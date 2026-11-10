"""COM backend: STA thread and COM exception mapping (sole entry)."""
from __future__ import annotations

import gc
import logging
import queue
import threading
import time
import traceback

from cadmcp.errors import CadMcpError, SideEffect, fail

from ._helpers import _is_server_gone, _scrub
from .probe import Win32DialogProbe

log = logging.getLogger(__name__)


class STAThreadMixin:
    """STA thread + COM exception mapping. All business mixins depend on this base."""

    _instance: ComBackend | None = None  # noqa: F821 — forward ref to avoid sta importing backend
    _lock = threading.RLock()

    def _init_state(self) -> None:
        """Initialize infrastructure state (v1.2.2 section 4.3.1)."""
        self._thread: threading.Thread | None = None
        self._queue: queue.Queue = queue.Queue()
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._attach_error: tuple[Exception, Exception] | None = None
        # Note: `sw` is not initialized here; owned by COMConnectionMixin

    # ---------- Lifecycle ----------

    @classmethod
    def attach(cls) -> ComBackend:  # noqa: F821 — forward ref to avoid sta importing backend
        with cls._lock:
            if cls._instance is not None:
                return cls._instance
            inst = cls()
            try:
                inst._start_sta()
            except Exception:
                inst.stop()
                raise
            cls._instance = inst
            return inst

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self.sw = None
        cls = type(self)
        with cls._lock:
            if cls._instance is self:
                cls._instance = None

    def _start_sta(self) -> None:
        self._thread = threading.Thread(target=self._sta_loop, name="cadmcp-com", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=30):
            raise fail(
                "COM_ATTACH_FAILED",
                "STA COM thread did not become ready",
                "Check that SolidWorks is installed and pywin32 is available",
                side_effect=SideEffect.NONE,
            )
        if self.sw is None:
            exc1, exc2 = self._attach_error or (None, None)
            err = fail(
                "COM_ATTACH_FAILED",
                f"Unable to attach to or start SolidWorks: {exc2 or 'unknown reason'}",
                "Ensure SolidWorks is running or can be started via DispatchEx (check DCOM/permissions)",
                side_effect=SideEffect.NONE,
                error1=str(exc1) if exc1 else None,
            )
            if exc2 is not None:
                raise err from exc2
            raise err

    def _sta_loop(self) -> None:
        pythoncom = None
        try:
            import pythoncom
            import win32com.client

            pythoncom.CoInitialize()
            try:
                self.sw = win32com.client.GetActiveObject("SldWorks.Application")
            except Exception as exc:
                try:
                    self.sw = win32com.client.DispatchEx("SldWorks.Application")
                except Exception as exc2:
                    self._attach_error = (exc, exc2)
                    return
            try:
                self.sw.Visible = True
            except Exception:
                pass
            self._ready.set()
            while not self._stop.is_set():
                try:
                    fn, q = self._queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                try:
                    q.put(("ok", fn()))
                except Exception as exc:
                    log.debug("COM closure exception: %s", traceback.format_exc())
                    _scrub(exc)
                    q.put(("err", exc))
                fn = q = None
                gc.collect()
        except Exception as exc:
            self._attach_error = (exc, exc)
        finally:
            self._ready.set()
            self.sw = None
            gc.collect()
            if pythoncom is not None:
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass

    # ---------- COM calls ----------

    def _modal_block(self, *, applied: bool) -> CadMcpError | None:
        try:
            for w in Win32DialogProbe().scan():
                if w.modal is True:
                    return fail(
                        "EXEC_BLOCKED",
                        f"Modal dialog is blocking: {w.title} ({w.class_name})",
                        "Close modal dialogs in SolidWorks (prompts, warnings, confirmations) and retry",
                        side_effect=SideEffect.APPLIED if applied else SideEffect.NONE,
                        title=w.title,
                        class_name=w.class_name,
                        rect=list(w.rect),
                    )
        except Exception:
            log.debug("Modal probe failed: %s", traceback.format_exc())
        return None

    def _call(self, fn, timeout: float = 60.0):
        if not self._ready.is_set() or self.sw is None:
            raise self._attach_failed()
        if threading.current_thread() is self._thread:
            return fn()
        blocked = self._modal_block(applied=False)
        if blocked is not None:
            raise blocked
        q: queue.Queue = queue.Queue()
        t0 = time.perf_counter()
        self._queue.put((fn, q))
        deadline = time.monotonic() + timeout
        while True:
            try:
                kind, value = q.get(timeout=1.0)
                break
            except queue.Empty:
                blocked = self._modal_block(applied=True)
                if blocked is not None:
                    raise blocked from None
                if time.monotonic() >= deadline:
                    raise fail(
                        "COM_CALL_FAILED",
                        f"COM call did not return within {timeout:.0f}s (SolidWorks may have a modal dialog)",
                        "Switch to the SolidWorks window, check for dialogs, close them, and retry",
                        side_effect=SideEffect.APPLIED,
                    ) from None
        log.debug("COM call %s took %.2fs", fn.__qualname__, time.perf_counter() - t0)
        if kind == "err":
            if _is_server_gone(value):
                raise fail(
                    "SW_NOT_RUNNING",
                    "SolidWorks process exited or crashed (RPC disconnected)",
                    "Restart SolidWorks and retry",
                    side_effect=SideEffect.APPLIED,
                ) from None
            raise self._map_error(value)
        return value

    def _attach_failed(self) -> CadMcpError:
        if self._attach_error is not None:
            exc1, exc2 = self._attach_error
            return fail(
                "COM_ATTACH_FAILED",
                f"Unable to attach to or start SolidWorks: {exc2}",
                "Ensure SolidWorks is running or can be started via DispatchEx (check DCOM/permissions)",
                side_effect=SideEffect.NONE,
                error1=str(exc1),
            )
        return fail(
            "COM_ATTACH_FAILED",
            "COM backend is not ready",
            "Confirm SolidWorks is available and retry",
            side_effect=SideEffect.NONE,
        )

    def _com_failed(
        self,
        message: str,
        hint: str,
        *,
        side_effect: SideEffect = SideEffect.APPLIED,
        **context,
    ) -> CadMcpError:
        """Build COM_CALL_FAILED for logical failures (API returned False / state unchanged).

        Exceptions go through `_map_error`; business code must not call `fail(\"COM_CALL_FAILED\", ...)` directly.
        """
        return fail("COM_CALL_FAILED", message, hint, side_effect=side_effect, **context)

    def _map_error(self, exc: Exception) -> CadMcpError:
        if isinstance(exc, CadMcpError):
            return exc
        msg = str(exc)
        code = "COM_CALL_FAILED"
        hint = "Check parameters and retry; inspect SolidWorks dialog state if needed"
        if "NewDocument" in msg:
            code = "OPEN_FAILED"
            hint = "Check that the template path is valid"
        elif "OpenDoc" in msg:
            code = "OPEN_FAILED"
            hint = "Confirm the file exists, is not locked, and can be opened in SolidWorks"
        elif "Save" in msg:
            code = "SAVE_FAILED"
            hint = "Check path permissions, file locks, and any unhandled dialogs"
        elif "Attach" in msg or "GetActiveObject" in msg:
            code = "COM_ATTACH_FAILED"
            hint = "Confirm SolidWorks is in the foreground, or allow DispatchEx to launch it"
        return fail(code, f"COM call failed: {exc}", hint, side_effect=SideEffect.APPLIED)
