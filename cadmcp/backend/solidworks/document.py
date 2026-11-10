"""COM backend · document domain (new / open / save / close / export / BOM)."""
from __future__ import annotations

import logging
import re
import traceback
from pathlib import Path
from typing import Any

from cadmcp.backend.export_formats import (
    STL_QUALITY_CODES,
    ensure_doc_type,
    validate_export_options,
)
from cadmcp.backend.protocol.constants import BOM_TYPE_IDS, BOM_TYPES
from cadmcp.backend.protocol.models import BomRow, DocInfo, RebuildOutcome
from cadmcp.backend.protocol.parsers import rollup_bom_rows
from cadmcp.errors import SideEffect, fail

from ._constants import (
    _SW_DXF_DONT_SHOW_MAP,
    _SW_DXF_MAPPING,
    _SW_STEP_AP,
    _SW_STL_QUALITY,
    SW_DOC_ASSEMBLY,
    SW_DOC_DRAWING,
    SW_DOC_PART,
    SW_DOC_TYPE_NAMES,
)
from ._helpers import _doc_type_for, _get

log = logging.getLogger(__name__)

# swBOMConfigurationAnchor_TopLeft / swNumberingType_None (matches probe_drw3_l3 / swconst.tlb)
_SW_BOM_ANCHOR_TOP_LEFT = 1
_SW_NUM_NONE = 0


class DocumentMixin:
    """Document domain: new / open / save / close / export / BOM."""

    def _init_state(self) -> None:
        pass  # stateless

    def _reset_session_state(self) -> None:
        """On document switch, reset each Mixin-owned state separately (issue-3)."""
        self._reset_sketch_state()
        self._reset_naming_state()
        self._reset_plane_state()

    def revision(self) -> str:
        return str(self._call(lambda: _get(self.sw, "RevisionNumber")))

    def new_part(self, template: str | None = None) -> DocInfo:
        def _fn() -> DocInfo:
            tpl = self._resolve_template(template)
            doc = self.sw.NewDocument(tpl, 0, 0, 0)
            if doc is None:
                raise fail(
                    "OPEN_FAILED",
                    f"NewDocument returned None (template={tpl!r})",
                    "Check the template is valid, or pass template pointing at an existing .prtdot",
                    side_effect=SideEffect.NONE,
                )
            self._reset_session_state()
            return self._doc_info(doc, "part")

        return self._call(_fn)

    def new_assembly(self, template: str | None = None) -> DocInfo:
        def _fn() -> DocInfo:
            tpl = ""
            if template:
                candidate = Path(template)
                tpl = str(candidate) if candidate.is_file() else template
            if not tpl:
                try:
                    tpl = self.sw.GetDocumentTemplate(SW_DOC_ASSEMBLY, "", 0, 0, 0) or ""
                except Exception:
                    tpl = ""
                if tpl and not Path(tpl).is_file():
                    tpl = ""
            if not tpl:
                folder = self._template_folder()
                if folder is not None:
                    for name in ("gb_assembly.asmdot", "Assembly.asmdot", "\u88c5\u914d\u4f53.asmdot"):
                        candidate = folder / name
                        if candidate.is_file():
                            tpl = str(candidate)
                            break
                    if not tpl:
                        try:
                            for candidate in sorted(folder.glob("*.asmdot")):
                                if candidate.is_file():
                                    tpl = str(candidate)
                                    break
                        except OSError:
                            pass
            if not tpl:
                raise fail(
                    "OPEN_FAILED",
                    "No usable assembly template found",
                    "Check SolidWorks template path (User Preferences) or pass template with an explicit .asmdot",
                    side_effect=SideEffect.NONE,
                )
            doc = self.sw.NewDocument(tpl, 0, 0, 0)
            if doc is None:
                raise fail("OPEN_FAILED", f"NewDocument returned None (template={tpl!r})", "Check the template is valid")
            self._reset_session_state()
            return self._doc_info(doc, "assembly")

        return self._call(_fn)

    def new_drawing(self, template: str | None = None) -> DocInfo:
        def _fn() -> DocInfo:
            tpl = self._resolve_drawing_template(template)
            # NewDocument(.drwdot) often returns None on real hardware; NewDrawing2 + A4 is known good.
            doc = self.sw.NewDrawing2(12, tpl, 12, 0.21, 0.297)
            if doc is None:
                raise fail(
                    "OPEN_FAILED",
                    f"NewDrawing2 returned None (template={tpl!r})",
                    "Check the .drwdot template, or dismiss dialogs blocking new document creation",
                    side_effect=SideEffect.NONE,
                )
            self._reset_session_state()
            if hasattr(self, "_reset_drawing_l3_state"):
                self._reset_drawing_l3_state()
            return self._doc_info(doc, "drawing")

        return self._call(_fn)

    def open_document(self, path: Path) -> DocInfo:
        doc_type, sw_type = _doc_type_for(Path(path))

        def _fn() -> DocInfo:
            # SW2025 OpenDoc6 with pywin32 late binding can type-mismatch on out-params (Errors/Warnings);
            # OpenDoc has no out-params and works as fallback.
            attempts = (
                lambda: self.sw.OpenDoc6(str(path), sw_type, 0, "", 0, 0),
                lambda: self.sw.OpenDoc(str(path), sw_type),
            )
            errors: list[str] = []
            for opener in attempts:
                try:
                    doc = opener()
                except Exception as exc:  # noqa: BLE001 — try next channel before surfacing error
                    errors.append(f"{type(exc).__name__}: {exc}")
                    continue
                if doc is not None:
                    return self._doc_info(doc, doc_type)
                errors.append("returned None")
            raise fail(
                "OPEN_FAILED",
                f"Open failed: {path} ({' | '.join(errors)})",
                "Confirm the file exists, type is correct, and is not locked by another process",
            )
        self._reset_session_state()
        return self._call(_fn)

    def save_as(self, path: Path) -> None:
        def _fn() -> None:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            # SaveAs3: success is 0 (int) or True; failure is 1 (int) or False.
            # Note 0 == False and 1 == True; do not use == / in tuple for checks.
            res = _get(doc, "SaveAs3", str(path), 0, 2)
            failed = res is False or res == "1" or (
                isinstance(res, int) and not isinstance(res, bool) and res != 0
            )
            if failed:
                raise fail(
                    "SAVE_FAILED",
                    f"SaveAs3 failed (returned {res!r}): {path}",
                    "Check path permissions, file locks, and that SolidWorks has no pending dialogs",
                )

        self._call(_fn)

    def close_document(self, discard: bool) -> None:
        # Whether unsaved changes may be discarded is enforced at tool layer (core.close_document);
        # backend only guarantees the document is actually closed on return, else raises (no silent fail).
        def _fn() -> None:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "No need to close")
            title = str(_get(doc, "GetTitle"))
            candidates = [title]
            try:
                path = _get(doc, "GetPathName")
                if path:
                    candidates.append(str(path))
            except Exception:
                pass
            for name in candidates:  # retry full path when title mismatches (e.g. hidden extension)
                try:
                    self.sw.CloseDoc(name)
                except Exception:
                    log.debug("CloseDoc(%r) failed: %s", name, traceback.format_exc())
                after = self.sw.ActiveDoc
                if after is None or str(_get(after, "GetTitle")) != title:
                    self._reset_session_state()
                    return
            raise self._com_failed(
                f"Failed to close document: {title}",
                "Check SolidWorks for dialogs, or whether another document references this one",
                side_effect=SideEffect.NONE,
            )

        self._call(_fn)

    def active_document(self) -> DocInfo | None:
        def _fn() -> DocInfo | None:
            doc = self.sw.ActiveDoc
            if doc is None:
                return None
            return self._doc_info(doc)

        return self._call(_fn)

    def export_document(
        self,
        path: Path,
        fmt: str,
        *,
        step_ap: int | None = None,
        stl_quality: str | None = None,
    ) -> None:
        def _fn() -> None:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            try:
                doc_type = SW_DOC_TYPE_NAMES.get(int(_get(doc, "GetType")), "unknown")
            except Exception:
                doc_type = "unknown"
            ensure_doc_type(fmt, doc_type)
            validate_export_options(fmt, step_ap=step_ap, stl_quality=stl_quality)
            sw = self.sw
            prev_ap: int | None = None
            prev_q: int | None = None
            prev_dxf_map: bool | None = None
            prev_dxf_dont: bool | None = None
            res: Any = None
            try:
                if step_ap is not None:
                    prev_ap = int(sw.GetUserPreferenceIntegerValue(_SW_STEP_AP))
                    sw.SetUserPreferenceIntegerValue(_SW_STEP_AP, int(step_ap))
                if stl_quality is not None:
                    prev_q = int(sw.GetUserPreferenceIntegerValue(_SW_STL_QUALITY))
                    code = STL_QUALITY_CODES[str(stl_quality).strip().lower()]
                    sw.SetUserPreferenceIntegerValue(_SW_STL_QUALITY, code)
                if fmt == "dxf":
                    # Suppress map dialog: disable custom map, enable DontShowMap. Layer table from drawing LayerManager.
                    try:
                        prev_dxf_map = bool(sw.GetUserPreferenceToggle(_SW_DXF_MAPPING))
                        prev_dxf_dont = bool(sw.GetUserPreferenceToggle(_SW_DXF_DONT_SHOW_MAP))
                        sw.SetUserPreferenceToggle(_SW_DXF_MAPPING, False)
                        sw.SetUserPreferenceToggle(_SW_DXF_DONT_SHOW_MAP, True)
                    except Exception:
                        log.debug("Failed to set DXF mapping preferences: %s", traceback.format_exc())
                # SaveAs3 3rd arg 3 = silent + copy: export copy without changing current doc path/title.
                res = _get(doc, "SaveAs3", str(path), 0, 3)
            finally:
                try:
                    if prev_ap is not None:
                        sw.SetUserPreferenceIntegerValue(_SW_STEP_AP, prev_ap)
                except Exception:
                    log.debug("Failed to restore STEP AP: %s", traceback.format_exc())
                try:
                    if prev_q is not None:
                        sw.SetUserPreferenceIntegerValue(_SW_STL_QUALITY, prev_q)
                except Exception:
                    log.debug("Failed to restore STL quality: %s", traceback.format_exc())
                try:
                    if prev_dxf_map is not None:
                        sw.SetUserPreferenceToggle(_SW_DXF_MAPPING, prev_dxf_map)
                    if prev_dxf_dont is not None:
                        sw.SetUserPreferenceToggle(_SW_DXF_DONT_SHOW_MAP, prev_dxf_dont)
                except Exception:
                    log.debug("Failed to restore DXF mapping preferences: %s", traceback.format_exc())
            failed = res is False or res == "1" or (
                isinstance(res, int) and not isinstance(res, bool) and res != 0
            )
            if failed:
                raise fail(
                    "SAVE_FAILED",
                    f"{fmt} export failed (SaveAs3 returned {res!r}): {path}",
                    "Check path permissions, file locks, and that SolidWorks has no pending dialogs",
                )

        return self._call(_fn)

    def _drawing_bom_annotation(self, doc: Any) -> Any:
        """First BomFeat table annotation on active drawing, or None."""
        try:
            feat = _get(doc, "FirstFeature")
        except Exception:
            return None
        while feat is not None:
            try:
                tname = str(_get(feat, "GetTypeName2") or "")
            except Exception:
                tname = ""
            if tname == "BomFeat":
                try:
                    spec = _get(feat, "GetSpecificFeature2") or feat
                    anns = _get(spec, "GetTableAnnotations")
                    if anns is not None:
                        for ann in list(anns):
                            if ann is not None:
                                return ann
                except Exception:
                    log.debug("Failed to read BomFeat table: %s", traceback.format_exc())
            try:
                feat = _get(feat, "GetNextFeature")
            except Exception:
                break
        return None

    @staticmethod
    def _plain_table_text(raw: Any) -> str:
        """BOM cells/column titles often wrap in <FONT ...>; strip before column name matching."""
        text = str(raw or "")
        text = re.sub(r"<[^>]+>", "", text)
        return text.strip()

    def _table_cell(self, table: Any, row: int, col: int) -> str:
        for meth, args in (
            ("DisplayedText2", (row, col, False)),
            ("DisplayedText", (row, col)),
            ("Text2", (row, col, False)),
            ("Text", (row, col)),
        ):
            try:
                val = _get(table, meth, *args) if args else _get(table, meth)
                if val is not None:
                    return self._plain_table_text(val)
            except Exception:
                try:
                    fn = getattr(table, meth)
                    if callable(fn) and not hasattr(fn, "_oleobj_"):
                        return self._plain_table_text(fn(*args))
                except Exception:
                    continue
        return ""

    def _table_column_title(self, table: Any, col: int) -> str:
        for meth, args in (
            ("GetColumnTitle2", (col, True)),
            ("GetColumnTitle", (col,)),
        ):
            try:
                val = _get(table, meth, *args)
                if val is not None:
                    return self._plain_table_text(val)
            except Exception:
                try:
                    fn = getattr(table, meth)
                    if callable(fn) and not hasattr(fn, "_oleobj_"):
                        return self._plain_table_text(fn(*args))
                except Exception:
                    continue
        return ""

    def _activate_bom_configurations(self, ann: Any) -> None:
        """Chinese SW top-level BOM often inserts header-only; GetConfigurations + SetConfigurations enables all visible configs."""
        if self._bom_table_row_count(ann) > 1:
            return
        try:
            bf = _get(ann, "BomFeature")
        except Exception:
            bf = None
        if bf is None:
            return
        import pythoncom
        from win32com.client import VARIANT

        try:
            vis = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_VARIANT, [])
            names = bf.GetConfigurations(False, vis)
            name_list = [str(n) for n in list(names or ()) if n is not None]
            if not name_list:
                return
            visible = VARIANT(
                pythoncom.VT_ARRAY | pythoncom.VT_BOOL,
                tuple(True for _ in name_list),
            )
            name_arr = VARIANT(
                pythoncom.VT_ARRAY | pythoncom.VT_BSTR,
                tuple(name_list),
            )
            bf.SetConfigurations(True, visible, name_arr)
        except Exception:
            log.debug("BOM SetConfigurations failed: %s", traceback.format_exc())

    def _rows_from_bom_table(self, table: Any) -> list[BomRow]:
        try:
            nrows = int(_get(table, "RowCount") or 0)
            ncols = int(_get(table, "ColumnCount") or 0)
        except Exception:
            nrows, ncols = 0, 0
        if nrows <= 1 or ncols <= 0:
            return []
        titles = [self._table_column_title(table, c).lower() for c in range(ncols)]

        def _col(*keys: str) -> int | None:
            for i, t in enumerate(titles):
                if any(k in t for k in keys):
                    return i
            return None

        c_item = _col("item", "\u9879\u76ee", "\u5e8f\u53f7")
        c_pn = _col("part number", "\u96f6\u4ef6\u53f7", "\u4ee3\u53f7", "\u6587\u4ef6\u540d", "filename")
        if c_pn is None:
            c_pn = _col("\u8bf4\u660e", "description")
        c_qty = _col("qty", "quantity", "\u6570\u91cf")
        c_mat = _col("material", "\u6750\u6599")
        c_cfg = _col("configuration", "\u914d\u7f6e")
        rows: list[BomRow] = []
        for r in range(1, nrows):  # row 0 is header
            pn = self._table_cell(table, r, c_pn) if c_pn is not None else ""
            qty_s = self._table_cell(table, r, c_qty) if c_qty is not None else "1"
            if not pn and not qty_s:
                # Without qty column, still accept rows with part number
                if not pn:
                    continue
            try:
                qty = int(float(qty_s)) if qty_s else 1
            except ValueError:
                qty = 1
            item_s = self._table_cell(table, r, c_item) if c_item is not None else str(r)
            try:
                item = int(float(item_s)) if item_s else r
            except ValueError:
                item = r
            rows.append(
                BomRow(
                    item=item,
                    part_number=pn or f"row{r}",
                    qty=max(qty, 1),
                    material=self._table_cell(table, r, c_mat) if c_mat is not None else "",
                    configuration=self._table_cell(table, r, c_cfg) if c_cfg is not None else "",
                )
            )
        return rows

    def _bom_table_row_count(self, table: Any) -> int:
        for name in ("TotalRowCount", "RowCount"):
            try:
                n = int(_get(table, name) or 0)
                if n > 0:
                    return n
            except Exception:
                continue
        return 0

    def _insert_bom_on_view(self, view: Any, bom_type_id: int, template: str) -> Any:
        """Prefer IView.InsertBomTable6, fallback 4; then Extension (caller passes doc owning view)."""
        args6 = (
            False,
            0.15,
            0.20,
            _SW_BOM_ANCHOR_TOP_LEFT,
            bom_type_id,
            "",
            template,
            False,
            _SW_NUM_NONE,
            False,
            False,
            False,
        )
        args4 = args6[:10]
        for meth, args in (("InsertBomTable6", args6), ("InsertBomTable4", args4)):
            try:
                fn = getattr(view, meth)
            except Exception:
                continue
            if not (callable(fn) and not hasattr(fn, "_oleobj_")):
                continue
            try:
                ann = fn(*args)
            except Exception:
                log.debug("%s failed: %s", meth, traceback.format_exc())
                continue
            if ann is not None:
                return ann
        return None

    def get_bom(self) -> tuple[str, list[BomRow]]:
        def _fn() -> tuple[str, list[BomRow]]:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Open a part or assembly first")
            try:
                doc_type = int(_get(doc, "GetType"))
            except Exception:
                doc_type = 0
            if doc_type == SW_DOC_ASSEMBLY:
                entries: list[tuple[str, str, str, str]] = []
                for name, comp in self._assembly_component_objs(doc):
                    path = ""
                    try:
                        path = str(comp.GetPathName() or "")
                    except Exception:
                        try:
                            path = str(_get(comp, "GetPathName") or "")
                        except Exception:
                            path = ""
                    cfg = ""
                    try:
                        cfg = str(_get(comp, "ReferencedConfiguration") or "")
                    except Exception:
                        cfg = ""
                    material = ""
                    try:
                        model = comp.GetModelDoc2()
                        if model is not None:
                            material, _db = self._read_material(model)
                    except Exception:
                        log.debug("Failed to read component material: %s", traceback.format_exc())
                    entries.append((name, path, material, cfg))
                return "assembly", rollup_bom_rows(entries)
            if doc_type == SW_DOC_PART:
                try:
                    path = str(_get(doc, "GetPathName") or "")
                except Exception:
                    path = ""
                title = str(_get(doc, "GetTitle") or "Part")
                material, _db = self._read_material(doc)
                cfg = ""
                try:
                    mgr = _get(doc, "ConfigurationManager")
                    act = _get(mgr, "ActiveConfiguration") if mgr is not None else None
                    if act is not None:
                        cfg = str(_get(act, "Name") or "")
                except Exception:
                    cfg = ""
                return "part", rollup_bom_rows([(title, path or title, material, cfg)])
            if doc_type == SW_DOC_DRAWING:
                table = self._drawing_bom_annotation(doc)
                if table is None:
                    raise fail(
                        "FEATURE_NOT_FOUND",
                        "Drawing has no BOM table yet",
                        "Call create_drawing_view (assembly) first, then insert_bom",
                    )
                rows = self._rows_from_bom_table(table)
                if not rows:
                    raise fail(
                        "FEATURE_NOT_FOUND",
                        "Drawing BOM table is empty or could not be parsed",
                        "Confirm the view is from an assembly and insert_bom succeeded",
                    )
                return "drawing", rows
            raise fail(
                "FEATURE_NOT_FOUND",
                "Drawing has no BOM table yet",
                "Call create_drawing_view (assembly) first, then insert_bom",
            )

        return self._call(_fn)

    def insert_bom(self, bom_type: str = "top") -> int:
        def _fn() -> int:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Call new_drawing first")
            if bom_type not in BOM_TYPES:
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Unknown BOM type: {bom_type!r}",
                    f"bom_type: {', '.join(BOM_TYPES)}",
                )
            try:
                doc_type = int(_get(doc, "GetType"))
            except Exception:
                doc_type = 0
            if doc_type != SW_DOC_DRAWING:
                raise fail(
                    "INVALID_ARGUMENT",
                    "BOM tables can only be inserted on drawings",
                    "Call new_drawing and create_drawing_view (assembly) first",
                )
            view = self._first_model_view(doc)
            self._select_drawing_view(doc, view)
            template = self._resolve_bom_template()
            bom_id = int(BOM_TYPE_IDS[bom_type])
            ann = self._insert_bom_on_view(view, bom_id, template)
            if ann is None:
                # Extension fallback (often None on part drawings; assembly drawings prefer View)
                try:
                    ext = _get(doc, "Extension")
                    fn = ext.InsertBomTable4
                    if callable(fn) and not hasattr(fn, "_oleobj_"):
                        ann = fn(
                            template,
                            0.15,
                            0.20,
                            bom_id,
                            "",
                            False,
                            _SW_NUM_NONE,
                            False,
                            False,
                        )
                except Exception:
                    log.debug("Extension.InsertBomTable4 failed: %s", traceback.format_exc())
                    ann = None
            if ann is None:
                raise fail(
                    "FEATURE_NOT_FOUND",
                    "Failed to insert BOM table (InsertBomTable returned None)",
                    "Use an assembly drawing view; confirm .sldbomtbt template and no modal dialogs",
                )
            self._activate_bom_configurations(ann)
            n = self._bom_table_row_count(ann)
            if n <= 1:
                found = self._drawing_bom_annotation(doc)
                if found is not None:
                    self._activate_bom_configurations(found)
                    n = self._bom_table_row_count(found)
            if n <= 1:
                raise fail(
                    "FEATURE_NOT_FOUND",
                    "BOM table inserted but has no data rows (header only)",
                    "Confirm drawing view is from a saved assembly; try bom_type=parts or indented",
                )
            return n

        return self._call(_fn)

    def force_rebuild(self) -> RebuildOutcome:
        def _fn() -> RebuildOutcome:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            try:
                res = _get(doc, "ForceRebuild3", True)
                if res is False:
                    return RebuildOutcome(ok=False)
                return RebuildOutcome(ok=True)
            except Exception as exc:
                raise self._map_error(exc) from exc

        return self._call(_fn)
