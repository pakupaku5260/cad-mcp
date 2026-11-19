"""COM backend: modal dialog probing + whitelist BM_CLICK respond (no COM)."""
from __future__ import annotations

from cadmcp.dialog_policy import (
    Action,
    classify_dialog,
    dialog_context,
    match_button_text,
)
from cadmcp.errors import fail
from cadmcp.probe import WindowInfo

from ._constants import SW_MAIN_WINDOW_CLASS, SW_MAIN_WINDOW_TITLE
from ._helpers import _derive_modal, _pid_of

# winuser.h BM_CLICK — side-thread window message only (never COM / STA).
_BM_CLICK = 0x00F5


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

    @staticmethod
    def _child_text_and_buttons(win32gui, hwnd: int) -> tuple[str | None, list[str]]:
        """Enumerate child controls: STATIC/EDIT → text; BUTTON → buttons list."""
        texts: list[str] = []
        buttons: list[str] = []

        def cb(child, _extra) -> None:
            try:
                if not win32gui.IsWindowVisible(child):
                    return
                cls = (win32gui.GetClassName(child) or "").upper()
                caption = (win32gui.GetWindowText(child) or "").strip()
                if not caption:
                    return
                if cls == "BUTTON" or cls.endswith("BUTTON"):
                    buttons.append(caption)
                elif cls in {"STATIC", "EDIT", "RICHEDIT", "RICHEDIT20A", "RICHEDIT20W"} or "STATIC" in cls:
                    texts.append(caption)
            except Exception:
                return

        try:
            win32gui.EnumChildWindows(hwnd, cb, None)
        except Exception:
            return None, []
        body = "\n".join(texts) if texts else None
        return body, buttons

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
                text, buttons = self._child_text_and_buttons(win32gui, hwnd)
                found.append(
                    WindowInfo(
                        title=win32gui.GetWindowText(hwnd),
                        class_name=win32gui.GetClassName(hwnd),
                        rect=tuple(int(v) for v in win32gui.GetWindowRect(hwnd)),
                        modal=_derive_modal(owner, owner_enabled),
                        text=text,
                        buttons=buttons or None,
                    )
                )
            except Exception:
                return

        win32gui.EnumWindows(cb, None)
        return found

    def respond(self, action: Action, match: str | None = None) -> dict:
        """Whitelist BM_CLICK on a matching button; side-thread safe (no COM)."""
        try:
            import win32gui
        except ImportError as exc:
            raise fail(
                "INTERNAL_ERROR",
                f"win32gui unavailable: {exc}",
                "session_respond requires Windows + pywin32",
            ) from exc
        import win32con

        windows = self.scan()
        target_info, target_hwnd = self._pick_hwnd(win32gui, windows, match)
        if target_info is None or target_hwnd is None:
            raise fail(
                "INVALID_ARGUMENT",
                f"No dialog matched match={match!r}" if match else "No modal/classifiable dialog found",
                "Call session_dialogs first; pass match=title substring when multiple dialogs exist",
            )
        policy = classify_dialog(
            title=target_info.title,
            text=target_info.text or "",
            buttons=list(target_info.buttons or []),
        )
        if action not in policy.allowed:
            raise fail(
                "INVALID_ARGUMENT",
                f"action={action!r} refused for dialog kind={policy.kind}",
                policy.reason + f"; allowed={sorted(policy.allowed) or 'none'}",
                dialog=dialog_context(
                    title=target_info.title,
                    text=target_info.text,
                    buttons=list(target_info.buttons or []),
                    modal=target_info.modal,
                ),
                kind=policy.kind,
                allowed=sorted(policy.allowed),
            )
        btn_hwnd, btn_text = self._find_button_hwnd(win32gui, target_hwnd, action)
        if btn_hwnd is None:
            raise fail(
                "INVALID_ARGUMENT",
                f"No button matching action={action!r} on dialog {target_info.title!r}",
                f"Visible buttons: {list(target_info.buttons or [])}",
                dialog=dialog_context(
                    title=target_info.title,
                    text=target_info.text,
                    buttons=list(target_info.buttons or []),
                    modal=target_info.modal,
                ),
            )
        # Prefer PostMessage so we never block the detector thread on a hung UI.
        try:
            win32gui.PostMessage(btn_hwnd, _BM_CLICK, 0, 0)
        except Exception:
            win32gui.SendMessage(btn_hwnd, win32con.BM_CLICK if hasattr(win32con, "BM_CLICK") else _BM_CLICK, 0, 0)
        return {
            "responded": True,
            "action": action,
            "button": btn_text,
            "kind": policy.kind,
            "dialog": dialog_context(
                title=target_info.title,
                text=target_info.text,
                buttons=list(target_info.buttons or []),
                modal=target_info.modal,
            ),
        }

    def _pick_hwnd(
        self, win32gui, windows: list[WindowInfo], match: str | None
    ) -> tuple[WindowInfo | None, int | None]:
        from cadmcp.probe import pick_dialog_target

        target = pick_dialog_target(windows, match)
        if target is None:
            return None, None
        # Re-resolve hwnd by title+class+rect (scan order stable enough for respond)
        hwnds: list[int] = []

        def cb(hwnd, _extra) -> None:
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    return
                title = win32gui.GetWindowText(hwnd) or ""
                cls = win32gui.GetClassName(hwnd) or ""
                rect = tuple(int(v) for v in win32gui.GetWindowRect(hwnd))
                if title == target.title and cls == target.class_name and rect == target.rect:
                    hwnds.append(hwnd)
            except Exception:
                return

        win32gui.EnumWindows(cb, None)
        return target, (hwnds[0] if hwnds else None)

    @staticmethod
    def _find_button_hwnd(win32gui, parent: int, action: Action) -> tuple[int | None, str | None]:
        found: list[tuple[int, str]] = []

        def cb(child, _extra) -> None:
            try:
                cls = (win32gui.GetClassName(child) or "").upper()
                if cls != "BUTTON" and not cls.endswith("BUTTON"):
                    return
                caption = (win32gui.GetWindowText(child) or "").strip()
                if caption and match_button_text(caption, action):
                    found.append((child, caption))
            except Exception:
                return

        win32gui.EnumChildWindows(parent, cb, None)
        if not found:
            return None, None
        return found[0]
