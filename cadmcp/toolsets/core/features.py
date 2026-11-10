"""Core toolset · base features: extrude/cut/revolve/fillet/chamfer/shell/pattern/mirror.

Split from toolsets/core.py by domain; handlers and ToolSpec unchanged.
"""

from __future__ import annotations

import math

from cadmcp.backend.protocol.constants import (
    EXTRUDE_DEPTHLESS,
    EXTRUDE_DIRECTIONS,
    MIRROR_SCOPES,
    REVOLVE_AXES,
    THIN_TYPES,
)
from cadmcp.backend.protocol.validators import validate_extrude_options, validate_thin_options
from cadmcp.errors import fail
from cadmcp.kernel import OpContext
from cadmcp.registry import ToolSpec, make_schema

from ._common import _UNIT_PROP, _unit_ctx


def _extrude_payload(
    feat, depth: float | None, unit: str, direction: str, depth2: float | None, reverse: bool | None,
    *, thin: bool = False, thickness: float | None = None, thin_type: str = "one",
) -> dict:
    out = {"name": feat.name, "kind": feat.kind, "unit": unit}
    if depth is not None:
        out["depth"] = depth
    if direction != "blind":
        out["direction"] = direction
    if depth2 is not None:
        out["depth2"] = depth2
    if reverse:
        out["reverse"] = True
    if thin:
        out["thin"] = True
        out["thickness"] = thickness
        if thin_type != "one":
            out["thin_type"] = thin_type
    return out


def _extrude_depth_m(direction: str, depth: float | None, uc) -> float:
    if direction not in EXTRUDE_DEPTHLESS:
        if depth is None or depth <= 0:
            raise fail(
                "INVALID_ARGUMENT",
                "Extrude/cut depth must be positive",
                "Pass depth > 0, or use through_all / up_to_next / up_to_surface / up_to_vertex / up_to_body",
            )
        return uc.to_m(depth)
    if depth is None:
        return 0.0
    if depth <= 0:
        raise fail("INVALID_ARGUMENT", "If depth is provided it must be positive", "Omit depth or pass depth > 0")
    return uc.to_m(depth)


def extrude(
    ctx: OpContext,
    depth: float | None = None,
    unit: str = "mm",
    sketch: str | None = None,
    direction: str = "blind",
    depth2: float | None = None,
    reverse: bool = False,
    end_face: int | None = None,
    end_vertex: int | None = None,
    end_body: int | None = None,
    merge: bool = True,
    thin: bool = False,
    thickness: float | None = None,
    thin_type: str = "one",
) -> dict:
    uc = _unit_ctx(ctx, unit)
    d2 = None if depth2 is None else uc.to_m(depth2)
    thk = None if thickness is None else uc.to_m(thickness)
    validate_extrude_options(direction, d2, end_face, end_vertex, end_body)
    validate_thin_options(thin, thk, thin_type, direction)
    feat = ctx.backend.extrude_blind(
        _extrude_depth_m(direction, depth, uc),
        sketch=sketch, direction=direction, depth2_m=d2, reverse=reverse,
        end_face=end_face, end_vertex=end_vertex, end_body=end_body,
        merge=merge, thin=thin, thickness_m=thk, thin_type=thin_type,
    )
    out = _extrude_payload(
        feat, depth, uc.external_unit, direction, depth2, reverse,
        thin=thin, thickness=thickness, thin_type=thin_type,
    )
    if not merge:
        out["merge"] = False
    if end_vertex is not None:
        out["end_vertex"] = int(end_vertex)
    if end_body is not None:
        out["end_body"] = int(end_body)
    return out


def extrude_cut(
    ctx: OpContext,
    depth: float | None = None,
    unit: str = "mm",
    sketch: str | None = None,
    direction: str = "blind",
    depth2: float | None = None,
    reverse: bool | None = None,
    end_face: int | None = None,
    end_vertex: int | None = None,
    end_body: int | None = None,
    thin: bool = False,
    thickness: float | None = None,
    thin_type: str = "one",
) -> dict:
    uc = _unit_ctx(ctx, unit)
    d2 = None if depth2 is None else uc.to_m(depth2)
    thk = None if thickness is None else uc.to_m(thickness)
    validate_extrude_options(direction, d2, end_face, end_vertex, end_body)
    validate_thin_options(thin, thk, thin_type, direction)
    feat = ctx.backend.extrude_cut(
        _extrude_depth_m(direction, depth, uc),
        sketch=sketch, direction=direction, depth2_m=d2, reverse=reverse,
        end_face=end_face, end_vertex=end_vertex, end_body=end_body,
        thin=thin, thickness_m=thk, thin_type=thin_type,
    )
    out = _extrude_payload(
        feat, depth, uc.external_unit, direction, depth2, reverse,
        thin=thin, thickness=thickness, thin_type=thin_type,
    )
    if end_vertex is not None:
        out["end_vertex"] = int(end_vertex)
    if end_body is not None:
        out["end_body"] = int(end_body)
    return out


def revolve(
    ctx: OpContext,
    axis: str = "+z",
    angle_deg: float = 360.0,
    sketch: str | None = None,
    edge: int | None = None,
) -> dict:
    feat = ctx.backend.revolve_blind(
        math.radians(angle_deg), axis, sketch=sketch, edge_index=edge
    )
    out = {"name": feat.name, "kind": feat.kind, "axis": axis, "angle_deg": angle_deg}
    if edge is not None:
        out["edge"] = edge
    return out


def fillet(
    ctx: OpContext,
    radius: float,
    unit: str = "mm",
    target: str | None = None,
    edges: list[int] | None = None,
) -> dict:
    uc = _unit_ctx(ctx, unit)
    feat = ctx.backend.fillet_blind(uc.to_m(radius), target=target, edge_indexes=edges)
    return {"name": feat.name, "kind": feat.kind, "radius": radius, "unit": uc.external_unit}


def chamfer(
    ctx: OpContext,
    distance: float,
    unit: str = "mm",
    target: str | None = None,
    edges: list[int] | None = None,
    angle_deg: float = 45.0,
) -> dict:
    if angle_deg <= 0 or angle_deg >= 90:
        raise fail("INVALID_ARGUMENT", "Chamfer angle must be in (0, 90) degrees", "Pass angle_deg, e.g. 30 or 45")
    uc = _unit_ctx(ctx, unit)
    feat = ctx.backend.chamfer_blind(
        uc.to_m(distance), target=target, edge_indexes=edges, angle_rad=math.radians(angle_deg)
    )
    return {
        "name": feat.name,
        "kind": feat.kind,
        "distance": distance,
        "angle_deg": angle_deg,
        "unit": uc.external_unit,
    }


def shell(
    ctx: OpContext,
    thickness: float,
    unit: str = "mm",
    faces: list[int] | None = None,
) -> dict:
    uc = _unit_ctx(ctx, unit)
    feat = ctx.backend.shell_blind(uc.to_m(thickness), face_indexes=faces)
    return {"name": feat.name, "kind": feat.kind, "thickness": thickness, "unit": uc.external_unit}


def linear_pattern(
    ctx: OpContext,
    feature: str,
    count: int,
    dx: float = 0.0,
    dy: float = 0.0,
    dz: float = 0.0,
    unit: str = "mm",
) -> dict:
    uc = _unit_ctx(ctx, unit)
    feat = ctx.backend.linear_pattern_blind(
        feature, uc.to_m(dx), uc.to_m(dy), uc.to_m(dz), count
    )
    return {"name": feat.name, "kind": feat.kind, "feature": feature, "count": count}


def circular_pattern(
    ctx: OpContext,
    feature: str,
    count: int,
    axis: str = "+z",
    edge: int | None = None,
) -> dict:
    feat = ctx.backend.circular_pattern_blind(feature, count, axis, edge_index=edge)
    return {
        "name": feat.name,
        "kind": feat.kind,
        "feature": feature,
        "count": count,
        "axis": axis,
    }


def mirror(
    ctx: OpContext, feature: str, plane: str, scope: str = "body"
) -> dict:
    if scope not in MIRROR_SCOPES:
        raise fail(
            "INVALID_ARGUMENT",
            f"Unknown mirror scope: {scope!r}",
            f"scope: {', '.join(MIRROR_SCOPES)}",
            requested=scope,
        )
    feat = ctx.backend.mirror_feature(feature, plane, scope)
    return {"name": feat.name, "kind": feat.kind, "feature": feature, "plane": plane, "scope": scope}


SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="extrude",
        description="Extrude last sketch; omit depth if depthless; thin needs thickness.",
        input_schema=make_schema(
            {
                "depth": {"type": "number", "exclusiveMinimum": 0},
                "unit": _UNIT_PROP,
                "sketch": {"type": "string"},
                "direction": {"type": "string", "enum": list(EXTRUDE_DIRECTIONS)},
                "depth2": {"type": "number", "exclusiveMinimum": 0},
                "reverse": {"type": "boolean"},
                "end_face": {"type": "integer"},
                "end_vertex": {
                    "type": "integer",
                    "description": "get_vertices index; required for up_to_vertex.",
                },
                "end_body": {
                    "type": "integer",
                    "description": "body index for up_to_body (face-equivalent create path).",
                },
                "merge": {"type": "boolean", "default": True},
                "thin": {"type": "boolean"},
                "thickness": {"type": "number", "exclusiveMinimum": 0},
                "thin_type": {"type": "string", "enum": list(THIN_TYPES)},
            },
        ),
        handler=extrude,
        mutating=True,
        verify_delta=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="extrude_cut",
        description="Cut with last sketch; same options as extrude.",
        input_schema=make_schema(
            {
                "depth": {"type": "number", "exclusiveMinimum": 0},
                "unit": _UNIT_PROP,
                "sketch": {"type": "string"},
                "direction": {"type": "string", "enum": list(EXTRUDE_DIRECTIONS)},
                "depth2": {"type": "number", "exclusiveMinimum": 0},
                "reverse": {"type": "boolean"},
                "end_face": {"type": "integer"},
                "end_vertex": {
                    "type": "integer",
                    "description": "get_vertices index; required for up_to_vertex.",
                },
                "end_body": {
                    "type": "integer",
                    "description": "body index for up_to_body (face-equivalent create path).",
                },
                "thin": {"type": "boolean"},
                "thickness": {"type": "number", "exclusiveMinimum": 0},
                "thin_type": {"type": "string", "enum": list(THIN_TYPES)},
            },
        ),
        handler=extrude_cut,
        mutating=True,
        verify_delta=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="revolve",
        description="Revolve the last sketch about a model axis or a line edge.",
        input_schema=make_schema(
            {
                "axis": {"type": "string", "enum": list(REVOLVE_AXES)},
                "angle_deg": {"type": "number", "exclusiveMinimum": 0, "maximum": 360,
                              "description": "Default: full 360."},
                "sketch": {"type": "string", "description": "Default: last finished sketch."},
                "edge": {"type": "integer", "description": "On sketch plane; overrides axis."},
            },
        ),
        handler=revolve,
        mutating=True,
        verify_delta=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="fillet",
        description=(
            "Round edges; omit edges for the whole part or one target feature."
        ),
        input_schema=make_schema(
            {
                "radius": {"type": "number", "exclusiveMinimum": 0},
                "unit": _UNIT_PROP,
                "target": {"type": "string"},
                "edges": {"type": "array", "items": {"type": "integer"}},
            },
            ["radius"],
        ),
        handler=fillet,
        mutating=True,
        verify_delta=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="chamfer",
        description=(
            "Chamfer edges: distance plus angle (default 45°)."
        ),
        input_schema=make_schema(
            {
                "distance": {"type": "number", "exclusiveMinimum": 0},
                "unit": _UNIT_PROP,
                "target": {"type": "string"},
                "edges": {"type": "array", "items": {"type": "integer"}},
                "angle_deg": {"type": "number", "default": 45.0, "description": "Default 45."},
            },
            ["distance"],
        ),
        handler=chamfer,
        mutating=True,
        verify_delta=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="shell",
        description=(
            "Shell with wall thickness; faces=[get_faces] opens those faces."
        ),
        input_schema=make_schema(
            {
                "thickness": {"type": "number", "exclusiveMinimum": 0},
                "unit": _UNIT_PROP,
                "faces": {"type": "array", "items": {"type": "integer"},
                          "description": "Omit for closed shell."},
            },
            ["thickness"],
        ),
        handler=shell,
        mutating=True,
        verify_delta=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="linear_pattern",
        description="Rectangular pattern along dx/dy/dz; count includes the original.",
        input_schema=make_schema(
            {
                "feature": {"type": "string"},
                "count": {"type": "integer", "minimum": 2, "description": "Includes original."},
                "dx": {"type": "number"},
                "dy": {"type": "number"},
                "dz": {"type": "number"},
                "unit": _UNIT_PROP,
            },
            ["feature", "count"],
        ),
        handler=linear_pattern,
        mutating=True,
        verify_delta=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="circular_pattern",
        description="Circular pattern about an axis or line edge; count includes the original.",
        input_schema=make_schema(
            {
                "feature": {"type": "string"},
                "count": {"type": "integer", "minimum": 2, "description": "Includes original."},
                "axis": {"type": "string", "enum": list(REVOLVE_AXES)},
                "edge": {"type": "integer", "description": "Overrides axis."},
            },
            ["feature", "count"],
        ),
        handler=circular_pattern,
        mutating=True,
        verify_delta=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="mirror",
        description="Mirror about a list_planes name. Default scope=body.",
        input_schema=make_schema(
            {
                "feature": {"type": "string"},
                "plane": {"type": "string"},
                "scope": {
                    "type": "string",
                    "enum": list(MIRROR_SCOPES),
                    "description": "body (default) or feature.",
                },
            },
            ["feature", "plane"],
        ),
        handler=mirror,
        mutating=True,
        verify_delta=True,
        timeout_class="slow",
    ),
)
