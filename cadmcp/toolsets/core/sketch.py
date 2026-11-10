"""Core toolset · sketches: open/close and rectangle/circle.

Split from toolsets/core.py by domain; handlers and ToolSpec unchanged.
"""

from __future__ import annotations

from cadmcp.kernel import OpContext
from cadmcp.registry import ToolSpec, make_schema

from ._common import _UNIT_PROP, _unit_ctx


def start_sketch(ctx: OpContext, plane: str = "Front Plane") -> dict:
    ctx.backend.begin_sketch(plane)
    return {"plane": plane, "sketch_open": True}


def sketch_rectangle(
    ctx: OpContext,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    z1: float = 0.0,
    z2: float = 0.0,
    unit: str = "mm",
) -> dict:
    uc = _unit_ctx(ctx, unit)
    ctx.backend.draw_rectangle(
        uc.to_m(x1),
        uc.to_m(y1),
        uc.to_m(x2),
        uc.to_m(y2),
        uc.to_m(z1),
        uc.to_m(z2),
    )
    sk = ctx.backend.active_sketch()
    return {"entity_count": sk.entity_count if sk else 0, "unit": uc.external_unit}


def sketch_circle(
    ctx: OpContext,
    cx: float,
    cy: float,
    r: float,
    cz: float = 0.0,
    unit: str = "mm",
) -> dict:
    uc = _unit_ctx(ctx, unit)
    ctx.backend.draw_circle(uc.to_m(cx), uc.to_m(cy), uc.to_m(r), uc.to_m(cz))
    sk = ctx.backend.active_sketch()
    return {"entity_count": sk.entity_count if sk else 0, "unit": uc.external_unit}


def end_sketch(ctx: OpContext) -> dict:
    info = ctx.backend.end_sketch()
    return {"name": info.name, "plane": info.plane, "entity_count": info.entity_count}


SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="start_sketch",
        description="Start a 2D sketch on a list_planes name, or plane=3D; end it before features.",
        input_schema=make_schema(
            {"plane": {"type": "string", "description": "list_planes name or 3D."}}
        ),
        handler=start_sketch,
        mutating=True,
    ),
    ToolSpec(
        name="sketch_rectangle",
        description=(
            "Draw a corner rectangle from (x1,y1[,z1]) to (x2,y2[,z2]). "
            "No driving dimension — call add_sketch_dimension before end_sketch "
            "for PARAM. z1/z2 only for start_sketch(plane=3D)."
        ),
        input_schema=make_schema(
            {
                "x1": {"type": "number"},
                "y1": {"type": "number"},
                "x2": {"type": "number"},
                "y2": {"type": "number"},
                "z1": {"type": "number", "description": "Start Z; 3D sketch only."},
                "z2": {"type": "number", "description": "Opposite-corner Z; 3D sketch only."},
                "unit": _UNIT_PROP,
            },
            ["x1", "y1", "x2", "y2"],
        ),
        handler=sketch_rectangle,
        mutating=True,
    ),
    ToolSpec(
        name="sketch_circle",
        description=(
            "Draw a circle centered at (cx,cy[,cz]) with radius r. "
            "No driving dimension — call add_sketch_dimension before end_sketch "
            "for PARAM. cz only for start_sketch(plane=3D)."
        ),
        input_schema=make_schema(
            {
                "cx": {"type": "number"},
                "cy": {"type": "number"},
                "r": {"type": "number", "exclusiveMinimum": 0},
                "cz": {"type": "number", "description": "Center Z; 3D sketch only."},
                "unit": _UNIT_PROP,
            },
            ["cx", "cy", "r"],
        ),
        handler=sketch_circle,
        mutating=True,
    ),
    ToolSpec(
        name="end_sketch",
        description="Finish the open sketch and keep its profile for the next extrude.",
        input_schema=make_schema({}),
        handler=end_sketch,
        mutating=True,
    ),
)
