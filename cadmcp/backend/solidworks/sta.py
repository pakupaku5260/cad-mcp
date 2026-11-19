"""COM backend: STA thread and COM exception mapping (sole entry)."""
from __future__ import annotations

import gc
import logging
import queue
import threading
import time
import traceback
from typing import Any

from cadmcp.errors import CadMcpError, SideEffect, fail

from ._helpers import _get, _is_server_gone, _scrub
from .probe import Win32DialogProbe

log = logging.getLogger(__name__)

_COM_LOST_HINT_BASE = (
    "Restart SolidWorks if it has exited, then retry the same call "
    "(do not restart the cadmcp server; it will reattach)."
)
_COM_LOST_HINT_UNSAVED = (
    " Unsaved document changes were likely lost with the SolidWorks process; "
    "use open_document on a saved path or new_part/new_assembly—nothing is auto-reopened."
)


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
        # F5 disconnect / reattach
        self._com_lost = False
        self._had_session = False
        self._unsaved_at_disconnect = False
        self._last_doc_snapshot: dict[str, Any] | None = None
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
        self._had_session = True
        self._com_lost = False

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
            from cadmcp.dialog_policy import classify_dialog, dialog_context, hint_for_policy

            for w in Win32DialogProbe().scan():
                if w.modal is True:
                    text = getattr(w, "text", None)
                    buttons = list(getattr(w, "buttons", None) or [])
                    policy = classify_dialog(
                        title=w.title,
                        text=text or "",
                        buttons=buttons,
                    )
                    # Progress wait UI (e.g. STEP Open Progress) — keep waiting, do not abort.
                    if not policy.blocks_sta:
                        continue
                    dlg = dialog_context(
                        title=w.title,
                        text=text,
                        buttons=buttons,
                        modal=w.modal,
                    )
                    return fail(
                        "EXEC_BLOCKED",
                        f"Modal dialog is blocking: {w.title} ({w.class_name})",
                        hint_for_policy(policy),
                        side_effect=SideEffect.APPLIED if applied else SideEffect.NONE,
                        title=w.title,
                        class_name=w.class_name,
                        rect=list(w.rect),
                        dialog=dlg,
                        dialog_kind=policy.kind,
                    )
        except Exception:
            log.debug("Modal probe failed: %s", traceback.format_exc())
        return None

    def _call(self, fn, timeout: float = 60.0):
        # Pre-dispatch disconnect: connection already known lost / stale handle cleared
        if self._com_lost or (self._had_session and self.sw is None):
            raise self._com_lost_error(mid_call=False)
        if not self._ready.is_set() or self.sw is None:
            raise self._attach_failed()
        if threading.current_thread() is self._thread:
            try:
                value = fn()
            except Exception as exc:
                if _is_server_gone(exc):
                    self._mark_disconnected(mid_call=True)
                    raise self._com_lost_error(mid_call=True) from None
                raise
            self._refresh_doc_snapshot_safe()
            return value
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
                self._mark_disconnected(mid_call=True)
                raise self._com_lost_error(mid_call=True) from None
            mapped = self._map_error(value)
            if mapped.code == "COM_LOST":
                raise mapped
            raise mapped
        self._refresh_doc_snapshot_safe()
        return value

    def _enqueue_sta(self, fn, timeout: float = 60.0):
        """Post work to the STA queue without requiring a live ``sw`` handle (used by reattach)."""
        if self._thread is None or not self._thread.is_alive():
            raise fail(
                "COM_ATTACH_FAILED",
                "STA COM thread is not running",
                "Call reattach after ensuring the CAD backend was started; or restart the server if STA cannot recover",
                side_effect=SideEffect.NONE,
            )
        if threading.current_thread() is self._thread:
            return fn()
        q: queue.Queue = queue.Queue()
        self._queue.put((fn, q))
        deadline = time.monotonic() + timeout
        while True:
            try:
                kind, value = q.get(timeout=1.0)
                break
            except queue.Empty:
                if time.monotonic() >= deadline:
                    raise fail(
                        "COM_ATTACH_FAILED",
                        f"reattach did not return within {timeout:.0f}s",
                        "Check SolidWorks/DCOM; retry reattach once SolidWorks is responsive",
                        side_effect=SideEffect.NONE,
                    ) from None
        if kind == "err":
            if isinstance(value, CadMcpError):
                raise value
            if _is_server_gone(value):
                raise self._com_lost_error(mid_call=False) from None
            raise self._map_error(value)
        return value

    def reattach(self) -> dict:
        """Rebuild COM binding after COM_LOST. Does not open documents."""
        # If STA thread died, restart it (attach path); else rebind on the live STA.
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._ready.clear()
            self._attach_error = None
            self.sw = None
            self._capture_unsaved_from_snapshot()
            try:
                if hasattr(self, "_reset_session_state"):
                    self._reset_session_state()
            except Exception:
                log.debug("Session reset during reattach failed: %s", traceback.format_exc())
            try:
                self._start_sta()
            except CadMcpError:
                self._com_lost = True
                raise
            return {
                "reattached": True,
                "unsaved_at_disconnect": self._unsaved_at_disconnect,
                "sta_restarted": True,
            }

        def _fn() -> dict:
            return self._reattach_on_sta()

        return self._enqueue_sta(_fn)

    def _reattach_on_sta(self) -> dict:
        import win32com.client

        self._capture_unsaved_from_snapshot()
        self.sw = None
        try:
            if hasattr(self, "_reset_session_state"):
                self._reset_session_state()
        except Exception:
            log.debug("Session reset during reattach failed: %s", traceback.format_exc())

        try:
            self.sw = win32com.client.GetActiveObject("SldWorks.Application")
        except Exception as exc1:
            try:
                self.sw = win32com.client.DispatchEx("SldWorks.Application")
            except Exception as exc2:
                self._com_lost = True
                self.sw = None
                raise fail(
                    "SW_NOT_RUNNING",
                    f"Cannot reattach: SolidWorks is not running ({exc2})",
                    "Start SolidWorks, then retry the tool call (server need not restart)",
                    side_effect=SideEffect.NONE,
                    error1=str(exc1),
                    unsaved_at_disconnect=self._unsaved_at_disconnect,
                ) from exc2
        try:
            self.sw.Visible = True
        except Exception:
            pass
        self._com_lost = False
        self._had_session = True
        self._attach_error = None
        return {
            "reattached": True,
            "unsaved_at_disconnect": self._unsaved_at_disconnect,
            "sta_restarted": False,
        }

    def _mark_disconnected(self, *, mid_call: bool) -> None:
        self._com_lost = True
        self._capture_unsaved_from_snapshot()
        self.sw = None
        _ = mid_call  # documented for call sites; snapshot capture is shared

    def _capture_unsaved_from_snapshot(self) -> None:
        snap = self._last_doc_snapshot
        if not snap:
            return
        if bool(snap.get("modified")) or not snap.get("path"):
            self._unsaved_at_disconnect = True

    def _refresh_doc_snapshot_safe(self) -> None:
        """Best-effort snapshot after a successful primary COM call; never raises COM_LOST."""
        try:
            self._refresh_doc_snapshot()
        except Exception:
            log.debug("Doc snapshot refresh failed: %s", traceback.format_exc())

    def _refresh_doc_snapshot(self) -> None:
        """Update unsaved-detection cache. Failures here do not mark disconnect (primary call already OK)."""
        if self.sw is None:
            return
        try:
            doc = self.sw.ActiveDoc
        except Exception:
            return
        if doc is None:
            self._last_doc_snapshot = None
            return
        try:
            title = str(_get(doc, "GetTitle") or "")
        except Exception:
            title = ""
        try:
            path = _get(doc, "GetPathName") or None
            if path:
                path = str(path)
        except Exception:
            path = None
        try:
            modified = bool(_get(doc, "GetSaveFlag"))
        except Exception:
            modified = True
        self._last_doc_snapshot = {"title": title, "path": path, "modified": modified}

    def _com_lost_error(self, *, mid_call: bool) -> CadMcpError:
        hint = _COM_LOST_HINT_BASE
        if self._unsaved_at_disconnect:
            hint += _COM_LOST_HINT_UNSAVED
        else:
            hint += " If you had only saved documents open, reopen them with open_document after SolidWorks is up."
        if mid_call:
            hint += " Do not blindly retry a write: verify the model/document state first."
        return fail(
            "COM_LOST",
            "SolidWorks COM connection was lost (process exited or RPC disconnected)",
            hint,
            side_effect=SideEffect.UNKNOWN if mid_call else SideEffect.NONE,
            recoverable=True,
            unsaved_at_disconnect=self._unsaved_at_disconnect,
            mid_call=mid_call,
        )

    def _attach_failed(self) -> CadMcpError:
        if self._com_lost or (self._had_session and self.sw is None):
            return self._com_lost_error(mid_call=False)
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
        if _is_server_gone(exc):
            self._mark_disconnected(mid_call=True)
            return self._com_lost_error(mid_call=True)
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
