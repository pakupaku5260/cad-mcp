"""Core toolset: document, sketch, base features, query, screenshot.

Chat, batch, and spec macros all reach handlers here via Kernel.dispatch.
Units: writes convert via UnitContext to meters; reads convert back for clients.
Paths go through the workspace safety gates (ctx.workspace roots).

Exports `core_registry` / `register_core` at `cadmcp.toolsets.core`.
"""
from __future__ import annotations

from collections.abc import Collection

from cadmcp.registry import ToolRegistry, ToolSpec

from .document import SPECS as _DOCUMENT_SPECS
from .features import SPECS as _FEATURE_SPECS
from .meta import SPECS as _META_SPECS
from .query import SPECS as _QUERY_SPECS
from .reference import SPECS as _REFERENCE_SPECS
from .sketch import SPECS as _SKETCH_SPECS

_CORE_SPECS: tuple[ToolSpec, ...] = (
    *_DOCUMENT_SPECS,
    *_REFERENCE_SPECS,
    *_SKETCH_SPECS,
    *_FEATURE_SPECS,
    *_QUERY_SPECS,
    *_META_SPECS,
)


def register_core(registry: ToolRegistry, toolsets: Collection[str] | None = None) -> None:
    from cadmcp.toolsets.assembly import ASSEMBLY_SPECS
    from cadmcp.toolsets.drawing import DRAWING_SPECS
    from cadmcp.toolsets.export import EXPORT_SPECS
    from cadmcp.toolsets.features_adv import FEATURES_ADV_SPECS
    from cadmcp.toolsets.sheetmetal import SHEETMETAL_SPECS

    allowed = None if toolsets is None else set(toolsets)
    specs = [
        *_CORE_SPECS,
        *ASSEMBLY_SPECS,
        *FEATURES_ADV_SPECS,
        *SHEETMETAL_SPECS,
        *DRAWING_SPECS,
        *EXPORT_SPECS,
    ]
    for spec in specs:
        if allowed is not None and spec.toolset not in allowed:
            continue
        registry.register(spec)


def core_registry(toolsets: Collection[str] | None = None) -> ToolRegistry:
    """Build registry; toolsets=None registers all (default), else only listed toolsets."""
    registry = ToolRegistry()
    register_core(registry, toolsets)
    return registry


__all__ = ["_CORE_SPECS", "core_registry", "register_core"]
