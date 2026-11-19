"""Window probe interface (v4 §6 W3-9): health answers which dialog may be blocking.

- Production scan (top-level windows, Windows APIs) is M1 and must live in the syscall
  allowlist (com_backend.py / cli.py); this module is protocol + fake only, so M0 executor
  and health path are fully testable on macOS.
- Contract: scan() must not use COM or the business thread; modal is true/false/unknown
  (None=unknown) so task panes are not reported as blockers.
"""
from __future__ import annotations

import time
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from cadmcp.dialog_policy import (
    Action,
    classify_dialog,
    dialog_context,
    match_button_text,
)
from cadmcp.errors import fail


class WindowInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    class_name: str
    rect: tuple[int, int, int, int]  # left, top, right, bottom
    modal: bool | None = None  # None = unknown (unread or unverified)
    # Additive (0.4.0 R1): optional child-control text for session_dialogs / EXEC_BLOCKED
    text: str | None = None
    buttons: list[str] | None = None


class DialogProbe(Protocol):
    def scan(self) -> list[WindowInfo]:
        """Enumerate top-level SolidWorks windows; no COM; callable from a side thread."""
        ...


class FakeDialogProbe:
    """Fake probe: programmable window list plus delay/error injection (M0 health tests)."""

    def __init__(
        self,
        windows: list[WindowInfo] | None = None,
        *,
        delay_s: float = 0.0,
        error: str | None = None,
    ) -> None:
        self._windows = list(windows or [])
        self._delay_s = delay_s
        self._error = error
        self.scan_calls = 0
        self.respond_calls: list[dict] = []

    def set_windows(self, windows: list[WindowInfo]) -> None:
        self._windows = list(windows)

    def scan(self) -> list[WindowInfo]:
        self.scan_calls += 1
        if self._delay_s:
            time.sleep(self._delay_s)
        if self._error:
            raise RuntimeError(self._error)
        return list(self._windows)

    def respond(self, action: Action, match: str | None = None) -> dict:
        """Whitelist respond (contract tests); records click without OS messages."""
        windows = self.scan()
        target = pick_dialog_target(windows, match)
        if target is None:
            raise fail(
                "INVALID_ARGUMENT",
                f"No dialog matched match={match!r}" if match else "No modal/classifiable dialog found",
                "Call session_dialogs first; pass match=title substring when multiple dialogs exist",
            )
        policy = classify_dialog(
            title=target.title,
            text=target.text or "",
            buttons=list(target.buttons or []),
        )
        if action not in policy.allowed:
            raise fail(
                "INVALID_ARGUMENT",
                f"action={action!r} refused for dialog kind={policy.kind}",
                policy.reason + "; " + f"allowed={sorted(policy.allowed) or 'none'}",
                dialog=dialog_context(
                    title=target.title,
                    text=target.text,
                    buttons=list(target.buttons or []),
                    modal=target.modal,
                ),
                kind=policy.kind,
                allowed=sorted(policy.allowed),
            )
        button = _find_button(target, action)
        if button is None:
            raise fail(
                "INVALID_ARGUMENT",
                f"No button matching action={action!r} on dialog {target.title!r}",
                f"Visible buttons: {list(target.buttons or [])}",
                dialog=dialog_context(
                    title=target.title,
                    text=target.text,
                    buttons=list(target.buttons or []),
                    modal=target.modal,
                ),
            )
        entry = {
            "action": action,
            "match": match,
            "title": target.title,
            "button": button,
            "kind": policy.kind,
        }
        self.respond_calls.append(entry)
        return {
            "responded": True,
            "action": action,
            "button": button,
            "kind": policy.kind,
            "dialog": dialog_context(
                title=target.title,
                text=target.text,
                buttons=list(target.buttons or []),
                modal=target.modal,
            ),
        }


def pick_dialog_target(windows: list[WindowInfo], match: str | None) -> WindowInfo | None:
    candidates = list(windows)
    if match:
        needle = match.strip().lower()
        candidates = [
            w
            for w in candidates
            if needle in (w.title or "").lower()
            or needle in (w.text or "").lower()
            or any(needle in (b or "").lower() for b in (w.buttons or []))
        ]
        if not candidates:
            return None
    # Prefer modal blockers
    modal = [w for w in candidates if w.modal is True]
    pool = modal or candidates
    for w in pool:
        policy = classify_dialog(title=w.title, text=w.text or "", buttons=list(w.buttons or []))
        if policy.classified:
            return w
    return pool[0] if pool else None


def _find_button(window: WindowInfo, action: Action) -> str | None:
    for btn in window.buttons or []:
        if match_button_text(btn, action):
            return btn
    return None


def derive_blocker(windows: list[WindowInfo] | None, error: str | None) -> bool | None:
    """Coarse blocker signal (W8 row 3: /health blocker field; unauthenticated may expose).

    Scan ok → any modal window; missing/failed probe → None (unknown, same as modal tristate).
    Boolean only—no titles/classes (titles often include paths; detail needs auth, §11).
    """
    if error is not None or windows is None:
        return None
    return any(w.modal is True for w in windows)


def primary_modal_dialog(windows: list[WindowInfo] | None) -> WindowInfo | None:
    """First modal window, else first window, else None."""
    if not windows:
        return None
    for w in windows:
        if w.modal is True:
            return w
    return windows[0]
