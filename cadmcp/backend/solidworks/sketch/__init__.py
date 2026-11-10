"""COM backend sketch domain (lifecycle / draw / constraints / modify).

Still exports `SketchMixin` so `cadmcp.backend.solidworks.sketch.SketchMixin` import paths stay unchanged.
"""
from __future__ import annotations

from .constraints import SketchConstraintMixin
from .draw import SketchDrawMixin
from .lifecycle import SketchLifecycleMixin
from .modify import SketchModifyMixin


class SketchMixin(
    SketchLifecycleMixin,
    SketchDrawMixin,
    SketchConstraintMixin,
    SketchModifyMixin,
):
    """Sketch domain composite (state owned by SketchLifecycleMixin)."""


__all__ = [
    "SketchConstraintMixin",
    "SketchDrawMixin",
    "SketchLifecycleMixin",
    "SketchMixin",
    "SketchModifyMixin",
]
