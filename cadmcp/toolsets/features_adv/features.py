"""features_adv · rib/draft/combine/split, hole wizard, cosmetic/native thread, feature mgmt.

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


def tooling_split(
    ctx: OpContext,
    sketch: str | None = None,
    depth1: float = 100.0,
    depth2: float = 100.0,
    setback: bool = False,
    angle_deg: float = 3.0,
    core_sheet: str | None = None,
    cavity_sheet: str | None = None,
    parting_sheet: str | None = None,
    unit: str = "mm",
) -> dict:
    if depth1 <= 0 or depth2 <= 0:
        raise fail("INVALID_ARGUMENT", "Tooling-split depths must be positive", "Pass depth1/depth2 > 0")
    if angle_deg < 0:
        raise fail("INVALID_ARGUMENT", "Tooling-split angle cannot be negative", "Pass angle_deg ≥ 0")
    uc = _unit_ctx(ctx, unit)
    feat = ctx.backend.tooling_split(
        sketch,
        depth1_m=uc.to_m(depth1),
        depth2_m=uc.to_m(depth2),
        setback=bool(setback),
        angle_rad=math.radians(float(angle_deg)),
        core_sheet=core_sheet,
        cavity_sheet=cavity_sheet,
        parting_sheet=parting_sheet,
    )
    out: dict = {
        "name": feat.name,
        "kind": feat.kind,
        "depth1": depth1,
        "depth2": depth2,
        "setback": bool(setback),
        "angle_deg": float(angle_deg),
        "unit": uc.external_unit,
    }
    if sketch is not None:
        out["sketch"] = sketch
    if core_sheet is not None:
        out["core_sheet"] = core_sheet
    if cavity_sheet is not None:
        out["cavity_sheet"] = cavity_sheet
    if parting_sheet is not None:
        out["parting_sheet"] = parting_sheet
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


def insert_cosmetic_thread(
    ctx: OpContext,
    size: str,
    diameter: float,
    length: float | None = None,
    edge: int | None = None,
    internal: bool = False,
    spec: str | None = None,
    unit: str = "mm",
) -> dict:
    """Cosmetic (annotation) thread + THREAD_SPEC/SIDE/SIZE properties. Not cut geometry."""
    size_s = str(size).strip()
    if not size_s:
        raise fail("INVALID_ARGUMENT", "Thread size must be non-empty", "Pass size e.g. M10x1.5")
    if diameter <= 0:
        raise fail("INVALID_ARGUMENT", "Thread diameter must be positive", "Pass diameter > 0")
    if length is not None and length <= 0:
        raise fail("INVALID_ARGUMENT", "Thread length must be positive", "Pass length > 0")
    uc = _unit_ctx(ctx, unit)
    feat = ctx.backend.insert_cosmetic_thread(
        size_s,
        uc.to_m(diameter),
        None if length is None else uc.to_m(length),
        None if edge is None else int(edge),
        bool(internal),
        None if spec is None else str(spec).strip(),
    )
    side = "internal" if internal else "external"
    spec_s = str(spec).strip() if spec else size_s
    return {
        "name": feat.name,
        "kind": feat.kind,
        "size": size_s,
        "spec": spec_s,
        "side": side,
        "diameter": diameter,
        "unit": uc.external_unit,
        "edge": edge,
        "properties": {
            "THREAD_SPEC": spec_s,
            "THREAD_SIDE": side,
            "THREAD_SIZE": size_s,
        },
    }


def create_thread(
    ctx: OpContext,
    size: str,
    depth: float,
    edge: int | None = None,
    method: str = "cut",
    internal: bool = False,
    thread_type: str | None = None,
    right_handed: bool = True,
    diameter: float | None = None,
    pitch: float | None = None,
    unit: str = "mm",
) -> dict:
    """Native Thread Feature (cut/extrude geometry). Not cosmetic annotation."""
    size_s = str(size).strip()
    if not size_s:
        raise fail("INVALID_ARGUMENT", "Thread size must be non-empty", "Pass size e.g. M10x1.5")
    if depth <= 0:
        raise fail("INVALID_ARGUMENT", "Thread depth must be positive", "Pass depth > 0")
    if diameter is not None and diameter <= 0:
        raise fail("INVALID_ARGUMENT", "Thread diameter must be positive", "Pass diameter > 0")
    if pitch is not None and pitch <= 0:
        raise fail("INVALID_ARGUMENT", "Thread pitch must be positive", "Pass pitch > 0")
    uc = _unit_ctx(ctx, unit)
    feat = ctx.backend.create_thread(
        size_s,
        uc.to_m(depth),
        None if edge is None else int(edge),
        str(method),
        bool(internal),
        None if thread_type is None else str(thread_type).strip(),
        bool(right_handed),
        None if diameter is None else uc.to_m(diameter),
        None if pitch is None else uc.to_m(pitch),
    )
    method_s = str(method).strip().lower()
    side = "internal" if internal else "external"
    type_s = (
        str(thread_type).strip()
        if thread_type
        else ("Metric Tap" if internal else "Metric Die")
    )
    return {
        "name": feat.name,
        "kind": feat.kind,
        "size": size_s,
        "depth": depth,
        "method": method_s,
        "side": side,
        "thread_type": type_s,
        "right_handed": bool(right_handed),
        "edge": edge,
        "unit": uc.external_unit,
    }


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
            "Omit edges to use the pull-face boundary loop (not all solid edges; "
            "needed for radiate parting_surface)."
        ),
        input_schema=make_schema(
            {
                "pull_face": {"type": "integer", "description": "get_faces index for pull direction."},
                "edges": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "get_edges indexes; omit for pull-face boundary loop.",
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
            "Omit parting_line to use the latest. "
            "Live: prefer radiate=true with offset>0 after a closed-loop parting_line; "
            "succeeds only if MoldPartingGeom appears in the feature tree "
            "(COM-only ghost returns FEATURE_CREATE_FAILED)."
        ),
        input_schema=make_schema(
            {
                "parting_line": {
                    "type": "string",
                    "description": "PartingLineN; omit for latest.",
                },
                "radiate": {
                    "type": "boolean",
                    "default": False,
                    "description": "Live recommended true with offset>0.",
                },
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
        name="tooling_split",
        toolset="features_adv",
        description=(
            "Mold tooling split (GUI Tooling Split / 切削分割): core+cavity solids. "
            "Requires parting_line + parting_surface sheets and a mold-block sketch "
            "(omit sketch = latest). Live uses EXTSKETCHSEGMENT + SURFACEBODY marks 1/2/4."
        ),
        input_schema=make_schema(
            {
                "sketch": {
                    "type": "string",
                    "description": "Mold-block sketch name; omit for latest ended sketch.",
                },
                "depth1": {"type": "number", "default": 100.0, "description": "Block depth direction 1."},
                "depth2": {"type": "number", "default": 100.0, "description": "Block depth direction 2."},
                "setback": {"type": "boolean", "default": False},
                "angle_deg": {"type": "number", "default": 3.0, "description": "Draft angle (degrees)."},
                "core_sheet": {"type": "string", "description": "Core SURFACEBODY name; omit to auto-pick *[2]."},
                "cavity_sheet": {
                    "type": "string",
                    "description": "Cavity SURFACEBODY name; omit to auto-pick *[3].",
                },
                "parting_sheet": {
                    "type": "string",
                    "description": "Parting SURFACEBODY name; omit to auto-pick 分型面*.",
                },
                "unit": {"type": "string", "enum": _UNIT_ENUM, "description": _UNIT_DESC},
            },
        ),
        handler=tooling_split,
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
        name="insert_cosmetic_thread",
        toolset="features_adv",
        description=(
            "Insert a SolidWorks cosmetic thread (annotation only; no cut geometry) and write "
            "THREAD_SPEC / THREAD_SIDE / THREAD_SIZE custom properties for manufacturing callouts. "
            "external: Metric Die on a cylinder edge; internal=true: Metric Tap on a hole edge. "
            "size e.g. M10x1.5; omit length for 1.5×diameter; optional edge from get_edges; "
            "optional spec overrides THREAD_SPEC (e.g. M10x1.5-6H)."
        ),
        input_schema=make_schema(
            {
                "size": {"type": "string", "description": "Chart size, e.g. M10x1.5."},
                "diameter": {"type": "number", "description": "Major diameter > 0."},
                "length": {"type": "number", "description": "Blind thread depth; default 1.5×diameter."},
                "edge": {"type": "integer", "description": "get_edges index; omit to auto-pick."},
                "internal": {"type": "boolean", "default": False},
                "spec": {"type": "string", "description": "THREAD_SPEC override, e.g. M10x1.5-6H."},
                "unit": {"type": "string", "enum": _UNIT_ENUM, "description": _UNIT_DESC},
            },
            ["size", "diameter"],
        ),
        handler=insert_cosmetic_thread,
        mutating=True,
        verify_delta=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="create_thread",
        toolset="features_adv",
        description=(
            "Create a native SolidWorks Thread Feature that changes solid geometry "
            "(CreateDefinition(swFmSweepThread) → IThreadFeatureData → CreateFeature). "
            "method=cut removes material; method=extrude adds material. "
            "size e.g. M10x1.5; depth is blind length; optional edge from get_edges; "
            "internal=true uses Metric Tap (else Metric Die) unless thread_type overrides. "
            "Requires Thread Profiles (Tools→Options→File Locations). Not a cosmetic annotation."
        ),
        input_schema=make_schema(
            {
                "size": {"type": "string", "description": "Chart size, e.g. M10x1.5."},
                "depth": {"type": "number", "description": "Blind thread depth > 0."},
                "edge": {"type": "integer", "description": "get_edges index; omit to auto-pick."},
                "method": {
                    "type": "string",
                    "enum": ["cut", "extrude"],
                    "default": "cut",
                    "description": "cut removes material; extrude adds material.",
                },
                "internal": {"type": "boolean", "default": False},
                "thread_type": {
                    "type": "string",
                    "description": "Profile name or .SLDLFP path; default Metric Die/Tap.",
                },
                "right_handed": {"type": "boolean", "default": True},
                "diameter": {"type": "number", "description": "Optional major-diameter override."},
                "pitch": {"type": "number", "description": "Optional pitch override."},
                "unit": {"type": "string", "enum": _UNIT_ENUM, "description": _UNIT_DESC},
            },
            ["size", "depth"],
        ),
        handler=create_thread,
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
