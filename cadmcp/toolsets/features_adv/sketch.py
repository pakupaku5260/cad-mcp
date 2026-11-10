"""features_adv · sketch_adv: draw, dimensions, offset/trim/mirror, re-edit.

Split from toolsets/features_adv.py by domain; handlers and ToolSpec unchanged.
"""

from __future__ import annotations

from cadmcp.backend.protocol.parsers import normalize_spline_points
from cadmcp.errors import fail
from cadmcp.kernel import OpContext
from cadmcp.registry import ToolSpec, make_schema
from cadmcp.units import UnitContext

from ._common import _UNIT_DESC, _UNIT_ENUM, _unit_ctx


def sketch_line(
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
    ctx.backend.sketch_line(
        uc.to_m(x1), uc.to_m(y1), uc.to_m(x2), uc.to_m(y2), uc.to_m(z1), uc.to_m(z2)
    )
    sk = ctx.backend.active_sketch()
    return {"entity_count": sk.entity_count if sk else 0, "unit": uc.external_unit}


def sketch_arc(
    ctx: OpContext,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    x3: float | None = None,
    y3: float | None = None,
    cx: float | None = None,
    cy: float | None = None,
    ccw: bool = True,
    z1: float = 0.0,
    z2: float = 0.0,
    z3: float = 0.0,
    cz: float = 0.0,
    unit: str = "mm",
) -> dict:
    uc = _unit_ctx(ctx, unit)
    ctx.backend.sketch_arc(
        uc.to_m(x1),
        uc.to_m(y1),
        uc.to_m(x2),
        uc.to_m(y2),
        None if x3 is None else uc.to_m(x3),
        None if y3 is None else uc.to_m(y3),
        None if cx is None else uc.to_m(cx),
        None if cy is None else uc.to_m(cy),
        ccw,
        uc.to_m(z1),
        uc.to_m(z2),
        uc.to_m(z3),
        uc.to_m(cz),
    )
    sk = ctx.backend.active_sketch()
    return {"entity_count": sk.entity_count if sk else 0, "unit": uc.external_unit}


def sketch_spline(
    ctx: OpContext,
    points: list,
    closed: bool = False,
    unit: str = "mm",
) -> dict:
    if not isinstance(points, list):
        raise fail(
            "INVALID_ARGUMENT",
            "points must be a list of points",
            "Pass points=[[x,y],...] or [[x,y,z],...]",
        )
    uc = _unit_ctx(ctx, unit)
    raw: list[tuple[float, ...]] = []
    for p in points:
        if not isinstance(p, (list, tuple)) or len(p) not in (2, 3):
            raise fail(
                "INVALID_ARGUMENT",
                "Each point must be [x, y] or [x, y, z]",
                "Each entry in points must have 2 or 3 numbers",
            )
        if len(p) == 2:
            raw.append((uc.to_m(float(p[0])), uc.to_m(float(p[1]))))
        else:
            raw.append(
                (uc.to_m(float(p[0])), uc.to_m(float(p[1])), uc.to_m(float(p[2])))
            )
    pts = normalize_spline_points(raw, closed)
    ctx.backend.sketch_spline(pts, closed)
    out = _sketch_count(ctx, uc)
    out["closed"] = bool(closed)
    out["point_count"] = len(pts)
    return out


def sketch_polygon(
    ctx: OpContext,
    sides: int,
    radius: float,
    polygon_type: str = "inscribed",
    cx: float = 0.0,
    cy: float = 0.0,
    cz: float = 0.0,
    unit: str = "mm",
) -> dict:
    uc = _unit_ctx(ctx, unit)
    lines = ctx.backend.sketch_polygon(
        sides,
        uc.to_m(radius),
        polygon_type,
        uc.to_m(cx),
        uc.to_m(cy),
        uc.to_m(cz),
    )
    sk = ctx.backend.active_sketch()
    side_out = [
        {
            "index": ln.index,
            "x0": uc.from_m(ln.x0_m),
            "y0": uc.from_m(ln.y0_m),
            "x1": uc.from_m(ln.x1_m),
            "y1": uc.from_m(ln.y1_m),
        }
        for ln in lines
    ]
    return {
        "entity_count": sk.entity_count if sk else 0,
        "sides": side_out,
        "unit": uc.external_unit,
    }


def add_sketch_dimension(
    ctx: OpContext,
    value: float,
    x1: float | None = None,
    y1: float | None = None,
    x2: float | None = None,
    y2: float | None = None,
    entity1: int | None = None,
    entity2: int | None = None,
    unit: str = "mm",
) -> dict:
    if value <= 0:
        raise fail("INVALID_ARGUMENT", "Dimension value must be positive", "Pass value > 0")
    if entity2 is not None and entity1 is None:
        raise fail("INVALID_ARGUMENT", "entity2 requires entity1 as well", "Provide index for both edges")
    by_index = entity1 is not None
    by_points = x1 is not None and y1 is not None and x2 is not None and y2 is not None
    if not by_index and not by_points:
        raise fail(
            "INVALID_ARGUMENT",
            "Need entity indices or two point pairs",
            "Lines/circles: x1,y1,x2,y2; polygon opposite edges: entity1 and entity2",
        )
    uc = _unit_ctx(ctx, unit)
    ctx.backend.add_sketch_dimension(
        uc.to_m(x1 or 0.0),
        uc.to_m(y1 or 0.0),
        uc.to_m(x2 or 0.0),
        uc.to_m(y2 or 0.0),
        uc.to_m(value),
        entity1,
        entity2,
    )
    return {"unit": uc.external_unit}


def add_sketch_relation(
    ctx: OpContext,
    relation: str,
    entity1: int,
    entity2: int | None = None,
    entity3: int | None = None,
) -> dict:
    ctx.backend.add_sketch_relation(relation, entity1, entity2, entity3)
    return {"relation": relation}


def _entity_payload(ref, uc: UnitContext) -> dict:
    item = {
        "index": ref.index,
        "kind": ref.kind,
        "points": [[uc.from_m(x), uc.from_m(y)] for x, y in ref.points_m],
        "construction": ref.construction,
    }
    if ref.radius_m is not None:
        item["radius"] = uc.from_m(ref.radius_m)
    return item


def list_sketch_entities(ctx: OpContext, sketch: str | None = None, unit: str = "mm") -> dict:
    uc = _unit_ctx(ctx, unit)
    rows = [_entity_payload(ref, uc) for ref in ctx.backend.list_sketch_entities(sketch)]
    return {
        "count": len(rows),
        "sketch": sketch,
        "unit": uc.external_unit,
        "entities": rows,
    }


def edit_sketch(ctx: OpContext, name: str) -> dict:
    info = ctx.backend.edit_sketch(name)
    return {"name": info.name, "plane": info.plane, "entity_count": info.entity_count}


def sketch_status(ctx: OpContext, sketch: str | None = None) -> dict:
    st = ctx.backend.sketch_solve_status(sketch)
    return {"state": st.state, "dof": st.dof, "sketch": sketch}


def _sketch_count(ctx: OpContext, uc: UnitContext) -> dict:
    sk = ctx.backend.active_sketch()
    return {"entity_count": sk.entity_count if sk else 0, "unit": uc.external_unit}


def sketch_offset(
    ctx: OpContext, distance: float, inward: bool = False, unit: str = "mm"
) -> dict:
    uc = _unit_ctx(ctx, unit)
    ctx.backend.sketch_offset(uc.to_m(distance), inward)
    return _sketch_count(ctx, uc)


def sketch_trim(
    ctx: OpContext, entity1: int, entity2: int, radius: float, unit: str = "mm"
) -> dict:
    uc = _unit_ctx(ctx, unit)
    ctx.backend.sketch_trim(entity1, entity2, uc.to_m(radius))
    return _sketch_count(ctx, uc)


def sketch_mirror(ctx: OpContext, axis: int) -> dict:
    ctx.backend.sketch_mirror(axis)
    sk = ctx.backend.active_sketch()
    return {"entity_count": sk.entity_count if sk else 0, "axis": axis}


SPECS: list[ToolSpec] = [
    ToolSpec(
        name="sketch_line",
        toolset="sketch_adv",
        description="Draw a line. Optional z1/z2 for 3D sketches (start_sketch plane=3D).",
        input_schema=make_schema(
            {
                "x1": {"type": "number"},
                "y1": {"type": "number"},
                "x2": {"type": "number"},
                "y2": {"type": "number"},
                "z1": {"type": "number", "description": "Start Z; 3D sketch only."},
                "z2": {"type": "number", "description": "End Z; 3D sketch only."},
                "unit": {"type": "string", "enum": _UNIT_ENUM, "description": _UNIT_DESC},
            },
            ["x1", "y1", "x2", "y2"],
        ),
        handler=sketch_line,
        mutating=True,
    ),
    ToolSpec(
        name="sketch_arc",
        toolset="sketch_adv",
        description=(
            "Draw an arc. Three-point: start (x1,y1[,z1]), through (x2,y2[,z2]), "
            "end (x3,y3[,z3]). Center: cx,cy[,cz] with start/end; ccw=true is "
            "counterclockwise. z*/cz only for start_sketch(plane=3D)."
        ),
        input_schema=make_schema(
            {
                "x1": {"type": "number", "description": "Start X."},
                "y1": {"type": "number", "description": "Start Y."},
                "x2": {"type": "number", "description": "Through X (3-point) or end X (center)."},
                "y2": {"type": "number", "description": "Through Y (3-point) or end Y (center)."},
                "x3": {"type": "number", "description": "End X for three-point mode."},
                "y3": {"type": "number", "description": "End Y for three-point mode."},
                "cx": {"type": "number", "description": "Center X for center mode."},
                "cy": {"type": "number", "description": "Center Y for center mode."},
                "z1": {"type": "number", "description": "Start Z; 3D sketch only."},
                "z2": {"type": "number", "description": "Through/end Z; 3D sketch only."},
                "z3": {"type": "number", "description": "End Z for three-point; 3D only."},
                "cz": {"type": "number", "description": "Center Z for center mode; 3D only."},
                "ccw": {
                    "type": "boolean",
                    "description": "Center-mode direction; default true (counterclockwise).",
                },
                "unit": {"type": "string", "enum": _UNIT_ENUM, "description": _UNIT_DESC},
            },
            ["x1", "y1", "x2", "y2"],
        ),
        handler=sketch_arc,
        mutating=True,
    ),
    ToolSpec(
        name="sketch_spline",
        toolset="sketch_adv",
        description=(
            "Draw a spline through points [[x,y],...] or [[x,y,z],...] "
            "(z only for start_sketch plane=3D); closed=true repeats the first point."
        ),
        input_schema=make_schema(
            {
                "points": {
                    "type": "array",
                    "minItems": 2,
                    "items": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 3,
                        "items": {"type": "number"},
                    },
                },
                "closed": {"type": "boolean"},
                "unit": {"type": "string", "enum": _UNIT_ENUM, "description": _UNIT_DESC},
            },
            ["points"],
        ),
        handler=sketch_spline,
        mutating=True,
    ),
    ToolSpec(
        name="sketch_polygon",
        toolset="sketch_adv",
        description=(
            "Draw a regular polygon centered at (cx,cy[,cz]); returns each side's "
            "index and endpoints (use those indexes with add_sketch_dimension for "
            "across-flats). cz only for start_sketch(plane=3D). On planar sketches "
            "the construction circle is removed so entity_count equals the side count."
        ),
        input_schema=make_schema(
            {
                "sides": {"type": "integer", "minimum": 3, "description": "Number of sides."},
                "radius": {"type": "number", "description": "Circumscribed/inscribed radius."},
                "polygon_type": {
                    "type": "string",
                    "default": "inscribed",
                    "enum": ["inscribed", "circumscribed"],
                },
                "cx": {"type": "number", "description": "Center X."},
                "cy": {"type": "number", "description": "Center Y."},
                "cz": {"type": "number", "description": "Center Z; 3D sketch only."},
                "unit": {"type": "string", "enum": _UNIT_ENUM, "description": _UNIT_DESC},
            },
            ["sides", "radius"],
        ),
        handler=sketch_polygon,
        mutating=True,
    ),
    ToolSpec(
        name="add_sketch_dimension",
        toolset="sketch_adv",
        description=(
            "Add a driving dimension (required before PARAM/RECIPE can "
            "set_dimension a sketch size). Line length or circle diameter from "
            "two points (x1,y1,x2,y2); or across-flats / segment by entity1[, "
            "entity2] from sketch_polygon sides."
        ),
        input_schema=make_schema(
            {
                "value": {"type": "number", "description": "Dimension value > 0."},
                "x1": {"type": "number"},
                "y1": {"type": "number"},
                "x2": {"type": "number"},
                "y2": {"type": "number"},
                "entity1": {"type": "integer", "description": "Sketch segment index."},
                "entity2": {
                    "type": "integer",
                    "description": "Second segment index for across-flats.",
                },
                "unit": {"type": "string", "enum": _UNIT_ENUM, "description": _UNIT_DESC},
            },
            ["value"],
        ),
        handler=add_sketch_dimension,
        mutating=True,
    ),
    ToolSpec(
        name="add_sketch_relation",
        toolset="sketch_adv",
        description=(
            "Add a geometric relation: horizontal/vertical/parallel/perpendicular/"
            "tangent/coincident/equal/concentric/colinear/fixed/midpoint/symmetric. "
            "coincident uses nearest endpoints; midpoint: entity1 provides the point, "
            "entity2 is the line; symmetric: entity1/entity2 + entity3 as the mirror axis."
        ),
        input_schema=make_schema(
            {
                "relation": {"type": "string"},
                "entity1": {"type": "integer"},
                "entity2": {"type": "integer"},
                "entity3": {
                    "type": "integer",
                    "description": "Mirror axis segment index (symmetric only).",
                },
            },
            ["relation", "entity1"],
        ),
        handler=add_sketch_relation,
        mutating=True,
    ),
    ToolSpec(
        name="list_sketch_entities",
        toolset="sketch_adv",
        description=(
            "List sketch entities (index, kind, UV points). Omit sketch to use the "
            "active open sketch; pass Sketch1 (or the name from end_sketch) for a finished one."
        ),
        input_schema=make_schema(
            {
                "sketch": {"type": "string", "description": "Sketch name; omit for the open sketch."},
                "unit": {"type": "string", "enum": _UNIT_ENUM, "description": _UNIT_DESC},
            }
        ),
        handler=list_sketch_entities,
        mutating=False,
        timeout_class="fast",
    ),
    ToolSpec(
        name="edit_sketch",
        toolset="sketch_adv",
        description=(
            "Re-enter a finished sketch by name (Sketch1). Fails if another sketch is already open. "
            "Call end_sketch when done; the sketch keeps its name."
        ),
        input_schema=make_schema(
            {"name": {"type": "string", "description": "Sketch name from end_sketch / list_features."}},
            ["name"],
        ),
        handler=edit_sketch,
        mutating=True,
    ),
    ToolSpec(
        name="sketch_status",
        toolset="sketch_adv",
        description=(
            "Read sketch constrained status: under_defined, fully_defined, or over_defined. "
            "Omit sketch to use the active open sketch."
        ),
        input_schema=make_schema(
            {
                "sketch": {"type": "string", "description": "Sketch name; omit for the open sketch."},
            }
        ),
        handler=sketch_status,
        mutating=False,
        timeout_class="fast",
    ),
    ToolSpec(
        name="sketch_offset",
        toolset="sketch_adv",
        description="Offset the open sketch contour; inward uses a negative offset (frame).",
        input_schema=make_schema(
            {
                "distance": {"type": "number"},
                "inward": {"type": "boolean", "default": False},
                "unit": {"type": "string", "enum": _UNIT_ENUM, "description": _UNIT_DESC},
            },
            ["distance"],
        ),
        handler=sketch_offset,
        mutating=True,
    ),
    ToolSpec(
        name="sketch_trim",
        toolset="sketch_adv",
        description="Fillet two sketch segments (CreateFillet; SketchTrim is unused on 2025).",
        input_schema=make_schema(
            {
                "entity1": {"type": "integer"},
                "entity2": {"type": "integer"},
                "radius": {"type": "number"},
                "unit": {"type": "string", "enum": _UNIT_ENUM, "description": _UNIT_DESC},
            },
            ["entity1", "entity2", "radius"],
        ),
        handler=sketch_trim,
        mutating=True,
    ),
    ToolSpec(
        name="sketch_mirror",
        toolset="sketch_adv",
        description="Mirror sketch entities about a line (that line becomes construction).",
        input_schema=make_schema(
            {"axis": {"type": "integer", "description": "Index of the mirror-axis line."}},
            ["axis"],
        ),
        handler=sketch_mirror,
        mutating=True,
    ),
]
