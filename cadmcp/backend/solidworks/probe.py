"""COM backend: modal dialog probing."""
from __future__ import annotations

from cadmcp.probe import WindowInfo

from ._constants import SW_MAIN_WINDOW_CLASS, SW_MAIN_WINDOW_TITLE
from ._helpers import _derive_modal, _pid_of


class Win32DialogProbe:
    """Real window scan (W8 row 1): SW process top-level windows -> WindowInfo list."""

    def __init__(self, sw_pid: int | None = None) -> None:
        self._pid = sw_pid

    def _resolve_pid(self, win32gui, win32process) -> int | None:
        if self._pid:
            return self._pid
        hwnd = win32gui.FindWindow(SW_MAIN_WINDOW_CLASS, None)
        if not hwnd:
            hwnd = self._find_by_title(win32gui)
        if not hwnd:
            return None
        pid = _pid_of(hwnd, win32gui, win32process)
        if pid:
            self._pid = pid
        return pid

    @staticmethod
    def _find_by_title(win32gui) -> int:
        found = 0

        def cb(hwnd, _extra) -> None:
            nonlocal found
            if found:
                return
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    return
                title = win32gui.GetWindowText(hwnd) or ""
                if SW_MAIN_WINDOW_TITLE in title.upper():
                    found = hwnd
            except Exception:
                return

        win32gui.EnumWindows(cb, None)
        return found

    def scan(self) -> list[WindowInfo]:
        try:
            import win32gui
        except ImportError as exc:
            raise RuntimeError(f"win32gui unavailable (requires Windows + pywin32): {exc}") from exc
        try:
            import win32process
        except ImportError:
            win32process = None
        import win32con

        pid = self._resolve_pid(win32gui, win32process)
        if pid is None:
            raise RuntimeError(
                f"Failed to locate SolidWorks main window (class={SW_MAIN_WINDOW_CLASS} / "
                f"title~={SW_MAIN_WINDOW_TITLE}) — SolidWorks is not running"
            )

        found: list[WindowInfo] = []

        def cb(hwnd, _extra) -> None:
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    return
                if _pid_of(hwnd, win32gui, win32process) != pid:
                    return
                owner = win32gui.GetWindow(hwnd, win32con.GW_OWNER) or None
                owner_enabled = None
                if owner is not None:
                    try:
                        owner_enabled = bool(win32gui.IsWindowEnabled(owner))
                    except Exception:
                        owner_enabled = None
                found.append(
                    WindowInfo(
                        title=win32gui.GetWindowText(hwnd),
                        class_name=win32gui.GetClassName(hwnd),
                        rect=tuple(int(v) for v in win32gui.GetWindowRect(hwnd)),
                        modal=_derive_modal(owner, owner_enabled),
                    )
                )
            except Exception:
                return

        win32gui.EnumWindows(cb, None)
        return found
