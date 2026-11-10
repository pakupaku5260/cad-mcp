"""Advanced toolset: sketch enhancers, thread/helix/sweep, feature ops, view, selection.

Same unit rules as core: lengths converted via UnitContext to meters; backend uses SI.

Exports `FEATURES_ADV_SPECS` at `cadmcp.toolsets.features_adv`.
"""
from __future__ import annotations

from cadmcp.registry import ToolSpec

from .features import SPECS as _FEATURE_SPECS
from .path import SPECS as _PATH_SPECS
from .selection import SPECS as _SELECTION_SPECS
from .sketch import SPECS as _SKETCH_SPECS
from .surface import SPECS as _SURFACE_SPECS
from .view import SPECS as _VIEW_SPECS

FEATURES_ADV_SPECS: list[ToolSpec] = [
    *_SKETCH_SPECS,
    *_PATH_SPECS,
    *_SURFACE_SPECS,
    *_FEATURE_SPECS,
    *_VIEW_SPECS,
    *_SELECTION_SPECS,
]

__all__ = ["FEATURES_ADV_SPECS"]
