"""Drawing: new/views/BOM; section, model items, balloons; DRW3 create_drawing/inspect; L3 sheets/title block/GD&T/layers."""
from __future__ import annotations

from cadmcp.backend.protocol.constants import BOM_TYPES, DRAWING_VIEW_ALIASES, GDT_SYMBOLS
from cadmcp.drawing_spec import load_drawing_spec
from cadmcp.errors import fail
from cadmcp.kernel import OpContext
from cadmcp.registry import ToolSpec, make_schema
from cadmcp.safety import ensure_input_path, ensure_output_path
from cadmcp.toolsets.core._common import _DOC_EXTS, _doc_payload
from cadmcp.units import SUPPORTED_UNITS, UnitContext

_UNIT_DESC = "Unit; default mm."
_UNIT_ENUM = sorted(SUPPORTED_UNITS)
_SPEC_EXTS = {".json"}
_MODEL_EXTS = {".sldprt", ".sldasm", ".SLDPRT", ".SLDASM"}
_PAPER_ENUM = ["A0", "A1", "A2", "A3", "A4"]


def _unit_ctx(ctx: OpContext, unit: str) -> UnitContext:
    return ctx.units if unit == ctx.units.external_unit else UnitContext(unit)


def new_drawing(ctx: OpContext, template: str | None = None) -> dict:
    return _doc_payload(ctx.backend.new_drawing(template))


def create_drawing_view(ctx: OpContext, path: str, view: str = "front") -> dict:
    resolved = ensure_input_path(path, roots=ctx.workspace, extensions=_DOC_EXTS)
    name = ctx.backend.create_drawing_view(resolved, view)
    return {"name": name, "view": str(view).strip().lower()}


def insert_bom(ctx: OpContext, bom_type: str = "top") -> dict:
    n = ctx.backend.insert_bom(str(bom_type))
    return {"row_count": int(n), "bom_type": str(bom_type)}


def create_section_view(
    ctx: OpContext,
    label: str = "A",
    x: float = 220.0,
    y: float = 150.0,
    unit: str = "mm",
) -> dict:
    raw = str(label).strip()
    if not raw:
        raise fail("INVALID_ARGUMENT", "Section view label cannot be empty", "Pass label, e.g. A")
    uc = _unit_ctx(ctx, unit)
    name = ctx.backend.create_section_view(raw, uc.to_m(x), uc.to_m(y), 0.0)
    return {"name": name, "label": raw, "unit": uc.external_unit}


def insert_model_items(ctx: OpContext) -> dict:
    count = ctx.backend.insert_model_items()
    return {"count": int(count)}


def insert_balloons(ctx: OpContext) -> dict:
    count = ctx.backend.insert_balloons()
    return {"count": int(count)}


def add_drawing_sheet(
    ctx: OpContext,
    name: str,
    paper: str = "A4",
    scale_num: float = 1.0,
    scale_den: float = 1.0,
) -> dict:
    return dict(
        ctx.backend.add_drawing_sheet(str(name), str(paper), (float(scale_num), float(scale_den)))
    )


def activate_drawing_sheet(ctx: OpContext, name: str) -> dict:
    activated = ctx.backend.activate_drawing_sheet(str(name))
    return {"name": activated}


def set_title_block(ctx: OpContext, entries: list) -> dict:
    if not isinstance(entries, list) or not entries:
        raise fail("INVALID_ARGUMENT", "entries must be a non-empty array", '[{"key":"PartNo","value":"P-001"}]')
    cleaned: dict[str, str] = {}
    for i, item in enumerate(entries):
        if not isinstance(item, dict):
            raise fail("INVALID_ARGUMENT", f"entries[{i}] must be an object", "Include key/value")
        key = str(item.get("key") or "").strip()
        if not key:
            raise fail("INVALID_ARGUMENT", f"entries[{i}].key cannot be empty", "e.g. PartNo")
        cleaned[key] = str(item.get("value") or "")
    written = ctx.backend.set_title_block(cleaned)
    return {"written": written, "count": len(written)}


def insert_datum(
    ctx: OpContext,
    label: str,
    x: float = 100.0,
    y: float = 80.0,
    edge: int | None = None,
    unit: str = "mm",
) -> dict:
    uc = _unit_ctx(ctx, unit)
    name = ctx.backend.insert_datum(str(label), uc.to_m(x), uc.to_m(y), edge)
    return {
        "name": name,
        "label": str(label).strip(),
        "edge": edge,
        "unit": uc.external_unit,
    }


def insert_gdt(
    ctx: OpContext,
    symbol: str,
    tolerance: str,
    datums: list | None = None,
    x: float = 120.0,
    y: float = 60.0,
    edge: int | None = None,
    unit: str = "mm",
) -> dict:
    uc = _unit_ctx(ctx, unit)
    refs = tuple(str(d).strip() for d in (datums or []) if str(d).strip())
    name = ctx.backend.insert_gdt(
        str(symbol), str(tolerance), refs, uc.to_m(x), uc.to_m(y), edge
    )
    return {
        "name": name,
        "symbol": str(symbol).strip().lower(),
        "tolerance": str(tolerance).strip(),
        "datums": list(refs),
        "edge": edge,
        "unit": uc.external_unit,
    }


def create_drawing(ctx: OpContext, spec_path: str, overwrite: bool = False) -> dict:
    """Build a drawing from DrawingSpec (L2/L3) and optionally export PDF."""
    resolved = ensure_input_path(spec_path, roots=ctx.workspace, extensions=_SPEC_EXTS)
    spec = load_drawing_spec(resolved)
    model = ensure_input_path(spec["model"], roots=ctx.workspace, extensions=_MODEL_EXTS)
    ctx.backend.new_drawing()
    views_made: list[str] = []
    sheets_out: list[dict] = []
    warnings: list[str] = []

    sheet_list = spec.get("sheets")
    if isinstance(sheet_list, list) and sheet_list:
        for i, sh in enumerate(sheet_list):
            requested = str(sh["name"])
            if i == 0:
                # First sheet: live default name may differ; trust list_drawing_sheets()[0]
                sheet = ctx.backend.set_sheet_props(sh["paper"], tuple(sh["scale"]))
                cur = ctx.backend.list_drawing_sheets()
                name = cur[0] if cur else requested
                ctx.backend.activate_drawing_sheet(name)
                if name != requested:
                    warnings.append(
                        f"sheets[0] actual name {name!r} (requested {requested!r}; common with localized templates)"
                    )
            else:
                sheet = ctx.backend.add_drawing_sheet(requested, sh["paper"], tuple(sh["scale"]))
                name = str(sheet.get("name") or requested)
            page_views: list[str] = []
            for view in sh["views"]:
                page_views.append(ctx.backend.create_drawing_view(model, view["orient"]))
            views_made.extend(page_views)
            sheets_out.append(
                {
                    "name": name,
                    "requested_name": requested,
                    "paper": sheet.get("paper") if i == 0 else sh["paper"],
                    "scale": sheet.get("scale") if i == 0 else sh["scale"],
                    "views": page_views,
                }
            )
        sheet = {"paper": sheets_out[0]["paper"], "scale": sheets_out[0]["scale"]}
    else:
        sheet = ctx.backend.set_sheet_props(spec["paper"], tuple(spec["scale"]))  # type: ignore[arg-type]
        for view in spec["views"]:
            views_made.append(ctx.backend.create_drawing_view(model, view["orient"]))
        actual = (ctx.backend.list_drawing_sheets() or ["Sheet1"])[0]
        sheets_out = [
            {
                "name": actual,
                "requested_name": actual,
                "paper": sheet.get("paper"),
                "scale": sheet.get("scale"),
                "views": list(views_made),
            }
        ]

    section_name = None
    if isinstance(spec.get("section"), dict):
        sec = spec["section"]
        section_name = ctx.backend.create_section_view(
            str(sec.get("label") or "A"),
            float(sec.get("x", 0.22)),
            float(sec.get("y", 0.15)),
            0.0,
        )
        views_made.append(section_name)
    detail_name = None
    if isinstance(spec.get("detail"), dict):
        det = spec["detail"]
        uc = ctx.units
        detail_name = ctx.backend.create_detail_view(
            str(det.get("label") or "B"),
            uc.to_m(float(det.get("x", 0))),
            uc.to_m(float(det.get("y", 0))),
            uc.to_m(float(det.get("radius", 10))),
        )
        views_made.append(detail_name)
    ann_count = 0
    if spec.get("import_dimensions", True):
        ann_count = int(ctx.backend.insert_model_items())
    tol_count = 0
    if spec.get("tolerances"):
        tol_count = int(ctx.backend.apply_drawing_tolerances(list(spec["tolerances"])))

    title_written: dict = {}
    if isinstance(spec.get("title_block"), dict) and spec["title_block"]:
        title_written = dict(ctx.backend.set_title_block(dict(spec["title_block"])))

    datum_names: list[str] = []
    gdt_names: list[str] = []
    if isinstance(spec.get("gdts"), list):
        uc = ctx.units
        for item in spec["gdts"]:
            edge = item.get("edge")
            edge_i = int(edge) if edge is not None else None
            if item.get("kind") == "datum":
                datum_names.append(
                    ctx.backend.insert_datum(
                        str(item["label"]),
                        uc.to_m(float(item.get("x", 100))),
                        uc.to_m(float(item.get("y", 80))),
                        edge_i,
                    )
                )
            elif item.get("kind") == "gdt":
                gdt_names.append(
                    ctx.backend.insert_gdt(
                        str(item["symbol"]),
                        str(item["tolerance"]),
                        tuple(item.get("datums") or ()),
                        uc.to_m(float(item.get("x", 120))),
                        uc.to_m(float(item.get("y", 60))),
                        edge_i,
                    )
                )

    pdf_path = None
    if spec.get("output_pdf"):
        pdf = ensure_output_path(
            str(spec["output_pdf"]),
            roots=ctx.workspace,
            extensions={".pdf"},
            overwrite=overwrite,
        )
        ctx.backend.export_document(pdf, "pdf")
        pdf_path = str(pdf)
    return {
        "paper": sheet.get("paper"),
        "scale": sheet.get("scale"),
        "views": views_made,
        "sheets": sheets_out,
        "sheet_count": len(sheets_out),
        "section": section_name,
        "detail": detail_name,
        "annotation_count": ann_count,
        "tolerance_count": tol_count,
        "title_block": title_written,
        "datums": datum_names,
        "gdts": gdt_names,
        "pdf": pdf_path,
        "spec_path": str(resolved),
        "warnings": warnings,
    }


def inspect_drawing(ctx: OpContext) -> dict:
    return dict(ctx.backend.inspect_drawing())


def add_drawing_layer(ctx: OpContext, name: str, color: int = 255) -> dict:
    return dict(ctx.backend.add_drawing_layer(str(name), int(color)))


def set_drawing_layer(ctx: OpContext, name: str) -> dict:
    current = ctx.backend.set_drawing_layer(str(name))
    return {"name": current}


def list_drawing_layers(ctx: OpContext) -> dict:
    return dict(ctx.backend.list_drawing_layers())


DRAWING_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="new_drawing",
        toolset="drawing",
        description="Create a new A4 drawing from a .drwdot template.",
        input_schema=make_schema(
            {"template": {"type": "string", "description": "Optional .drwdot."}}
        ),
        handler=new_drawing,
        mutating=True,
    ),
    ToolSpec(
        name="create_drawing_view",
        toolset="drawing",
        description="Create a standard model view on the active drawing.",
        input_schema=make_schema(
            {
                "path": {"type": "string"},
                "view": {
                    "type": "string",
                    "enum": sorted(DRAWING_VIEW_ALIASES),
                    "default": "front",
                },
            },
            ["path"],
        ),
        handler=create_drawing_view,
        mutating=True,
    ),
    ToolSpec(
        name="insert_bom",
        toolset="drawing",
        description=(
            "Insert a BOM table on the active drawing (assembly views). "
            "Resolves bom-standard.sldbomtbt from the SolidWorks install (registry / executable path); "
            "returns row_count including header."
        ),
        input_schema=make_schema(
            {
                "bom_type": {
                    "type": "string",
                    "enum": list(BOM_TYPES),
                    "default": "top",
                    "description": "parts | top | indented",
                },
            }
        ),
        handler=insert_bom,
        mutating=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="create_section_view",
        toolset="drawing",
        description="Create a section view from the first drawing model view (horizontal cut through the view origin). Requires create_drawing_view first.",
        input_schema=make_schema(
            {
                "label": {"type": "string", "default": "A", "description": "Section label (A → A-A)."},
                "x": {"type": "number", "default": 220, "description": "Section-view sheet X."},
                "y": {"type": "number", "default": 150, "description": "Section-view sheet Y."},
                "unit": {"type": "string", "enum": _UNIT_ENUM, "description": _UNIT_DESC},
            }
        ),
        handler=create_section_view,
        mutating=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="insert_model_items",
        toolset="drawing",
        description="Import model dimensions onto the first drawing view (Insert Model Items). Requires a view; unmarked sketch/feature dims are included.",
        input_schema=make_schema({}),
        handler=insert_model_items,
        mutating=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="insert_balloons",
        toolset="drawing",
        description="Auto-balloon the first drawing view. Assembly drawings get one balloon per component instance.",
        input_schema=make_schema({}),
        handler=insert_balloons,
        mutating=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="create_drawing",
        toolset="drawing",
        description=(
            "Build a drawing from a DrawingSpec JSON (views/sheets, optional section/detail, "
            "paper/scale, title_block, gdts, tolerances, optional PDF). L1 tools remain available."
        ),
        input_schema=make_schema(
            {
                "spec_path": {"type": "string", "description": "Workspace-relative DrawingSpec .json."},
                "overwrite": {"type": "boolean", "default": False, "description": "Allow PDF overwrite."},
            },
            ["spec_path"],
        ),
        handler=create_drawing,
        mutating=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="inspect_drawing",
        toolset="drawing",
        description="Inspect the active drawing: views, sheets, title_block, gdts, paper/scale, tolerances.",
        input_schema=make_schema({}),
        handler=inspect_drawing,
        timeout_class="fast",
    ),
    ToolSpec(
        name="add_drawing_sheet",
        toolset="drawing",
        description="Add a drawing sheet (DRW3 L3-A) with paper size and scale; activates the new sheet.",
        input_schema=make_schema(
            {
                "name": {"type": "string", "description": "Sheet name, e.g. Sheet2."},
                "paper": {"type": "string", "enum": _PAPER_ENUM, "default": "A4"},
                "scale_num": {"type": "number", "default": 1},
                "scale_den": {"type": "number", "default": 1},
            },
            ["name"],
        ),
        handler=add_drawing_sheet,
        mutating=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="activate_drawing_sheet",
        toolset="drawing",
        description="Activate an existing drawing sheet by name (DRW3 L3-A).",
        input_schema=make_schema(
            {"name": {"type": "string", "description": "Sheet name."}},
            ["name"],
        ),
        handler=activate_drawing_sheet,
        mutating=True,
        timeout_class="fast",
    ),
    ToolSpec(
        name="set_title_block",
        toolset="drawing",
        description=(
            "Write drawing custom properties used by the title block (DRW3 L3-B). "
            "Keys should match the .drwdot template links (PartNo, Description, DrawnBy, Date, …)."
        ),
        input_schema=make_schema(
            {
                "entries": {
                    "type": "array",
                    "description": "Title-block fields as {key,value} pairs.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string"},
                            "value": {"type": "string"},
                        },
                        "required": ["key", "value"],
                        "additionalProperties": False,
                    },
                },
            },
            ["entries"],
        ),
        handler=set_title_block,
        mutating=True,
        timeout_class="fast",
    ),
    ToolSpec(
        name="insert_datum",
        toolset="drawing",
        description=(
            "Insert a datum tag on the active drawing (DRW3 L3-C). "
            "Pre-selects a visible view edge (optional edge index); may fall back to a text note."
        ),
        input_schema=make_schema(
            {
                "label": {"type": "string", "description": "Datum label, e.g. A."},
                "x": {"type": "number", "default": 100},
                "y": {"type": "number", "default": 80},
                "edge": {
                    "type": "integer",
                    "description": "Visible drawing-view edge index; omit to auto-pick first.",
                },
                "unit": {"type": "string", "enum": _UNIT_ENUM, "description": _UNIT_DESC},
            },
            ["label"],
        ),
        handler=insert_datum,
        mutating=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="insert_gdt",
        toolset="drawing",
        description=(
            "Insert a geometric tolerance frame (DRW3 L3-C). "
            f"Symbols: {', '.join(GDT_SYMBOLS)}. Pre-selects a visible edge; may note-fallback."
        ),
        input_schema=make_schema(
            {
                "symbol": {"type": "string", "enum": list(GDT_SYMBOLS)},
                "tolerance": {"type": "string", "description": "Tolerance value, e.g. 0.1."},
                "datums": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Datum references, e.g. [\"A\"].",
                },
                "x": {"type": "number", "default": 120},
                "y": {"type": "number", "default": 60},
                "edge": {
                    "type": "integer",
                    "description": "Visible drawing-view edge index; omit to auto-pick first.",
                },
                "unit": {"type": "string", "enum": _UNIT_ENUM, "description": _UNIT_DESC},
            },
            ["symbol", "tolerance"],
        ),
        handler=insert_gdt,
        mutating=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="add_drawing_layer",
        toolset="drawing",
        description=(
            "Add a named layer on the active drawing. Export to .dxf writes the layer table; "
            "custom map files are not used (avoids the DXF mapping dialog)."
        ),
        input_schema=make_schema(
            {
                "name": {"type": "string", "description": "Layer name, e.g. VISIBLE."},
                "color": {
                    "type": "integer",
                    "default": 255,
                    "description": "SolidWorks color int (255=red, 65280=green).",
                },
            },
            ["name"],
        ),
        handler=add_drawing_layer,
        mutating=True,
    ),
    ToolSpec(
        name="set_drawing_layer",
        toolset="drawing",
        description="Set the current drawing layer; new annotations use this layer in DXF export.",
        input_schema=make_schema(
            {"name": {"type": "string", "description": "Existing layer name."}},
            ["name"],
        ),
        handler=set_drawing_layer,
        mutating=True,
    ),
    ToolSpec(
        name="list_drawing_layers",
        toolset="drawing",
        description=(
            "List drawing layers: count, current, and known names "
            "(session-added; 2025 COM cannot enumerate every template layer by index)."
        ),
        input_schema=make_schema({}),
        handler=list_drawing_layers,
        mutating=False,
    ),
]
