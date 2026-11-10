"""features_adv · rib/draft/combine/split, hole wizard, cosmetic thread, feature mgmt.

Split from toolsets/features_adv.py by domain; handlers and ToolSpec unchanged.
"""

from __future__ import annotations

import math

from cadmcp.backend.protocol.constants import COMBINE_OPS, HOLE_WIZARD_ENDS
from cadmcp.errors import fail
from cadmcp.kernel import OpContext
from cadmcp.registry import ToolSpec, make_schema

from ._common import _UNIT_DESC, _UNIT_ENUM, _unit_ctx


def rib(
    ctx: OpContext, thickness: float, sketch: str | None = None, unit: str = "mm"
) -> dict:
    if thickness <= 0:
        raise fail("INVALID_ARGUMENT", "Rib thickness must be positive", "Pass thickness > 0")
    uc = _unit_ctx(ctx, unit)
    feat = ctx.backend.rib(uc.to_m(thickness), sketch)
    return {"name": feat.name, "kind": feat.kind, "unit": uc.external_unit}


def draft(
    ctx: OpContext,
    angle_deg: float,
    faces: list[int],
    neutral: int,
    flip: bool = False,
) -> dict:
    feat = ctx.backend.draft(math.radians(angle_deg), faces, neutral, flip)
    return {"name": feat.name, "kind": feat.kind, "angle_deg": angle_deg, "faces": list(faces), "neutral": neutral}


def combine(ctx: OpContext, op: str = "add", keep: int = 0) -> dict:
    feat = ctx.backend.combine(op, keep)
    return {"name": feat.name, "kind": feat.kind, "op": op}


def split_body(ctx: OpContext, plane: str) -> dict:
    feat = ctx.backend.split_body(plane)
    return {"name": feat.name, "kind": feat.kind, "plane": plane}


def parting_line(
    ctx: OpContext,
    pull_face: int,
    edges: list[int] | None = None,
    flip: bool = False,
) -> dict:
    feat = ctx.backend.parting_line(pull_face, edges, flip=flip)
    out: dict = {"name": feat.name, "kind": feat.kind, "pull_face": int(pull_face)}
    if edges is not None:
        out["edges"] = [int(x) for x in edges]
    if flip:
        out["flip"] = True
    return out


def parting_surface(
    ctx: OpContext,
    parting_line: str | None = None,
    radiate: bool = False,
    offset: float = 0.0,
    knit: bool = False,
    unit: str = "mm",
) -> dict:
    uc = _unit_ctx(ctx, unit)
    off_m = uc.to_m(offset) if radiate else 0.0
    feat = ctx.backend.parting_surface(
        parting_line, radiate=radiate, offset_m=off_m, knit=knit,
    )
    out: dict = {"name": feat.name, "kind": feat.kind, "unit": uc.external_unit}
    if parting_line is not None:
        out["parting_line"] = parting_line
    if radiate:
        out["radiate"] = True
        out["offset"] = offset
    if knit:
        out["knit"] = True
    return out


def shut_off_surface(ctx: OpContext, edges: list[int] | None = None) -> dict:
    feat = ctx.backend.shut_off_surface(edges)
    out: dict = {"name": feat.name, "kind": feat.kind}
    if edges is not None:
        out["edges"] = [int(x) for x in edges]
    return out


def hole_wizard(
    ctx: OpContext,
    face: int,
    diameter: float,
    end: str = "blind",
    depth: float | None = None,
    x: float | None = None,
    y: float | None = None,
    unit: str = "mm",
) -> dict:
    if diameter <= 0:
        raise fail("INVALID_ARGUMENT", "Hole diameter must be positive", "Pass diameter > 0")
    if end not in HOLE_WIZARD_ENDS:
        raise fail(
            "INVALID_ARGUMENT",
            f"Unknown hole end condition: {end!r}",
            f"end: {', '.join(HOLE_WIZARD_ENDS)}",
            requested=end,
        )
    uc = _unit_ctx(ctx, unit)
    feat = ctx.backend.hole_wizard(
        int(face),
        uc.to_m(diameter),
        end,
        None if depth is None else uc.to_m(depth),
        None if x is None else uc.to_m(x),
        None if y is None else uc.to_m(y),
    )
    out = {
        "name": feat.name,
        "kind": feat.kind,
        "face": int(face),
        "end": end,
        "unit": uc.external_unit,
    }
    if depth is not None:
        out["depth"] = depth
    return out


def insert_thread(
    ctx: OpContext,
    diameter: float,
    pitch: float,
    length: float | None = None,
    internal: bool = False,
    unit: str = "mm",
) -> dict:
    uc = _unit_ctx(ctx, unit)
    if diameter <= 0 or pitch <= 0:
        raise fail("INVALID_ARGUMENT", "Diameter and pitch must be positive", "Pass diameter > 0, pitch > 0")
    feat = ctx.backend.insert_thread(
        uc.to_m(diameter), uc.to_m(pitch), uc.to_m(length) if length is not None else None, internal
    )
    return {"name": feat.name, "kind": feat.kind, "unit": uc.external_unit}


def delete_feature(ctx: OpContext, name: str) -> dict:
    ctx.backend.delete_feature(name)
    return {"deleted": name}


def suppress_feature(ctx: OpContext, name: str, suppress: bool = True) -> dict:
    feat = ctx.backend.suppress_feature(name, suppress)
    return {"name": feat.name, "suppressed": suppress}


SPECS: list[ToolSpec] = [
    ToolSpec(
        name="rib",
        toolset="features_adv",
        description="Add a rib from an ended line sketch (thin boss; InsertRib is unused on 2025).",
        input_schema=make_schema(
            {
                "thickness": {"type": "number"},
                "sketch": {"type": "string"},
                "unit": {"type": "string", "enum": _UNIT_ENUM, "description": _UNIT_DESC},
            },
            ["thickness"],
        ),
        handler=rib,
        mutating=True,
        verify_delta=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="draft",
        toolset="features_adv",
        description="Neutral-plane draft. faces and neutral are get_faces indexes.",
        input_schema=make_schema(
            {
                "angle_deg": {"type": "number"},
                "faces": {"type": "array", "items": {"type": "integer"}},
                "neutral": {"type": "integer"},
                "flip": {"type": "boolean", "default": False},
            },
            ["angle_deg", "faces", "neutral"],
        ),
        handler=draft,
        mutating=True,
        verify_delta=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="combine",
        toolset="features_adv",
        description="Combine solid bodies: add, cut, or common. cut keeps body index keep.",
        input_schema=make_schema(
            {
                "op": {"type": "string", "enum": list(COMBINE_OPS), "default": "add"},
                "keep": {"type": "integer", "default": 0},
            },
        ),
        handler=combine,
        mutating=True,
        verify_delta=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="split_body",
        toolset="features_adv",
        description="Split solid with a reference plane into multiple bodies.",
        input_schema=make_schema(
            {"plane": {"type": "string", "description": "Cutting plane, e.g. Right Plane."}},
            ["plane"],
        ),
        handler=split_body,
        mutating=True,
        verify_delta=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="parting_line",
        toolset="features_adv",
        description=(
            "Mold parting line: pull_face (get_faces) mark=1 + edges (get_edges) mark=4. "
            "Omit edges to select all solid edges (works for a simple box)."
        ),
        input_schema=make_schema(
            {
                "pull_face": {"type": "integer", "description": "get_faces index for pull direction."},
                "edges": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "get_edges indexes; omit for all edges.",
                },
                "flip": {"type": "boolean", "default": False},
            },
            ["pull_face"],
        ),
        handler=parting_line,
        mutating=True,
        verify_delta=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="parting_surface",
        toolset="features_adv",
        description=(
            "Mold parting surface from an existing parting_line. "
            "Omit parting_line to use the latest. radiate needs offset ≥ 0."
        ),
        input_schema=make_schema(
            {
                "parting_line": {
                    "type": "string",
                    "description": "PartingLineN; omit for latest.",
                },
                "radiate": {"type": "boolean", "default": False},
                "offset": {"type": "number", "description": "Radiate distance when radiate=true."},
                "knit": {"type": "boolean", "default": False},
                "unit": {"type": "string", "enum": _UNIT_ENUM, "description": _UNIT_DESC},
            },
        ),
        handler=parting_surface,
        mutating=True,
        verify_delta=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="shut_off_surface",
        toolset="features_adv",
        description=(
            "Mold shut-off surface after parting_line. "
            "Omit edges to select all solid edges (works for a simple box)."
        ),
        input_schema=make_schema(
            {
                "edges": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "get_edges indexes; omit for all edges.",
                },
            },
        ),
        handler=shut_off_surface,
        mutating=True,
        verify_delta=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="hole_wizard",
        toolset="features_adv",
        description="ISO drill-size hole wizard on a planar face (get_faces index). end=blind needs depth; through_all does not. Omit x,y to place at face centroid.",
        input_schema=make_schema(
            {
                "face": {"type": "integer"},
                "diameter": {"type": "number", "description": "ISO drill size in unit (e.g. 6 → Ø6.0)."},
                "end": {"type": "string", "enum": list(HOLE_WIZARD_ENDS), "default": "blind"},
                "depth": {"type": "number"},
                "x": {"type": "number", "description": "Hole-sketch X; omit for face centroid."},
                "y": {"type": "number", "description": "Hole-sketch Y; omit for face centroid."},
                "unit": {"type": "string", "enum": _UNIT_ENUM, "description": _UNIT_DESC},
            },
            ["face", "diameter"],
        ),
        handler=hole_wizard,
        mutating=True,
        verify_delta=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="insert_thread",
        toolset="features_adv",
        description=(
            "Cut a metric-style thread (helix + triangular profile sweep-cut). "
            "external: existing cylinder of the given diameter. "
            "internal=true: existing tube whose hole diameter matches diameter. "
            "omit length for 4×pitch."
        ),
        input_schema=make_schema(
            {
                "diameter": {"type": "number", "description": "Nominal diameter > 0."},
                "pitch": {"type": "number", "description": "Pitch > 0."},
                "length": {"type": "number"},
                "internal": {"type": "boolean", "default": False},
                "unit": {"type": "string", "enum": _UNIT_ENUM, "description": _UNIT_DESC},
            },
            ["diameter", "pitch"],
        ),
        handler=insert_thread,
        mutating=True,
        verify_delta=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="delete_feature",
        toolset="features_adv",
        description="Delete a feature by name.",
        input_schema=make_schema({"name": {"type": "string"}}, ["name"]),
        handler=delete_feature,
        mutating=True,
        verify_delta=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="suppress_feature",
        toolset="features_adv",
        description="Suppress or unsuppress a feature by name.",
        input_schema=make_schema(
            {"name": {"type": "string"}, "suppress": {"type": "boolean", "default": True}},
            ["name"],
        ),
        handler=suppress_feature,
        mutating=True,
    ),
]
