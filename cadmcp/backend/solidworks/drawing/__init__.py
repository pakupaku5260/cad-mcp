"""COM backend drawing domain (views / annotations / sheets / layers / inspection).

Still exports `DrawingMixin` so `cadmcp.backend.solidworks.drawing.DrawingMixin` import
paths stay unchanged.
"""
from __future__ import annotations

from ._state import DrawingStateMixin
from .annotations import DrawingAnnotationsMixin
from .inspect import DrawingInspectMixin
from .layers import DrawingLayersMixin
from .placement import DrawingPlacementMixin
from .sheets import DrawingSheetsMixin
from .views import DrawingViewsMixin


class DrawingMixin(
    DrawingViewsMixin,
    DrawingAnnotationsMixin,
    DrawingPlacementMixin,
    DrawingSheetsMixin,
    DrawingLayersMixin,
    DrawingInspectMixin,
    DrawingStateMixin,
):
    """Drawing domain composite (state owned by DrawingStateMixin)."""


__all__ = ["DrawingMixin"]
