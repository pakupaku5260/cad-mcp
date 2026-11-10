"""features_adv · surface extrude, knit, thicken, fill, boundary, trim, extend, fillet.

Split from toolsets/features_adv.py by domain; handlers and ToolSpec unchanged.
"""

from __future__ import annotations

from cadmcp.errors import fail
from cadmcp.kernel import OpContext
from cadmcp.registry import ToolSpec, make_schema

from ._common import _UNIT_DESC, _UNIT_ENUM, _unit_ctx


def extrude_surface(
    ctx: OpContext, depth: float, sketch: str | None = None, unit: str = "mm"
) -> dict:
    if depth <= 0:
        raise fail("INVALID_ARGUMENT", "Surface extrude depth must be positive", "Pass depth > 0")
    uc = _unit_ctx(ctx, unit)
    feat = ctx.backend.extrude_surface(uc.to_m(depth), sketch)
    return {"name": feat.name, "kind": feat.kind, "unit": uc.external_unit}


def knit(ctx: OpContext, surfaces: list[str] | None = None) -> dict:
    feat = ctx.backend.knit(surfaces)
    out = {"name": feat.name, "kind": feat.kind}
    if surfaces:
        out["surfaces"] = list(surfaces)
    return out


def thicken(
    ctx: OpContext, thickness: float, surface: str | None = None, unit: str = "mm"
) -> dict:
    if thickness <= 0:
        raise fail("INVALID_ARGUMENT", "Thicken thickness must be positive", "Pass thickness > 0")
    uc = _unit_ctx(ctx, unit)
    feat = ctx.backend.thicken(uc.to_m(thickness), surface)
    return {"name": feat.name, "kind": feat.kind, "unit": uc.external_unit}


def fill_surface(ctx: OpContext, surface: str | None = None, edge: int = 0) -> dict:
    feat = ctx.backend.fill_surface(surface, edge)
    out = {"name": feat.name, "kind": feat.kind, "edge": int(edge)}
    if surface:
        out["surface"] = surface
    return out


def boundary_surface(ctx: OpContext, profiles: list[str] | None = None) -> dict:
    feat = ctx.backend.boundary_surface(profiles)
    out = {"name": feat.name, "kind": feat.kind}
    if profiles:
        out["profiles"] = list(profiles)
    return out


def trim_surface(
    ctx: OpContext,
    tool: str | None = None,
    target: str | None = None,
    keep: int = 0,
) -> dict:
    feat = ctx.backend.trim_surface(tool, target, int(keep))
    out = {"name": feat.name, "kind": feat.kind, "keep": int(keep)}
    if tool:
        out["tool"] = tool
    if target:
        out["target"] = target
    return out


def extend_surface(
    ctx: OpContext,
    distance: float,
    surface: str | None = None,
    edge: int | None = None,
    linear: bool = True,
    unit: str = "mm",
) -> dict:
    if distance <= 0:
        raise fail("INVALID_ARGUMENT", "Extend distance must be positive", "Pass distance > 0")
    uc = _unit_ctx(ctx, unit)
    feat = ctx.backend.extend_surface(
        uc.to_m(distance), surface, None if edge is None else int(edge), bool(linear)
    )
    out = {
        "name": feat.name,
        "kind": feat.kind,
        "distance": distance,
        "linear": bool(linear),
        "unit": uc.external_unit,
    }
    if surface:
        out["surface"] = surface
    if edge is not None:
        out["edge"] = int(edge)
    return out


def fillet_surface(
    ctx: OpContext,
    radius: float,
    surface: str | None = None,
    edge: int = 0,
    unit: str = "mm",
) -> dict:
    if radius <= 0:
        raise fail("INVALID_ARGUMENT", "Fillet radius must be positive", "Pass radius > 0")
    uc = _unit_ctx(ctx, unit)
    feat = ctx.backend.fillet_surface(uc.to_m(radius), surface, int(edge))
    out = {
        "name": feat.name,
        "kind": feat.kind,
        "radius": radius,
        "edge": int(edge),
        "unit": uc.external_unit,
    }
    if surface:
        out["surface"] = surface
    return out


def untrim_surface(ctx: OpContext, surface: str | None = None) -> dict:
    feat = ctx.backend.untrim_surface(surface)
    out: dict = {"name": feat.name, "kind": feat.kind}
    if surface:
        out["surface"] = surface
    return out


SPECS: list[ToolSpec] = [
    ToolSpec(
        name="extrude_surface",
        toolset="features_adv",
        description="Extrude the last ended sketch as a surface (not a solid). Then knit or thicken.",
        input_schema=make_schema(
            {
                "depth": {"type": "number", "description": "Extrude depth > 0."},
                "sketch": {"type": "string", "description": "Ended sketch name; omit for last."},
                "unit": {"type": "string", "enum": _UNIT_ENUM, "description": _UNIT_DESC},
            },
            ["depth"],
        ),
        handler=extrude_surface,
        mutating=True,
        verify_delta=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="knit",
        toolset="features_adv",
        description="Knit two or more sheet bodies. Omit surfaces to use the last two.",
        input_schema=make_schema(
            {
                "surfaces": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Surface feature/body names; omit for the last two sheets.",
                },
            }
        ),
        handler=knit,
        mutating=True,
        verify_delta=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="thicken",
        toolset="features_adv",
        description="Thicken a closed surface extrude into a solid. Open knit sheets fail.",
        input_schema=make_schema(
            {
                "thickness": {"type": "number", "description": "Thickness > 0."},
                "surface": {"type": "string", "description": "Surface feature name; omit for last."},
                "unit": {"type": "string", "enum": _UNIT_ENUM, "description": _UNIT_DESC},
            },
            ["thickness"],
        ),
        handler=thicken,
        mutating=True,
        verify_delta=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="fill_surface",
        toolset="features_adv",
        description="Cap a sheet-body edge (last extrude_surface by default) with a filled surface.",
        input_schema=make_schema(
            {
                "surface": {"type": "string", "description": "Surface feature name; omit for last sheet."},
                "edge": {"type": "integer", "description": "Sheet-body edge index; default 0.", "default": 0},
            }
        ),
        handler=fill_surface,
        mutating=True,
        verify_delta=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="boundary_surface",
        toolset="features_adv",
        description="Boundary surface from two ended sketches (omit profiles = last two), like a surface loft.",
        input_schema=make_schema(
            {
                "profiles": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Two ended sketch names; omit for the last two.",
                },
            }
        ),
        handler=boundary_surface,
        mutating=True,
        verify_delta=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="trim_surface",
        toolset="features_adv",
        description=(
            "Trim one sheet body with another. Omit tool/target to use the last two "
            "surface features (last=tool). keep indexes the piece to keep after the split."
        ),
        input_schema=make_schema(
            {
                "tool": {"type": "string", "description": "Trim-tool surface name; omit for last."},
                "target": {
                    "type": "string",
                    "description": "Surface to trim; omit for the previous surface feature.",
                },
                "keep": {
                    "type": "integer",
                    "description": "Index of the piece to keep (default 0).",
                    "default": 0,
                },
            }
        ),
        handler=trim_surface,
        mutating=True,
        verify_delta=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="extend_surface",
        toolset="features_adv",
        description=(
            "Extend a sheet body by distance. Omit surface for the last sheet; "
            "omit edge to extend via the first face, or pass a sheet-body edge index."
        ),
        input_schema=make_schema(
            {
                "distance": {"type": "number", "description": "Extend distance > 0."},
                "surface": {
                    "type": "string",
                    "description": "Surface feature name; omit for last sheet.",
                },
                "edge": {
                    "type": "integer",
                    "description": "Sheet-body edge index; omit to select the first face.",
                },
                "linear": {
                    "type": "boolean",
                    "description": "True=linear extend; False=same surface (default true).",
                    "default": True,
                },
                "unit": {"type": "string", "enum": _UNIT_ENUM, "description": _UNIT_DESC},
            },
            ["distance"],
        ),
        handler=extend_surface,
        mutating=True,
        verify_delta=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="fillet_surface",
        toolset="features_adv",
        description=(
            "Fillet a sheet-body edge (FeatureFillet3 on a surface edge). "
            "Omit surface for the last sheet; edge indexes that sheet body's edges."
        ),
        input_schema=make_schema(
            {
                "radius": {"type": "number", "description": "Fillet radius > 0."},
                "surface": {
                    "type": "string",
                    "description": "Surface feature name; omit for last sheet.",
                },
                "edge": {
                    "type": "integer",
                    "description": "Sheet-body edge index; default 0.",
                    "default": 0,
                },
                "unit": {"type": "string", "enum": _UNIT_ENUM, "description": _UNIT_DESC},
            },
            ["radius"],
        ),
        handler=fillet_surface,
        mutating=True,
        verify_delta=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="untrim_surface",
        toolset="features_adv",
        description=(
            "Untrim a sheet body (InsertUntrimSurface: all edges, connect endpoints). "
            "Omit surface for the last sheet; typically used after trim_surface."
        ),
        input_schema=make_schema(
            {
                "surface": {
                    "type": "string",
                    "description": "Surface feature name; omit for last sheet.",
                },
            }
        ),
        handler=untrim_surface,
        mutating=True,
        verify_delta=True,
        timeout_class="slow",
    ),
]
