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


class WindowInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    class_name: str
    rect: tuple[int, int, int, int]  # left, top, right, bottom
    modal: bool | None = None  # None = unknown (unread or unverified)


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

    def scan(self) -> list[WindowInfo]:
        self.scan_calls += 1
        if self._delay_s:
            time.sleep(self._delay_s)
        if self._error:
            raise RuntimeError(self._error)
        return list(self._windows)


def derive_blocker(windows: list[WindowInfo] | None, error: str | None) -> bool | None:
    """Coarse blocker signal (W8 row 3: /health blocker field; unauthenticated may expose).

    Scan ok → any modal window; missing/failed probe → None (unknown, same as modal tristate).
    Boolean only—no titles/classes (titles often include paths; detail needs auth, §11).
    """
    if error is not None or windows is None:
        return None
    return any(w.modal is True for w in windows)
