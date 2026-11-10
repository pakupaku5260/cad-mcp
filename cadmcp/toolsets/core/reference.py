"""Core toolset · reference planes and axes.

Split from toolsets/core.py by domain; handlers and ToolSpec unchanged.
"""

from __future__ import annotations

import math

from cadmcp.backend.protocol.constants import PLANE_MODES
from cadmcp.backend.protocol.validators import validate_create_plane
from cadmcp.errors import fail
from cadmcp.kernel import OpContext
from cadmcp.registry import ToolSpec, make_schema

from ._common import _UNIT_PROP, _unit_ctx


def list_planes(ctx: OpContext) -> dict:
    return {"planes": ctx.backend.list_planes()}


def create_plane(
    ctx: OpContext,
    reference: str | None = None,
    offset: float | None = None,
    flip: bool = False,
    unit: str = "mm",
    mode: str = "offset",
    angle_deg: float | None = None,
    axis: str | None = None,
    points: list[list[float]] | None = None,
) -> dict:
    uc = _unit_ctx(ctx, unit)
    pts = None
    if points is not None:
        if not isinstance(points, list) or len(points) != 3:
            raise fail("INVALID_ARGUMENT", "Three-point plane needs exactly three points", "Pass points as three [x,y,z]")
        parsed: list[tuple[float, float, float]] = []
        for i, raw in enumerate(points):
            if not isinstance(raw, (list, tuple)) or len(raw) != 3:
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Point {i + 1} must be [x,y,z]",
                    "Each point needs three numbers",
                )
            parsed.append((uc.to_m(raw[0]), uc.to_m(raw[1]), uc.to_m(raw[2])))
        pts = parsed
    angle_rad = None if angle_deg is None else math.radians(float(angle_deg))
    validate_create_plane(mode, reference, offset is not None, angle_rad, axis, pts)
    feat = ctx.backend.create_plane(
        reference,
        uc.to_m(offset or 0.0),
        flip,
        mode=mode,
        angle_rad=angle_rad,
        axis=axis,
        points_m=pts,
    )
    out: dict = {"name": feat.name, "kind": feat.kind, "unit": uc.external_unit}
    if mode == "offset":
        out["reference"] = reference
        out["offset"] = offset
    else:
        out["mode"] = mode
        if reference:
            out["reference"] = reference
        if axis:
            out["axis"] = axis
        if angle_deg is not None:
            out["angle_deg"] = angle_deg
    if flip:
        out["flip"] = True
    return out


def create_axis(
    ctx: OpContext, planes: list[str] | None = None, edge: int | None = None
) -> dict:
    has_planes = planes is not None
    has_edge = edge is not None
    if has_planes == has_edge:
        raise fail(
            "INVALID_ARGUMENT",
            "create_axis needs planes=[p1,p2] or an edge index, not both",
            "For plane intersection pass planes; or a straight edge index from get_edges",
        )
    pair: tuple[str, str] | None = None
    if has_planes:
        if not isinstance(planes, list) or len(planes) != 2:
            raise fail(
                "INVALID_ARGUMENT",
                "planes must be two reference plane names",
                'e.g. planes=["Front Plane","Right Plane"]',
            )
        pair = (str(planes[0]), str(planes[1]))
    feat = ctx.backend.create_axis(planes=pair, edge=edge)
    out = {"name": feat.name, "kind": feat.kind}
    if pair is not None:
        out["planes"] = list(pair)
    if edge is not None:
        out["edge"] = edge
    return out


SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="list_planes",
        description="List default and create_plane reference planes.",
        input_schema=make_schema({}),
        handler=list_planes,
    ),
    ToolSpec(
        name="create_plane",
        description="Offset, angle, or 3-point plane. Sketch on returned PlaneN.",
        input_schema=make_schema(
            {
                "reference": {"type": "string"},
                "offset": {"type": "number"},
                "flip": {"type": "boolean"},
                "unit": _UNIT_PROP,
                "mode": {"type": "string", "enum": list(PLANE_MODES)},
                "angle_deg": {"type": "number"},
                "axis": {"type": "string"},
                "points": {
                    "type": "array",
                    "minItems": 3,
                    "maxItems": 3,
                    "items": {
                        "type": "array",
                        "minItems": 3,
                        "maxItems": 3,
                        "items": {"type": "number"},
                    },
                },
            },
        ),
        handler=create_plane,
        mutating=True,
    ),
    ToolSpec(
        name="create_axis",
        description="Axis from two planes or a get_edges line index (not both).",
        input_schema=make_schema(
            {
                "planes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 2,
                    "maxItems": 2,
                },
                "edge": {"type": "integer"},
            },
        ),
        handler=create_axis,
        mutating=True,
    ),
)
