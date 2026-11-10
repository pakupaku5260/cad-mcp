"""Core toolset · query: mass/geometry/features/dimensions/equations/color/entities.

get_selection moved to the selection toolset (core budget).
Wave 7 PARAM: part_parameters / update_parameters batch read/write.
"""

from __future__ import annotations

import math
from typing import Any

from cadmcp.errors import CadMcpError, fail
from cadmcp.kernel import OpContext
from cadmcp.registry import ToolSpec, make_schema
from cadmcp.toolsets.paging import paginate

from ._common import _UNIT_PROP, _public_face, _unit_ctx


def get_mass_properties(ctx: OpContext) -> dict:
    mp = ctx.backend.mass_properties()
    u = ctx.units
    return {
        "volume": u.volume_from_m3(mp.volume_m3),
        "surface_area": u.area_from_m2(mp.surface_area_m2),
        "mass_kg": mp.mass_kg,
        "center_of_mass": list(u.tuple_from_m(mp.center_of_mass_m)),
        "length_unit": u.external_unit,
        "area_unit": f"{u.external_unit}2",
        "volume_unit": f"{u.external_unit}3",
    }


def get_geometry(ctx: OpContext) -> dict:
    """Geometry fingerprint; same shape as delta.after for external change detection."""
    fp = ctx.backend.fingerprint()
    u = ctx.units
    return {
        "volume": u.volume_from_m3(fp.volume_m3),
        "surface_area": u.area_from_m2(fp.surface_area_m2),
        "mass_kg": fp.mass_kg,
        "face_count": fp.face_count,
        "edge_count": fp.edge_count,
        "bbox": list(u.tuple_from_m(fp.bbox_m)),
        "length_unit": u.external_unit,
        "area_unit": f"{u.external_unit}2",
        "volume_unit": f"{u.external_unit}3",
    }


def list_features(ctx: OpContext) -> dict:
    return {"features": [{"name": f.name, "kind": f.kind} for f in ctx.backend.list_features()]}


def list_dimensions(ctx: OpContext) -> dict:
    u = ctx.units
    rows = []
    for dim in ctx.backend.list_dimensions():
        if dim.kind == "angle":
            rows.append({
                "name": dim.name,
                "kind": "angle",
                "value": math.degrees(dim.value_si),
                "unit": "deg",
            })
        else:
            rows.append({
                "name": dim.name,
                "kind": "length",
                "value": u.from_m(dim.value_si),
                "unit": u.external_unit,
            })
    return {"count": len(rows), "dimensions": rows}


def set_color(ctx: OpContext, r: float, g: float, b: float) -> dict:
    rgb = ctx.backend.set_color(r, g, b)
    return {"r": rgb[0], "g": rgb[1], "b": rgb[2]}


def get_color(ctx: OpContext) -> dict:
    rgb = ctx.backend.get_color()
    if rgb is None:
        return {"r": None, "g": None, "b": None, "color": None}
    return {"r": rgb[0], "g": rgb[1], "b": rgb[2], "color": list(rgb)}


def set_dimension(ctx: OpContext, name: str, value: float, unit: str = "mm") -> dict:
    current = next((d for d in ctx.backend.list_dimensions() if d.name == name), None)
    if current is not None and current.kind == "angle":
        ref = ctx.backend.set_dimension(name, math.radians(value))
        return {
            "name": ref.name,
            "kind": "angle",
            "value": math.degrees(ref.value_si),
            "unit": "deg",
        }
    uc = _unit_ctx(ctx, unit)
    ref = ctx.backend.set_dimension(name, uc.to_m(value))
    return {
        "name": ref.name,
        "kind": ref.kind,
        "value": uc.from_m(ref.value_si),
        "unit": uc.external_unit,
    }


def list_equations(ctx: OpContext) -> dict:
    rows = [{"name": eq.name, "expression": eq.expression} for eq in ctx.backend.list_equations()]
    return {"count": len(rows), "equations": rows}


def set_equation(ctx: OpContext, name: str, expression: str) -> dict:
    ref = ctx.backend.set_equation(name, expression)
    return {"name": ref.name, "expression": ref.expression}


def _dimension_row(ctx: OpContext, dim: Any) -> dict:
    u = ctx.units
    if dim.kind == "angle":
        return {
            "name": dim.name,
            "kind": "angle",
            "value": math.degrees(dim.value_si),
            "unit": "deg",
        }
    return {
        "name": dim.name,
        "kind": "length",
        "value": u.from_m(dim.value_si),
        "unit": u.external_unit,
    }


def part_parameters(ctx: OpContext) -> dict:
    """Read dimensions, equations, and configurations in one call (wave 7 PARAM)."""
    dims = [_dimension_row(ctx, d) for d in ctx.backend.list_dimensions()]
    eqs = [{"name": eq.name, "expression": eq.expression} for eq in ctx.backend.list_equations()]
    active, names = ctx.backend.list_configurations()
    return {
        "dimensions": dims,
        "equations": eqs,
        "active_configuration": active,
        "configurations": list(names),
        "count": {
            "dimensions": len(dims),
            "equations": len(eqs),
            "configurations": len(names),
        },
    }


def update_parameters(
    ctx: OpContext,
    dimensions: list | None = None,
    equations: list | None = None,
    configuration: str | None = None,
    unit: str = "mm",
) -> dict:
    """Batch-write parameters: apply in order, stop on first failure; no auto-rollback.

    Returns applied / failed / not_applied. Validation before any write still raises INVALID_ARGUMENT.
    """
    dims = list(dimensions or [])
    eqs = list(equations or [])
    if configuration is None and not dims and not eqs:
        raise fail(
            "INVALID_ARGUMENT",
            "No parameter updates provided",
            "Pass at least one of dimensions, equations, or configuration",
        )

    pending: list[tuple[str, dict]] = []
    if configuration is not None:
        pending.append(("configuration", {"name": configuration}))
    for item in eqs:
        if not isinstance(item, dict) or "name" not in item or "expression" not in item:
            raise fail(
                "INVALID_ARGUMENT",
                "Each equations item must include name and expression",
                'e.g. [{"name":"D","expression":"80"}]',
            )
        pending.append(("equation", {"name": str(item["name"]), "expression": str(item["expression"])}))
    for item in dims:
        if not isinstance(item, dict) or "name" not in item or "value" not in item:
            raise fail(
                "INVALID_ARGUMENT",
                "Each dimensions item must include name and value",
                'e.g. [{"name":"D1@Boss-Extrude1","value":40}]',
            )
        pending.append(
            ("dimension", {"name": str(item["name"]), "value": float(item["value"])})
        )

    applied: list[dict] = []
    failed: dict | None = None
    not_applied: list[dict] = []

    for kind, args in pending:
        if failed is not None:
            not_applied.append({"kind": kind, **args})
            continue
        try:
            if kind == "configuration":
                active, created = ctx.backend.set_configuration(args["name"], False)
                applied.append(
                    {"kind": kind, "name": active, "created": created}
                )
            elif kind == "equation":
                ref = ctx.backend.set_equation(args["name"], args["expression"])
                applied.append(
                    {"kind": kind, "name": ref.name, "expression": ref.expression}
                )
            else:
                set_dimension(ctx, args["name"], args["value"], unit=unit)
                applied.append({"kind": kind, "name": args["name"], "value": args["value"]})
        except CadMcpError as exc:
            if not applied:
                raise
            failed = {
                "kind": kind,
                **args,
                "code": exc.code,
                "message": exc.message,
                "hint": exc.hint,
            }

    # Force one rebuild; attribute errors via kernel verify_delta / rebuild
    rebuild = ctx.backend.force_rebuild()
    return {
        "applied": applied,
        "failed": failed,
        "not_applied": not_applied,
        "rebuild_ok": rebuild.ok,
        "feature_errors": list(rebuild.feature_errors),
    }


def get_entities(
    ctx: OpContext,
    limit: int | None = None,
    offset: int | None = None,
) -> dict:
    """Face/edge inventory (dual-handle source): index + coords; pass back on ops.

    limit/offset only trim returned rows; indices stay global; faces and edges paginate separately.
    """
    u = ctx.units
    all_faces = [_public_face(f, u) for f in ctx.backend.list_faces()]
    all_edges = [
        {"index": e.index, "kind": e.kind, "midpoint": list(u.tuple_from_m(e.midpoint_m))}
        for e in ctx.backend.list_edges()
    ]
    faces, start = paginate(all_faces, limit, offset)
    edges, _ = paginate(all_edges, limit, offset)
    out: dict = {"faces": faces, "edges": edges, "length_unit": u.external_unit}
    if start is not None:
        out["total"] = {"faces": len(all_faces), "edges": len(all_edges)}
        out["offset"] = start
    return out


SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="get_mass_properties",
        description="Volume, area, mass and center of mass of the active document.",
        input_schema=make_schema({}),
        handler=get_mass_properties,
    ),
    ToolSpec(
        name="get_geometry",
        description="Geometry fingerprint: volume, area, face/edge counts, bounding box.",
        input_schema=make_schema({}),
        handler=get_geometry,
    ),
    ToolSpec(
        name="list_features",
        description="List features of the active document with names and kinds.",
        input_schema=make_schema({}),
        handler=list_features,
    ),
    ToolSpec(
        name="list_dimensions",
        description=(
            "List length/angle dimensions of the active part (parts only)."
        ),
        input_schema=make_schema({}),
        handler=list_dimensions,
        timeout_class="fast",
    ),
    ToolSpec(
        name="set_dimension",
        description=(
            "Set a dimension from list_dimensions; lengths use unit, angles are degrees."
        ),
        input_schema=make_schema(
            {
                "name": {"type": "string", "description": "e.g. D1@Boss-Extrude1."},
                "value": {"type": "number", "description": "Length or angle (deg)."},
                "unit": _UNIT_PROP,
            },
            ["name", "value"],
        ),
        handler=set_dimension,
        mutating=True,
        verify_delta=True,
    ),
    ToolSpec(
        name="list_equations",
        description="List part equations. Assembly/drawing are INVALID_ARGUMENT.",
        input_schema=make_schema({}),
        handler=list_equations,
        timeout_class="fast",
    ),
    ToolSpec(
        name="set_equation",
        description=(
            "Set a part equation: global D=80, or bind a dimension to D. No VBA."
        ),
        input_schema=make_schema(
            {
                "name": {"type": "string", "description": "Global or D1@Feature."},
                "expression": {"type": "string", "description": "e.g. 80, D, or D*2."},
            },
            ["name", "expression"],
        ),
        handler=set_equation,
        mutating=True,
        verify_delta=True,
    ),
    ToolSpec(
        name="part_parameters",
        description="Read dimensions, equations and configurations of the active part in one call.",
        input_schema=make_schema({}),
        handler=part_parameters,
        timeout_class="fast",
    ),
    ToolSpec(
        name="update_parameters",
        description=(
            "Batch-write dimensions/equations/configuration then rebuild. "
            "Applies in order and stops on first failure (no auto-rollback). "
            "Returns applied/failed/not_applied."
        ),
        input_schema=make_schema(
            {
                "dimensions": {
                    "type": "array",
                    "description": '[{"name":"D1@Boss-Extrude1","value":40}, ...]',
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "name": {"type": "string"},
                            "value": {"type": "number"},
                        },
                        "required": ["name", "value"],
                    },
                },
                "equations": {
                    "type": "array",
                    "description": '[{"name":"D","expression":"80"}, ...]',
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "name": {"type": "string"},
                            "expression": {"type": "string"},
                        },
                        "required": ["name", "expression"],
                    },
                },
                "configuration": {
                    "type": "string",
                    "description": "Activate this configuration before writes.",
                },
                "unit": _UNIT_PROP,
            }
        ),
        handler=update_parameters,
        mutating=True,
        verify_delta=True,
    ),
    ToolSpec(
        name="set_color",
        description=(
            "Set the active part appearance RGB (each 0–1); parts only."
        ),
        input_schema=make_schema(
            {
                "r": {"type": "number"},
                "g": {"type": "number"},
                "b": {"type": "number"},
            },
            ["r", "g", "b"],
        ),
        handler=set_color,
        mutating=True,
    ),
    ToolSpec(
        name="get_color",
        description="Read the active part appearance RGB (0–1). Unset returns color=null.",
        input_schema=make_schema({}),
        handler=get_color,
        timeout_class="fast",
    ),
    ToolSpec(
        name="get_entities",
        description=(
            "List faces and edges with index+coordinate handles; faces include unit normal. "
            "limit/offset paginate both lists; indexes stay global."
        ),
        input_schema=make_schema(
            {
                "limit": {"type": "integer", "minimum": 1},
                "offset": {"type": "integer", "minimum": 0},
            }
        ),
        handler=get_entities,
    ),
)
