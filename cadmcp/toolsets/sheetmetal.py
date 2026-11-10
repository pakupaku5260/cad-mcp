"""Sheet metal toolset: base flange, edge flange, unfold length; SM2 miter/hem/unfold DXF/bend table.

Same unit rules as core: lengths via UnitContext to meters; backend uses SI.
"""
from __future__ import annotations

import math

from cadmcp.errors import fail
from cadmcp.kernel import OpContext
from cadmcp.registry import ToolSpec, make_schema
from cadmcp.safety import ensure_output_path
from cadmcp.units import SUPPORTED_UNITS, UnitContext

_UNIT_DESC = "Unit; default mm."
_UNIT_ENUM = sorted(SUPPORTED_UNITS)
_DXF_EXTS = {".dxf"}


def _unit_ctx(ctx: OpContext, unit: str) -> UnitContext:
    return ctx.units if unit == ctx.units.external_unit else UnitContext(unit)


def base_flange(
    ctx: OpContext,
    thickness: float,
    radius: float | None = None,
    sketch: str | None = None,
    unit: str = "mm",
) -> dict:
    if thickness <= 0:
        raise fail("INVALID_ARGUMENT", "Sheet metal thickness must be positive", "Pass thickness > 0")
    uc = _unit_ctx(ctx, unit)
    feat = ctx.backend.base_flange(
        uc.to_m(thickness),
        None if radius is None else uc.to_m(radius),
        sketch,
    )
    return {"name": feat.name, "kind": feat.kind, "unit": uc.external_unit}


def edge_flange(
    ctx: OpContext,
    edge: int,
    length: float,
    angle_deg: float = 90.0,
    radius: float | None = None,
    unit: str = "mm",
) -> dict:
    if length <= 0:
        raise fail("INVALID_ARGUMENT", "Edge flange length must be positive", "Pass length > 0")
    uc = _unit_ctx(ctx, unit)
    feat = ctx.backend.edge_flange(
        int(edge),
        uc.to_m(length),
        math.radians(angle_deg),
        None if radius is None else uc.to_m(radius),
    )
    return {
        "name": feat.name,
        "kind": feat.kind,
        "edge": int(edge),
        "angle_deg": angle_deg,
        "unit": uc.external_unit,
    }


def sheet_metal_unfold(ctx: OpContext, unit: str = "mm") -> dict:
    uc = _unit_ctx(ctx, unit)
    flat = ctx.backend.sheet_metal_unfold()
    return {
        "length": uc.from_m(flat.length_m),
        "width": uc.from_m(flat.width_m),
        "thickness": uc.from_m(flat.thickness_m),
        "k_factor": flat.k_factor,
        "unit": uc.external_unit,
    }


def miter_flange(
    ctx: OpContext,
    edges: list,
    length: float,
    angle_deg: float = 90.0,
    radius: float | None = None,
    unit: str = "mm",
) -> dict:
    if length <= 0:
        raise fail("INVALID_ARGUMENT", "Miter flange length must be positive", "Pass length > 0")
    if not edges:
        raise fail("INVALID_ARGUMENT", "Miter flange needs at least one edge", "Pass edges=[get_edges indices]")
    uc = _unit_ctx(ctx, unit)
    feat = ctx.backend.miter_flange(
        [int(e) for e in edges],
        uc.to_m(length),
        math.radians(angle_deg),
        None if radius is None else uc.to_m(radius),
    )
    return {
        "name": feat.name,
        "kind": feat.kind,
        "edges": [int(e) for e in edges],
        "angle_deg": angle_deg,
        "unit": uc.external_unit,
    }


def hem_flange(
    ctx: OpContext,
    edge: int,
    length: float,
    radius: float | None = None,
    unit: str = "mm",
) -> dict:
    if length <= 0:
        raise fail("INVALID_ARGUMENT", "Hem length must be positive", "Pass length > 0")
    uc = _unit_ctx(ctx, unit)
    feat = ctx.backend.hem_flange(
        int(edge),
        uc.to_m(length),
        None if radius is None else uc.to_m(radius),
    )
    return {
        "name": feat.name,
        "kind": feat.kind,
        "edge": int(edge),
        "unit": uc.external_unit,
    }


def export_flat_dxf(ctx: OpContext, path: str, overwrite: bool = False) -> dict:
    resolved = ensure_output_path(
        path, roots=ctx.workspace, extensions=_DXF_EXTS, overwrite=overwrite
    )
    ctx.backend.export_flat_dxf(resolved)
    return {"saved": True, "path": str(resolved)}


def sheet_metal_bend_table(ctx: OpContext, unit: str = "mm") -> dict:
    uc = _unit_ctx(ctx, unit)
    rows = []
    for row in ctx.backend.sheet_metal_bend_table():
        item = {
            "index": row.get("index"),
            "angle_deg": row.get("angle_deg"),
            "k_factor": row.get("k_factor"),
        }
        if row.get("radius_m") is not None:
            item["radius"] = uc.from_m(float(row["radius_m"]))
            item["unit"] = uc.external_unit
        rows.append(item)
    return {"count": len(rows), "bends": rows}


SHEETMETAL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="base_flange",
        toolset="sheetmetal",
        description="Sheet-metal base flange from the last closed sketch. thickness > 0; omit radius for 0.5×thickness.",
        input_schema=make_schema(
            {
                "thickness": {"type": "number"},
                "radius": {"type": "number"},
                "sketch": {"type": "string"},
                "unit": {"type": "string", "enum": _UNIT_ENUM, "description": _UNIT_DESC},
            },
            ["thickness"],
        ),
        handler=base_flange,
        mutating=True,
        verify_delta=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="edge_flange",
        toolset="sheetmetal",
        description="Edge flange on a sheet-metal outline edge (get_edges index). length > 0; angle_deg default 90.",
        input_schema=make_schema(
            {
                "edge": {"type": "integer"},
                "length": {"type": "number"},
                "angle_deg": {"type": "number", "default": 90},
                "radius": {"type": "number"},
                "unit": {"type": "string", "enum": _UNIT_ENUM, "description": _UNIT_DESC},
            },
            ["edge", "length"],
        ),
        handler=edge_flange,
        mutating=True,
        verify_delta=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="sheet_metal_unfold",
        toolset="sheetmetal",
        description="Unsuppress the flat pattern and return unfold length/width, thickness and K-factor.",
        input_schema=make_schema(
            {
                "unit": {"type": "string", "enum": _UNIT_ENUM, "description": _UNIT_DESC},
            },
        ),
        handler=sheet_metal_unfold,
        mutating=True,
        verify_delta=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="miter_flange",
        toolset="sheetmetal",
        description=(
            "Miter flange on sheet-metal edges (get_edges indexes). Requires base_flange. "
            "angle_deg: 0=in-plane outward, 90=face normal (default)."
        ),
        input_schema=make_schema(
            {
                "edges": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "get_edges indexes.",
                },
                "length": {"type": "number"},
                "angle_deg": {"type": "number", "default": 90},
                "radius": {"type": "number"},
                "unit": {"type": "string", "enum": _UNIT_ENUM, "description": _UNIT_DESC},
            },
            ["edges", "length"],
        ),
        handler=miter_flange,
        mutating=True,
        verify_delta=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="hem_flange",
        toolset="sheetmetal",
        description="Hem on a sheet-metal outline edge (get_edges index).",
        input_schema=make_schema(
            {
                "edge": {"type": "integer"},
                "length": {"type": "number"},
                "radius": {"type": "number"},
                "unit": {"type": "string", "enum": _UNIT_ENUM, "description": _UNIT_DESC},
            },
            ["edge", "length"],
        ),
        handler=hem_flange,
        mutating=True,
        verify_delta=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="export_flat_dxf",
        toolset="sheetmetal",
        description="Export the sheet-metal flat pattern to DXF (ExportToDWG2).",
        input_schema=make_schema(
            {
                "path": {"type": "string", "description": "Output .dxf path."},
                "overwrite": {"type": "boolean", "default": False},
            },
            ["path"],
        ),
        handler=export_flat_dxf,
        mutating=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="sheet_metal_bend_table",
        toolset="sheetmetal",
        description="Read bend-table rows (angle/radius/K-factor) from the active sheet-metal part.",
        input_schema=make_schema(
            {"unit": {"type": "string", "enum": _UNIT_ENUM, "description": _UNIT_DESC}},
        ),
        handler=sheet_metal_bend_table,
        timeout_class="fast",
    ),
]
