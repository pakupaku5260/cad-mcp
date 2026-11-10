"""Fake backend · document domain（S8c）。

S8c: 21 methods (new/open/save/close/active doc + config/material + drawing + BOM + export).

Dependencies (self, MRO):
- `_enter` / `calls` / `_counts`（FakeBackend）
- `_require_doc` / `_require_drawing` (this module / FakeBackend)
- `_doc` / `_part_seq` / `_asm_seq` / `_draw_seq` / `_edit_component`（FakeBackend._init_state）
- `_part_library` / `_assembly_library`（FakeBackend._init_state）
- `_geom` / `list_faces` / `list_edges` / `_snapshot_component` (FakeBackend body until S8g)

Imports:
- `cadmcp.backend.export_formats`（ensure_doc_type）
- `cadmcp.backend.protocol.constants`（BOM_TYPES）
- `cadmcp.backend.protocol.models`（BomRow / DocInfo）
- `cadmcp.backend.protocol.parsers`（drawing_view_key / rollup_bom_rows）
- `cadmcp.errors`（fail）
- `._state`（_Doc / _as_assembly_snap_item）
"""
from __future__ import annotations

from pathlib import Path

from cadmcp.backend.export_formats import ensure_doc_type, validate_export_options
from cadmcp.backend.protocol.constants import (
    BOM_TYPES,
    GDT_SYMBOLS,
    TITLE_BLOCK_DEFAULT_KEYS,
)
from cadmcp.backend.protocol.models import BomRow, DocInfo
from cadmcp.backend.protocol.parsers import drawing_view_key, rollup_bom_rows
from cadmcp.errors import fail

from ._state import _as_assembly_snap_item, _Doc


class FakeDocumentMixin:
    """document domain (S8c: 21 methods)."""

    def _init_state(self) -> None:
        pass  # State owned by FakeBackend._init_state

    # ---------- New / open / save / close ----------

    def new_part(self, template: str | None = None) -> DocInfo:
        self._enter("new_part", template=template)
        self._part_seq += 1
        self._doc = _Doc(title=f"Part{self._part_seq}")
        self._edit_component = None
        return self._doc_info()

    def new_assembly(self, template: str | None = None) -> DocInfo:
        self._enter("new_assembly", template=template)
        self._asm_seq += 1
        self._doc = _Doc(title=f"Assembly{self._asm_seq}", doc_type="assembly")
        self._edit_component = None
        return self._doc_info()

    def open_document(self, path: Path) -> DocInfo:
        self._enter("open_document", path=path)
        # Existence enforced by tool sandbox; fake only strict validation (protocol semantics)
        if not path.exists():
            raise fail(
                "OPEN_FAILED", f"File does not exist: {path}",
                "Check path spelling and directory (relative to workspace)",
            )
        doc_type = {".sldasm": "assembly", ".slddrw": "drawing"}.get(path.suffix.lower(), "part")
        self._doc = _Doc(title=path.stem, path=path, doc_type=doc_type)
        self._edit_component = None
        return self._doc_info()

    def save_as(self, path: Path) -> None:
        self._enter("save_as", path=path)
        doc = self._require_doc()
        if path.exists() and not path.is_file():
            raise fail("SAVE_FAILED", f"Target is not a regular file：{path}", "Use a different output path")
        try:
            path.write_text(f"FAKE-DOC:{doc.title}", encoding="utf-8")
        except OSError as exc:
            raise fail(
                "SAVE_FAILED", f"Write failed: {exc}",
                "Check that the directory exists and is writable",
            ) from exc
        doc.path = str(path)
        doc.title = path.stem  # SW behavior: title becomes file name after save-as
        doc.modified = False
        if doc.doc_type == "part":
            g = self._geom()
            self._part_library[str(Path(path).resolve())] = (
                list(self.list_faces()),
                list(self.list_edges()),
                tuple(g["bbox"]),
                doc.material,
                float(g["volume"]),
                float(g["area"]),
                int(g["faces"]),
                int(g["edges"]),
            )
        elif doc.doc_type == "assembly":
            self._assembly_library[str(Path(path).resolve())] = [
                self._snapshot_component(doc, name) for name in doc.components
            ]

    def close_document(self, discard: bool) -> None:
        self._enter("close_document", discard=discard)
        self._require_doc()
        self._doc = None  # Discard allowed per tool-layer confirm flag
        self._edit_component = None

    def active_document(self) -> DocInfo | None:
        self._enter("active_document")
        return self._doc_info() if self._doc else None

    def _doc_info(self) -> DocInfo:
        doc = self._require_doc()
        return DocInfo(
            title=doc.title, path=doc.path, doc_type=doc.doc_type, modified=doc.modified
        )

    # ---------- Drawing ----------

    def new_drawing(self, template: str | None = None) -> DocInfo:
        self._enter("new_drawing", template=template)
        self._draw_seq += 1
        self._doc = _Doc(title=f"Drawing{self._draw_seq}", doc_type="drawing")
        return self._doc_info()

    def create_drawing_view(self, model: Path, view: str) -> str:
        self._enter("create_drawing_view", model=model, view=view)
        doc = self._require_doc()
        if doc.doc_type != "drawing":
            raise fail("INVALID_ARGUMENT", "Active document is not a drawing", "Call new_drawing first")
        key = drawing_view_key(view)
        if not model.exists():
            raise fail("OPEN_FAILED", f"Model file does not exist: {model}", "save_document the part or assembly first")
        doc.drawing_model = str(Path(model).resolve())
        doc.drawing_views.append(key)
        for sh in doc.drawing_sheets:
            if sh["name"] == doc.drawing_active_sheet:
                sh.setdefault("views", []).append(key)
                break
        doc.modified = True
        return key

    def _require_drawing(self, hint: str):
        doc = self._require_doc()
        if doc.doc_type != "drawing":
            raise fail("INVALID_ARGUMENT", "Active document is not a drawing", hint)
        return doc

    def _active_sheet(self, doc: _Doc) -> dict:
        for sh in doc.drawing_sheets:
            if sh["name"] == doc.drawing_active_sheet:
                return sh
        if doc.drawing_sheets:
            return doc.drawing_sheets[0]
        raise fail("FEATURE_CREATE_FAILED", "Drawing has no sheet", "Call new_drawing first")

    def create_section_view(
        self, label: str = "A", x_m: float = 0.22, y_m: float = 0.15, depth_m: float = 0.0
    ) -> str:
        self._enter("create_section_view", label=label, x=x_m, y=y_m, depth=depth_m)
        doc = self._require_drawing("Call new_drawing and create_drawing_view first")
        raw = str(label).strip()
        if not raw:
            raise fail("INVALID_ARGUMENT", "Section label cannot be empty", "Pass label, e.g. A")
        if not doc.drawing_views:
            raise fail("INVALID_ARGUMENT", "Drawing has no model view yet", "create_drawing_view first")
        name = f"section_{raw}"
        doc.drawing_views.append(name)
        doc.modified = True
        return name

    def insert_model_items(self) -> int:
        self._enter("insert_model_items")
        doc = self._require_drawing("Call new_drawing and create_drawing_view first")
        if not doc.drawing_views:
            raise fail("INVALID_ARGUMENT", "Drawing has no model view yet", "create_drawing_view first")
        doc.drawing_annotations = max(1, doc.drawing_annotations)
        doc.modified = True
        return int(doc.drawing_annotations)

    def insert_balloons(self) -> int:
        self._enter("insert_balloons")
        doc = self._require_drawing("Call new_drawing and create_drawing_view first")
        if not doc.drawing_views:
            raise fail("INVALID_ARGUMENT", "Drawing has no model view yet", "create_drawing_view first")
        count = 1
        if doc.drawing_model:
            count = max(1, len(self._entries_for_model(doc.drawing_model)))
        doc.modified = True
        return count

    def set_sheet_props(self, paper: str, scale: tuple[float, float]) -> dict:
        self._enter("set_sheet_props", paper=paper, scale=scale)
        doc = self._require_drawing("Call new_drawing first")
        doc.drawing_paper = str(paper).upper()
        doc.drawing_scale = (float(scale[0]), float(scale[1]))
        sh = self._active_sheet(doc)
        sh["paper"] = doc.drawing_paper
        sh["scale"] = list(doc.drawing_scale)
        doc.modified = True
        return {"paper": doc.drawing_paper, "scale": list(doc.drawing_scale)}

    def add_drawing_layer(self, name: str, color: int = 255) -> dict:
        self._enter("add_drawing_layer", name=name, color=color)
        doc = self._require_drawing("Call new_drawing first")
        raw = str(name).strip()
        if not raw:
            raise fail("INVALID_ARGUMENT", "Layer name cannot be empty", "Pass name, e.g. VISIBLE")
        if not isinstance(color, int) or isinstance(color, bool):
            raise fail("INVALID_ARGUMENT", "color must be an integer color value", "e.g. 255 (red) or 65280 (green)")
        if any(layer["name"] == raw for layer in doc.drawing_layers):
            raise fail(
                "INVALID_ARGUMENT",
                f"Layer already exists: {raw}",
                "Use a different name, or set_drawing_layer",
                requested=raw,
            )
        doc.drawing_layers.append({"name": raw, "color": int(color)})
        doc.modified = True
        return {"name": raw, "color": int(color)}

    def set_drawing_layer(self, name: str) -> str:
        self._enter("set_drawing_layer", name=name)
        doc = self._require_drawing("Call new_drawing first")
        raw = str(name).strip()
        if not raw:
            raise fail("INVALID_ARGUMENT", "Layer name cannot be empty", "Pass name, or add_drawing_layer first")
        if not any(layer["name"] == raw for layer in doc.drawing_layers):
            raise fail(
                "FEATURE_NOT_FOUND",
                f"Layer not found: {raw}",
                "add_drawing_layer first, or check list_drawing_layers",
                requested=raw,
            )
        doc.drawing_current_layer = raw
        doc.modified = True
        return raw

    def list_drawing_layers(self) -> dict:
        self._enter("list_drawing_layers")
        doc = self._require_drawing("Call new_drawing first")
        names = [str(layer["name"]) for layer in doc.drawing_layers]
        return {
            "count": len(names),
            "current": doc.drawing_current_layer,
            "layers": names,
        }

    def add_drawing_sheet(self, name: str, paper: str, scale: tuple[float, float]) -> dict:
        self._enter("add_drawing_sheet", name=name, paper=paper, scale=scale)
        doc = self._require_drawing("Call new_drawing first")
        raw = str(name).strip()
        if not raw:
            raise fail("INVALID_ARGUMENT", "Sheet name cannot be empty", "Pass name, e.g. Sheet2")
        if any(sh["name"] == raw for sh in doc.drawing_sheets):
            raise fail("INVALID_ARGUMENT", f"Sheet already exists: {raw}", "Use a different name or activate_drawing_sheet first")
        paper_u = str(paper).strip().upper()
        sc = [float(scale[0]), float(scale[1])]
        doc.drawing_sheets.append({"name": raw, "paper": paper_u, "scale": sc, "views": []})
        doc.drawing_active_sheet = raw
        doc.drawing_paper = paper_u
        doc.drawing_scale = (sc[0], sc[1])
        doc.modified = True
        return {"name": raw, "paper": paper_u, "scale": sc}

    def activate_drawing_sheet(self, name: str) -> str:
        self._enter("activate_drawing_sheet", name=name)
        doc = self._require_drawing("Call new_drawing first")
        raw = str(name).strip()
        for sh in doc.drawing_sheets:
            if sh["name"] == raw:
                doc.drawing_active_sheet = raw
                doc.drawing_paper = str(sh.get("paper") or "A4")
                sc = sh.get("scale") or [1.0, 1.0]
                doc.drawing_scale = (float(sc[0]), float(sc[1]))
                return raw
        raise fail(
            "FEATURE_NOT_FOUND",
            f"Sheet not found: {raw}",
            f"Existing: {', '.join(sh['name'] for sh in doc.drawing_sheets)}",
        )

    def list_drawing_sheets(self) -> list[str]:
        self._enter("list_drawing_sheets")
        doc = self._require_drawing("Call new_drawing first")
        return [str(sh["name"]) for sh in doc.drawing_sheets]

    def set_title_block(self, props: dict[str, str]) -> dict:
        self._enter("set_title_block", keys=list(props))
        doc = self._require_drawing("Call new_drawing first")
        written: dict[str, str] = {}
        for k, v in props.items():
            key = str(k).strip()
            if not key:
                continue
            written[key] = str(v)
            doc.title_block[key] = str(v)
        doc.modified = True
        return written

    def get_title_block(self, keys: list[str] | None = None) -> dict:
        self._enter("get_title_block", keys=keys)
        doc = self._require_drawing("Call new_drawing first")
        want = list(keys) if keys else list(TITLE_BLOCK_DEFAULT_KEYS)
        return {k: doc.title_block.get(k, "") for k in want}

    def insert_datum(
        self, label: str, x_m: float = 0.1, y_m: float = 0.1, edge: int | None = None
    ) -> str:
        self._enter("insert_datum", label=label, x=x_m, y=y_m, edge=edge)
        doc = self._require_drawing("Call new_drawing first")
        raw = str(label).strip()
        if not raw:
            raise fail("INVALID_ARGUMENT", "Datum label cannot be empty", "Pass label, e.g. A")
        if edge is not None and int(edge) < 0:
            raise fail("INVALID_ARGUMENT", f"edge index invalid: {edge}", "Pass a visible edge index >= 0")
        name = f"datum_{raw}"
        doc.drawing_datums.append(
            {
                "name": name,
                "label": raw,
                "mode": "native",
                "edge_selected": True,
                "edge": None if edge is None else int(edge),
                "x_m": float(x_m),
                "y_m": float(y_m),
            }
        )
        doc.drawing_annotations += 1
        doc.modified = True
        return name

    def insert_gdt(
        self,
        symbol: str,
        tolerance: str,
        datums: tuple[str, ...] = (),
        x_m: float = 0.1,
        y_m: float = 0.1,
        edge: int | None = None,
    ) -> str:
        self._enter("insert_gdt", symbol=symbol, tolerance=tolerance, datums=datums, edge=edge)
        doc = self._require_drawing("Call new_drawing first")
        sym = str(symbol).strip().lower()
        if sym not in GDT_SYMBOLS:
            raise fail(
                "INVALID_ARGUMENT",
                f"Unknown GD&T symbol: {symbol!r}",
                f"Options: {', '.join(GDT_SYMBOLS)}",
            )
        tol = str(tolerance).strip()
        if not tol:
            raise fail("INVALID_ARGUMENT", "Tolerance value cannot be empty", "Pass tolerance, e.g. 0.1")
        if edge is not None and int(edge) < 0:
            raise fail("INVALID_ARGUMENT", f"edge index invalid: {edge}", "Pass a visible edge index >= 0")
        refs = tuple(str(d).strip() for d in datums if str(d).strip())
        name = f"gdt_{sym}_{len(doc.drawing_gdts) + 1}"
        doc.drawing_gdts.append(
            {
                "name": name,
                "symbol": sym,
                "tolerance": tol,
                "datums": list(refs),
                "mode": "native",
                "edge_selected": True,
                "edge": None if edge is None else int(edge),
                "x_m": float(x_m),
                "y_m": float(y_m),
            }
        )
        doc.drawing_annotations += 1
        doc.modified = True
        return name

    def create_detail_view(
        self, label: str = "B", x_m: float = 0.0, y_m: float = 0.0, radius_m: float = 0.01
    ) -> str:
        self._enter("create_detail_view", label=label, x=x_m, y=y_m, radius=radius_m)
        doc = self._require_drawing("Call new_drawing and create_drawing_view first")
        if not doc.drawing_views:
            raise fail("INVALID_ARGUMENT", "Drawing has no model view yet", "create_drawing_view first")
        if float(radius_m) <= 0:
            raise fail("INVALID_ARGUMENT", "detail radius must be positive", "Pass radius > 0")
        name = f"detail_{str(label).strip() or 'B'}"
        doc.drawing_views.append(name)
        doc.modified = True
        return name

    def apply_drawing_tolerances(self, tolerances: list[dict]) -> int:
        self._enter("apply_drawing_tolerances", count=len(tolerances))
        doc = self._require_drawing("Call new_drawing first")
        doc.drawing_tolerances = [dict(t) for t in tolerances]
        doc.drawing_annotations = max(doc.drawing_annotations, len(doc.drawing_tolerances))
        doc.modified = True
        return len(doc.drawing_tolerances)

    def inspect_drawing(self) -> dict:
        self._enter("inspect_drawing")
        doc = self._require_drawing("Call new_drawing first")
        views = list(doc.drawing_views)
        title = {k: doc.title_block.get(k, "") for k in TITLE_BLOCK_DEFAULT_KEYS}
        missing = [k for k in TITLE_BLOCK_DEFAULT_KEYS if not doc.title_block.get(k)]
        sheets = [
            {
                "name": sh["name"],
                "paper": sh.get("paper"),
                "scale": list(sh.get("scale") or [1.0, 1.0]),
                "view_count": len(sh.get("views") or []),
            }
            for sh in doc.drawing_sheets
        ]
        return {
            "view_count": len(views),
            "views": views,
            "annotation_count": int(doc.drawing_annotations) or (1 if views else 0),
            "paper": doc.drawing_paper,
            "scale": list(doc.drawing_scale),
            "tolerances": list(doc.drawing_tolerances),
            "missing_tolerances": [],
            "untoleranced_dimensions": [],
            "sheet_count": len(doc.drawing_sheets),
            "active_sheet": doc.drawing_active_sheet,
            "sheets": sheets,
            "title_block": title,
            "missing_title_fields": missing,
            "datum_count": len(doc.drawing_datums),
            "datums": list(doc.drawing_datums),
            "gdt_count": len(doc.drawing_gdts),
            "gdts": list(doc.drawing_gdts),
        }

    def export_document(
        self,
        path: Path,
        fmt: str,
        *,
        step_ap: int | None = None,
        stl_quality: str | None = None,
    ) -> None:
        self._enter(
            "export_document",
            path=path,
            fmt=fmt,
            step_ap=step_ap,
            stl_quality=stl_quality,
        )
        doc = self._require_doc()
        ensure_doc_type(fmt, doc.doc_type)
        validate_export_options(fmt, step_ap=step_ap, stl_quality=stl_quality)
        if path.exists() and not path.is_file():
            raise fail("SAVE_FAILED", f"Target is not a regular file：{path}", "Use a different output path")
        marker = f"FAKE-EXPORT:{fmt}:{doc.title}"
        if step_ap is not None:
            marker += f":ap={int(step_ap)}"
        if stl_quality is not None:
            marker += f":quality={str(stl_quality).strip().lower()}"
        if fmt == "dxf":
            layers = ",".join(str(layer["name"]) for layer in doc.drawing_layers)
            marker += f":layers={layers}:current={doc.drawing_current_layer}"
        try:
            path.write_text(marker, encoding="utf-8")
        except OSError as exc:
            raise fail(
                "SAVE_FAILED", f"Write failed: {exc}",
                "Check that the directory exists and is writable",
            ) from exc
        # Export is copy semantics: does not change doc.path / title / modified.

    # ---------- Config / material ----------

    def list_configurations(self) -> tuple[str, list[str]]:
        self._enter("list_configurations")
        doc = self._require_doc()
        if doc.doc_type == "drawing":
            raise fail("INVALID_ARGUMENT", "Drawing has no model configuration", "Query configuration on part or assembly")
        return doc.active_config, list(doc.config_names)

    def set_configuration(self, name: str, create: bool = False) -> tuple[str, bool]:
        self._enter("set_configuration", name=name, create=create)
        doc = self._require_doc()
        if doc.doc_type == "drawing":
            raise fail("INVALID_ARGUMENT", "Cannot switch model configuration on drawing", "set_configuration on part or assembly")
        raw = str(name).strip()
        if not raw:
            raise fail("INVALID_ARGUMENT", "Configuration name cannot be empty", "Pass name")
        created = False
        if raw not in doc.config_names:
            if not create:
                raise fail(
                    "FEATURE_NOT_FOUND",
                    f"Configuration not found: {raw!r}",
                    "list_configurations first, or set_configuration(..., create=true)",
                    name=raw,
                )
            doc.config_names.append(raw)
            created = True
        doc.active_config = raw
        doc.modified = True
        return raw, created

    def get_material(self) -> tuple[str, str]:
        self._enter("get_material")
        doc = self._require_doc()
        if doc.doc_type != "part":
            raise fail("INVALID_ARGUMENT", "Material grade only on parts", "Open or create a part first")
        return doc.material, "fake"

    def set_material(self, name: str) -> tuple[str, str]:
        self._enter("set_material", name=name)
        doc = self._require_doc()
        if doc.doc_type != "part":
            raise fail("INVALID_ARGUMENT", "Set material grade only on parts", "Open or create a part first")
        raw = str(name).strip()
        if not raw:
            raise fail("INVALID_ARGUMENT", "Material grade cannot be empty", "e.g. AISI 1020")
        doc.material = raw
        doc.modified = True
        return raw, "fake"

    def set_color(self, r: float, g: float, b: float) -> tuple[float, float, float]:
        self._enter("set_color", r=r, g=g, b=b)
        doc = self._require_part("Use a part document to set appearance color")
        rgb = (float(r), float(g), float(b))
        for c in rgb:
            if c < 0.0 or c > 1.0:
                raise fail("INVALID_ARGUMENT", "RGB components must be in 0–1", "Pass 0 <= r,g,b <= 1")
        doc.color = rgb
        doc.modified = True
        return rgb

    def get_color(self) -> tuple[float, float, float] | None:
        self._enter("get_color")
        doc = self._require_part("Use a part document to get appearance color")
        return doc.color        

    # ---------- BOM ----------

    def _entries_for_model(self, path: str) -> list[tuple[str, str, str, str]]:
        resolved = str(Path(path).resolve())
        if resolved in self._assembly_library:
            out: list[tuple[str, str, str, str]] = []
            for item in self._assembly_library[resolved]:
                row = _as_assembly_snap_item(item)
                out.append(
                    (
                        str(row.get("name") or ""),
                        str(row.get("path") or ""),
                        str(row.get("material") or ""),
                        str(row.get("config") or "Default"),
                    )
                )
            return out
        stored = self._part_library.get(resolved)
        material = stored[3] if stored and len(stored) > 3 else ""
        stem = Path(path).stem
        return [(f"{stem}-1", path, material, "Default")]

    def get_bom(self) -> tuple[str, list[BomRow]]:
        self._enter("get_bom")
        doc = self._require_doc()
        if doc.doc_type == "assembly":
            entries = [
                (n, p, doc.component_material.get(n, ""), doc.active_config)
                for n, p in doc.components.items()
            ]
            return "assembly", rollup_bom_rows(entries)
        if doc.doc_type == "part":
            name = Path(doc.path).stem if doc.path else doc.title
            return "part", rollup_bom_rows([(name, doc.path or name, doc.material, doc.active_config)])
        if not doc.bom_inserted or not doc.bom_rows:
            raise fail(
                "FEATURE_NOT_FOUND",
                "Drawing has no BOM table yet",
                "create_drawing_view first, then insert_bom",
            )
        return "drawing", list(doc.bom_rows)

    def insert_bom(self, bom_type: str = "top") -> int:
        self._enter("insert_bom", bom_type=bom_type)
        doc = self._require_doc()
        if bom_type not in BOM_TYPES:
            raise fail(
                "INVALID_ARGUMENT",
                f"Unknown BOM type: {bom_type!r}",
                f"bom_type：{', '.join(BOM_TYPES)}",
            )
        if doc.doc_type != "drawing":
            raise fail("INVALID_ARGUMENT", "BOM insert only on drawings", "Call new_drawing and create_drawing_view first")
        if not doc.drawing_views or not doc.drawing_model:
            raise fail("INVALID_ARGUMENT", "Drawing has no model view yet", "create_drawing_view first")
        doc.bom_rows = rollup_bom_rows(self._entries_for_model(doc.drawing_model))
        doc.bom_inserted = True
        doc.modified = True
        return len(doc.bom_rows) + 1  # includes header
        