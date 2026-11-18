"""Drawing session state: per-document datum, GD&T, weld and known-layer registries.

Does not touch COM or hold the drawing document handle.
Boundary: `_init_state` runs once from `ComBackend.__init__`; `_reset_drawing_l3_state`
clears the registries when a document is replaced.
"""

from __future__ import annotations


class DrawingStateMixin:
    """Per-document drawing registries (datums, GD&Ts, welds, known layers)."""

    def _init_state(self) -> None:
        self._drawing_datums: list[dict] = []
        self._drawing_gdts: list[dict] = []
        self._drawing_welds: list[dict] = []
        self._drawing_layers_known: list[str] = []
        self._drawing_tol_applied: list[dict] = []
        self._drawing_tol_failed: list[str] = []

    def _reset_drawing_l3_state(self) -> None:
        self._drawing_datums = []
        self._drawing_gdts = []
        self._drawing_welds = []
        self._drawing_layers_known = []
        self._drawing_tol_applied = []
        self._drawing_tol_failed = []
