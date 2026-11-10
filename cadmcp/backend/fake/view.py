"""Fake backend · view domain（S8i）。

S8i: set_view / screenshot (2 methods).

Dependencies (self, MRO):
- `_enter` / `_require_doc`（FakeBackend）

Imports:
- `cadmcp.backend.protocol.constants`（STANDARD_VIEWS）
- `cadmcp.errors`（fail）
"""
from __future__ import annotations

from pathlib import Path

from cadmcp.backend.protocol.constants import STANDARD_VIEWS
from cadmcp.errors import fail


class FakeViewMixin:
    """view domain (S8i: 2 methods)."""

    def _init_state(self) -> None:
        pass  # State owned by FakeBackend._init_state

    def set_view(self, view: str) -> None:
        self._enter("set_view", view=view)
        self._require_doc()
        if view not in STANDARD_VIEWS:
            raise fail(
                "INVALID_ARGUMENT",
                f"Unknown view: {view!r}",
                f"Available views: {', '.join(STANDARD_VIEWS)}",
                requested=view,
            )

    def screenshot(self, path: Path, view: str) -> None:
        self._enter("screenshot", path=path, view=view)
        self._require_doc()
        if view not in STANDARD_VIEWS:
            raise fail(
                "INVALID_ARGUMENT",
                f"Unknown view: {view!r}",
                f"Available views: {', '.join(STANDARD_VIEWS)}",
                requested=view,
            )
        path.write_bytes(b"\x89PNG\r\n\x1a\nFAKE-SCREENSHOT")
        