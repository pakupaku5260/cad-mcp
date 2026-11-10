"""COM backend · drawings (views / section / annotations / balloons).

Dependencies (self, MRO):
- `_call`（STAThreadMixin）
- `_map_error`（STAThreadMixin）
- `_get`（_helpers）
- `_first_model_view` / `_select_drawing_view` / `_require_drawing_doc` (this module)

imports:
- `cadmcp.backend.protocol.constants`（DRAWING_VIEW_ALIASES）
- `cadmcp.backend.protocol.models` (none; returns str only)
- `cadmcp.backend.protocol.parsers`（drawing_view_key）
- `._constants`（SW_DOC_DRAWING）
- `._helpers`（_get）
"""
from __future__ import annotations

import logging
import traceback
from pathlib import Path
from typing import Any

from cadmcp.backend.protocol.constants import (
    DRAWING_PAPER_CODES,
    DRAWING_VIEW_ALIASES,
    GDT_FRAME_SYMBOLS,
    GDT_SYMBOLS,
    TITLE_BLOCK_DEFAULT_KEYS,
)
from cadmcp.backend.protocol.parsers import drawing_view_key
from cadmcp.errors import fail

from ._constants import SW_DOC_DRAWING
from ._helpers import _get

log = logging.getLogger(__name__)


class DrawingMixin:
    """Drawings (S4-2d-a: view creation + 3 helpers)."""

    def _init_state(self) -> None:
        self._drawing_datums: list[dict] = []
        self._drawing_gdts: list[dict] = []
        self._drawing_layers_known: list[str] = []

    def _reset_drawing_l3_state(self) -> None:
        self._drawing_datums = []
        self._drawing_gdts = []
        self._drawing_layers_known = []

    def create_drawing_view(self, model: Path, view: str) -> str:
        def _fn() -> str:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Call new_drawing first")
            try:
                doc_type = int(_get(doc, "GetType"))
            except Exception:
                doc_type = 0
            if doc_type != SW_DOC_DRAWING:
                raise fail("INVALID_ARGUMENT", "Active document is not a drawing", "Call new_drawing first")
            key = drawing_view_key(view)
            if not Path(model).is_file():
                raise fail("OPEN_FAILED", f"Model file not found: {model}", "save_document the part or assembly first")
            path = str(Path(model).resolve())
            created = None
            used = ""
            for name in DRAWING_VIEW_ALIASES[key]:
                try:
                    created = doc.CreateDrawViewFromModelView3(path, name, 0.12, 0.15, 0.0)
                except Exception:
                    log.debug("CreateDrawViewFromModelView3 %s: %s", name, traceback.format_exc())
                    created = None
                if created is not None:
                    used = name
                    break
            if created is None:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    f"Cannot create drawing view {key}",
                    "Confirm model is saved; try front/top/isometric",
                )
            return used or key

        return self._call(_fn)

    def _require_drawing_doc(self, doc: Any, hint: str) -> None:
        if doc is None:
            raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Call new_drawing first")
        try:
            doc_type = int(_get(doc, "GetType"))
        except Exception:
            doc_type = 0
        if doc_type != SW_DOC_DRAWING:
            raise fail("INVALID_ARGUMENT", "Active document is not a drawing", hint)

    def _first_model_view(self, doc: Any) -> Any:
        sheet = _get(doc, "GetFirstView")
        view = _get(sheet, "GetNextView") if sheet is not None else None
        if view is None:
            raise fail("INVALID_ARGUMENT", "Drawing has no model view yet", "create_drawing_view first")
        return view

    def _select_drawing_view(self, doc: Any, view: Any) -> str:
        import pythoncom
        from win32com.client import VARIANT

        name = str(_get(view, "Name") or "")
        callout = VARIANT(pythoncom.VT_DISPATCH, None)
        try:
            doc.Extension.SelectByID2(name, "DRAWINGVIEW", 0, 0, 0, False, 0, callout, 0)
        except Exception:
            log.debug("Select drawing view failed: %s", traceback.format_exc())
        try:
            doc.ActivateView(name)
        except Exception:
            log.debug("Activate drawing view failed: %s", traceback.format_exc())
        return name

    def _visible_drawing_edges(self, view: Any) -> list[Any]:
        """Visible drawing edges (GetVisibleComponents first, then GetVisibleEntities2(comp, Edge=1))."""
        edges: list[Any] = []
        comps: list[Any] = []
        try:
            raw_comps = _get(view, "GetVisibleComponents")
            if raw_comps is not None:
                comps = [c for c in list(raw_comps) if c is not None]
        except Exception:
            log.debug("GetVisibleComponents failed: %s", traceback.format_exc())
        # With no components, still try None (occasionally works on part drawings)
        targets: list[Any] = comps if comps else [None]
        for comp in targets:
            # Edge=1 only; Face cannot host DatumTag reliably
            raw = None
            for meth in ("GetVisibleEntities2", "GetVisibleEntities"):
                try:
                    raw = _get(view, meth, comp, 1)
                except Exception:
                    try:
                        raw = getattr(view, meth)(comp, 1)
                    except Exception:
                        log.debug("%s(comp, Edge) failed: %s", meth, traceback.format_exc())
                        continue
                if raw is not None:
                    break
            if raw is None:
                continue
            try:
                batch = [e for e in list(raw) if e is not None]
            except Exception:
                log.debug("Parse visible edges failed: %s", traceback.format_exc())
                batch = []
            edges.extend(batch)
            if edges:
                return edges
        return edges

    def _selection_count(self, doc: Any) -> int:
        try:
            sm = _get(doc, "SelectionManager")
            return int(_get(sm, "GetSelectedObjectCount2", -1) or 0)
        except Exception:
            return 0

    def _com_insert_annotation(self, doc: Any, name: str, *arg_variants: tuple) -> Any:
        """Call Insert*: SW2025 often exposes members as properties; calling () re-invokes CDispatch.

        Prefer `_get(doc, name)` (no-arg create); then parameterized variants.
        """
        try:
            obj = _get(doc, name)
            if obj is not None:
                return obj
        except Exception:
            log.debug("%s _get failed: %s", name, traceback.format_exc())
        for args in arg_variants:
            try:
                fn = getattr(doc, name)
                if callable(fn) and not hasattr(fn, "_oleobj_"):
                    obj = fn(*args)
                    if obj is not None:
                        return obj
            except Exception:
                log.debug("%s%s failed: %s", name, args, traceback.format_exc())
        return None

    def _preselect_drawing_edge(self, doc: Any, edge: int | None = None) -> bool:
        """Activate first model view and pick an edge (InsertDatumTag2 needs EDGE selection).

        Hardware probe: `view.SelectEntity(edge)` beats SelectByID2(EDGE).
        """
        import pythoncom
        from win32com.client import VARIANT

        try:
            view = self._first_model_view(doc)
        except Exception:
            log.debug("No model view; cannot preselect edge: %s", traceback.format_exc())
            return False
        self._select_drawing_view(doc, view)
        try:
            doc.ClearSelection2(True)
        except Exception:
            pass

        outline = []
        try:
            outline = list(_get(view, "GetOutline") or [])
        except Exception:
            outline = []
        cx = cy = 0.12
        if len(outline) >= 4:
            cx = (float(outline[0]) + float(outline[2])) / 2.0
            cy = (float(outline[1]) + float(outline[3])) / 2.0
            # Offset within bbox by edge index to avoid same hit point
            if edge is not None:
                span = max(1e-4, float(outline[2]) - float(outline[0]))
                cx = float(outline[0]) + span * (0.2 + 0.1 * (int(edge) % 5))

        # 1) Visible edge SelectEntity (probe_gdt_native: any_native=true)
        edges = self._visible_drawing_edges(view)
        if edges:
            idx = 0 if edge is None else int(edge)
            if 0 <= idx < len(edges):
                ent = edges[idx]
                try:
                    if bool(_get(view, "SelectEntity", ent, False)) and self._selection_count(doc) > 0:
                        return True
                except Exception:
                    log.debug("SelectEntity failed: %s", traceback.format_exc())
                if hasattr(self, "_select_entity"):
                    try:
                        if self._select_entity(doc, ent, mark=0) and self._selection_count(doc) > 0:
                            return True
                    except Exception:
                        log.debug("Select4 visible edge failed: %s", traceback.format_exc())

        callout = VARIANT(pythoncom.VT_DISPATCH, None)
        # 2) SelectByID2: FACE hits more often than EDGE; fallback
        for kind in ("FACE", "EDGE", "VERTEX"):
            try:
                if bool(doc.Extension.SelectByID2("", kind, cx, cy, 0.0, False, 0, callout, 0)):
                    if self._selection_count(doc) > 0:
                        return True
            except Exception:
                log.debug("SelectByID2 %s failed: %s", kind, traceback.format_exc())

        try:
            ok = doc.Extension.SelectByRay(cx, cy, 0.0, 0.0, 0.0, -1.0, 0.02, 1, False, 0, callout)
            if ok and self._selection_count(doc) > 0:
                return True
        except Exception:
            log.debug("SelectByRay edge pick failed: %s", traceback.format_exc())
        log.debug("No visible edges to preselect (selection_count=%d)", self._selection_count(doc))
        return self._selection_count(doc) > 0

    def create_section_view(
        self, label: str = "A", x_m: float = 0.22, y_m: float = 0.15, depth_m: float = 0.0,
    ) -> str:
        def _fn() -> str:
            import pythoncom
            from win32com.client import VARIANT

            doc = self.sw.ActiveDoc
            self._require_drawing_doc(doc, "Call new_drawing and create_drawing_view first")
            raw = str(label).strip()
            if not raw:
                raise fail("INVALID_ARGUMENT", "Section label cannot be empty", "Pass label, e.g.  A")
            view = self._first_model_view(doc)
            try:
                doc.ClearSelection2(True)
            except Exception:
                pass
            self._select_drawing_view(doc, view)
            line = None
            try:
                line = doc.SketchManager.CreateLine(-0.02, 0.0, 0.0, 0.02, 0.0, 0.0)
            except Exception as exc:
                log.debug("Section line failed: %s", traceback.format_exc())
                raise fail("FEATURE_CREATE_FAILED", "Cannot draw section line on view", "Confirm the view is active") from exc
            if line is None:
                raise fail("FEATURE_CREATE_FAILED", "Cannot draw section line on view", "Confirm the view is active")
            try:
                line.Select4(False, VARIANT(pythoncom.VT_DISPATCH, None))
            except Exception:
                log.debug("Select section line failed: %s", traceback.format_exc())
            try:
                sec = doc.CreateSectionViewAt5(
                    float(x_m), float(y_m), 0.0, raw, 0, None, float(depth_m or 0.0)
                )
            except Exception as exc:
                log.debug("CreateSectionViewAt5 failed: %s", traceback.format_exc())
                raise self._map_error(exc) from exc
            if sec is None:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Section view creation failed",
                    "create_drawing_view first, then create_section_view",
                )
            return str(_get(sec, "Name") or f"Section view {raw}-{raw}")

        return self._call(_fn)

    def insert_model_items(self) -> int:
        def _fn() -> int:
            doc = self.sw.ActiveDoc
            self._require_drawing_doc(doc, "Call new_drawing and create_drawing_view first")
            view = self._first_model_view(doc)
            self._select_drawing_view(doc, view)
            try:
                ok = doc.InsertModelAnnotations2(0, True, 3, False, True, True)
            except Exception as exc:
                log.debug("InsertModelAnnotations2 failed: %s", traceback.format_exc())
                raise self._map_error(exc) from exc
            if ok is False:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Failed to import model dimensions",
                    "Dimension the part first, then create_drawing_view",
                )
            try:
                return int(_get(view, "GetDimensionCount2") or 0)
            except Exception:
                anns = list(_get(view, "GetAnnotations") or [])
                return len(anns)

        return self._call(_fn)

    def insert_balloons(self) -> int:
        def _fn() -> int:
            doc = self.sw.ActiveDoc
            self._require_drawing_doc(doc, "Call new_drawing and create_drawing_view first")
            view = self._first_model_view(doc)
            self._select_drawing_view(doc, view)
            try:
                opts = doc.CreateAutoBalloonOptions
                opts.Layout = 1
                opts.Style = 1
                opts.Size = 2
                opts.ItemNumberStart = 1
                opts.ItemNumberIncrement = 1
                opts.IgnoreMultiple = False
                res = doc.AutoBalloon5(opts)
            except Exception as exc:
                log.debug("AutoBalloon5 failed: %s", traceback.format_exc())
                raise self._map_error(exc) from exc
            if res is None:
                anns = list(_get(view, "GetAnnotations") or [])
                return len(anns)
            try:
                return len(list(res))
            except Exception:
                return 1

        return self._call(_fn)

    def set_sheet_props(self, paper: str, scale: tuple[float, float]) -> dict:
        """risk: unverified — Sheet.SetProperties paper codes vary by version; returns requested values on failure."""

        def _fn() -> dict:
            doc = self.sw.ActiveDoc
            self._require_drawing_doc(doc, "Call new_drawing first")
            sheet = _get(doc, "GetCurrentSheet")
            if sheet is None:
                raise fail("FEATURE_CREATE_FAILED", "Cannot get current sheet", "Confirm a drawing is open")
            paper_u = str(paper).strip().upper()
            n, d = float(scale[0]), float(scale[1])
            # swDwgPaperA4=12 etc.; on failure record request only
            code = DRAWING_PAPER_CODES.get(paper_u, 12)
            try:
                sheet.SetProperties(code, 12, False, False, False, False, n, d)
            except Exception:
                log.debug("SetProperties failed: %s", traceback.format_exc())
                try:
                    sheet.SetScale(n, d, False, False)
                except Exception:
                    log.debug("SetScale failed: %s", traceback.format_exc())
            return {"paper": paper_u, "scale": [n, d]}

        return self._call(_fn)

    def add_drawing_layer(self, name: str, color: int = 255) -> dict:
        def _fn() -> dict:
            doc = self.sw.ActiveDoc
            self._require_drawing_doc(doc, "Call new_drawing first")
            raw = str(name).strip()
            if not raw:
                raise fail("INVALID_ARGUMENT", "Layer name cannot be empty", "Pass name, e.g.  VISIBLE")
            if not isinstance(color, int) or isinstance(color, bool):
                raise fail("INVALID_ARGUMENT", "color must be an integer color value", "e.g. 255 (red) or 65280 (green)")
            lm = _get(doc, "GetLayerManager")
            if lm is None:
                raise fail("FEATURE_CREATE_FAILED", "Cannot get layer manager", "Confirm active document is a drawing")
            try:
                existing = _get(lm, "GetLayer", raw)
            except Exception:
                existing = None
            if existing is not None:
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Layer already exists: {raw}",
                    "Use another name, or set_drawing_layer for current layer",
                    requested=raw,
                )
            try:
                res = _get(lm, "AddLayer", raw, "", int(color), 0, 0)
            except Exception as exc:
                log.debug("AddLayer failed: %s", traceback.format_exc())
                raise self._map_error(exc) from exc
            if res in (0, False):
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    f"AddLayer failed：{raw}",
                    "Retry with a valid layer name",
                    requested=raw,
                )
            if raw not in self._drawing_layers_known:
                self._drawing_layers_known.append(raw)
            return {"name": raw, "color": int(color)}

        return self._call(_fn)

    def set_drawing_layer(self, name: str) -> str:
        def _fn() -> str:
            doc = self.sw.ActiveDoc
            self._require_drawing_doc(doc, "Call new_drawing first")
            raw = str(name).strip()
            if not raw:
                raise fail("INVALID_ARGUMENT", "Layer name cannot be empty", "Pass name, or add_drawing_layer first")
            lm = _get(doc, "GetLayerManager")
            if lm is None:
                raise fail("FEATURE_CREATE_FAILED", "Cannot get layer manager", "Confirm active document is a drawing")
            try:
                layer = _get(lm, "GetLayer", raw)
            except Exception:
                layer = None
            if layer is None:
                raise fail(
                    "FEATURE_NOT_FOUND",
                    f"Layer not found: {raw}",
                    "add_drawing_layer first, or check list_drawing_layers",
                    requested=raw,
                )
            try:
                ok = _get(lm, "SetCurrentLayer", raw)
            except Exception as exc:
                log.debug("SetCurrentLayer failed: %s", traceback.format_exc())
                raise self._map_error(exc) from exc
            if ok in (0, False):
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    f"Cannot switch to layer: {raw}",
                    "Confirm layer was not deleted",
                    requested=raw,
                )
            if raw not in self._drawing_layers_known:
                self._drawing_layers_known.append(raw)
            return raw

        return self._call(_fn)

    def list_drawing_layers(self) -> dict:
        def _fn() -> dict:
            doc = self.sw.ActiveDoc
            self._require_drawing_doc(doc, "Call new_drawing first")
            lm = _get(doc, "GetLayerManager")
            if lm is None:
                raise fail("FEATURE_CREATE_FAILED", "Cannot get layer manager", "Confirm active document is a drawing")
            try:
                count = int(_get(lm, "GetCount") or 0)
            except Exception:
                count = 0
            current = None
            try:
                cur = _get(lm, "GetCurrentLayer")
                current = None if cur is None else str(cur)
            except Exception:
                current = None
            known: list[str] = []
            for name in self._drawing_layers_known:
                try:
                    if _get(lm, "GetLayer", name) is not None:
                        known.append(name)
                except Exception:
                    continue
            if current and current not in known:
                known = [current, *known]
            return {"count": count, "current": current, "layers": known}

        return self._call(_fn)

    def _sheet_names(self, doc: Any) -> list[str]:
        names: list[str] = []
        try:
            raw = _get(doc, "GetSheetNames")
            if raw is not None:
                names = [str(n) for n in list(raw)]
        except Exception:
            log.debug("GetSheetNames failed: %s", traceback.format_exc())
        if names:
            return names
        try:
            count = int(_get(doc, "GetSheetCount") or 0)
        except Exception:
            count = 0
        # Fallback: current sheet
        try:
            sh = _get(doc, "GetCurrentSheet")
            cur = str(_get(sh, "GetName") or "") if sh is not None else ""
            if cur:
                names.append(cur)
        except Exception:
            pass
        if not names and count > 0:
            names = [f"Sheet{i}" for i in range(1, count + 1)]
        return names

    def create_detail_view(
        self, label: str = "B", x_m: float = 0.0, y_m: float = 0.0, radius_m: float = 0.01
    ) -> str:
        """Detail view: circle on active view, then CreateDetailViewAt4 (2025 typelib 12 params)."""

        def _fn() -> str:
            doc = self.sw.ActiveDoc
            self._require_drawing_doc(doc, "Call new_drawing and create_drawing_view first")
            if float(radius_m) <= 0:
                raise fail("INVALID_ARGUMENT", "detail radius must be positive", "Pass radius > 0")
            view = self._first_model_view(doc)
            self._select_drawing_view(doc, view)
            raw = str(label).strip() or "B"
            cx = float(x_m)
            cy = float(y_m)
            r = float(radius_m)
            # Same as section: circle on active view; CreateDetailViewAt* consumes sketch circle
            try:
                circ = doc.SketchManager.CreateCircle(cx, cy, 0.0, cx + r, cy, 0.0)
            except Exception as exc:
                log.debug("detail circle failed: %s", traceback.format_exc())
                raise fail("FEATURE_CREATE_FAILED", "Cannot draw detail circle on view", "Confirm the view is active") from exc
            if circ is None:
                raise fail("FEATURE_CREATE_FAILED", "Cannot draw detail circle on view", "Confirm the view is active")
            # Place detail view beside circle to avoid parent overlap
            vx, vy = cx + max(0.05, 2.5 * r), cy + max(0.03, 1.5 * r)
            created = None
            # Style=0 swDetViewSTANDARD; Showtype=1 swDetCircleCIRCLE; Scale 1:1
            try:
                created = doc.CreateDetailViewAt4(
                    float(vx), float(vy), 0.0, 0, 1.0, 1.0, raw, 1, True, False, False, 5
                )
            except Exception:
                log.debug("CreateDetailViewAt4 failed: %s", traceback.format_exc())
                created = None
            if created is None:
                try:
                    created = doc.CreateDetailViewAt3(
                        float(vx), float(vy), 0.0, 0, 1.0, 1.0, raw, 1, True
                    )
                except Exception:
                    log.debug("CreateDetailViewAt3 failed: %s", traceback.format_exc())
                    created = None
            if created is None:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Detail view creation failed",
                    "Confirm model view exists and parent is selected",
                )
            try:
                return str(_get(created, "Name") or f"detail_{raw}")
            except Exception:
                return f"detail_{raw}"

        return self._call(_fn)

    def apply_drawing_tolerances(self, tolerances: list[dict]) -> int:
        """risk: unverified — write IDimension tolerances when possible; else count requested items only."""

        def _fn() -> int:
            doc = self.sw.ActiveDoc
            self._require_drawing_doc(doc, "Call new_drawing first")
            applied = 0
            for item in tolerances:
                name = str(item.get("dimension") or "").strip()
                if not name:
                    continue
                try:
                    disp = doc.Extension.GetDisplayDimensionByName2(name, 1)
                except Exception:
                    disp = None
                if disp is None:
                    continue
                try:
                    dim = _get(disp, "GetDimension2", 0) or _get(disp, "GetDimension")
                    if dim is None:
                        continue
                    tol_type = int(item.get("type", 1) or 1)
                    _get(dim, "SetToleranceType2", tol_type, True)
                    vals = item.get("values") or []
                    if isinstance(vals, list) and len(vals) >= 2:
                        _get(dim, "SetToleranceValues", float(vals[0]), float(vals[1]))
                    applied += 1
                except Exception:
                    log.debug("Write tolerance failed %s: %s", name, traceback.format_exc())
            return applied

        return self._call(_fn)

    def inspect_drawing(self) -> dict:
        def _fn() -> dict:
            doc = self.sw.ActiveDoc
            self._require_drawing_doc(doc, "Call new_drawing first")
            views: list[str] = []
            sheet = _get(doc, "GetFirstView")
            cur = _get(sheet, "GetNextView") if sheet is not None else None
            ann_count = 0
            while cur is not None:
                try:
                    views.append(str(_get(cur, "Name") or ""))
                except Exception:
                    views.append("")
                try:
                    ann_count += int(_get(cur, "GetDimensionCount2") or 0)
                except Exception:
                    try:
                        ann_count += len(list(_get(cur, "GetAnnotations") or []))
                    except Exception:
                        pass
                cur = _get(cur, "GetNextView")
            paper = "A4"
            scale = [1.0, 1.0]
            active_name = ""
            try:
                sh = _get(doc, "GetCurrentSheet")
                if sh is not None:
                    active_name = str(_get(sh, "GetName") or "")
                    props = _get(sh, "GetProperties")
                    if props is not None and len(list(props)) >= 8:
                        p = list(props)
                        scale = [float(p[6]), float(p[7])]
            except Exception:
                log.debug("Read sheet size failed: %s", traceback.format_exc())
            sheet_names = self._sheet_names(doc)
            sheets = [{"name": n, "paper": None, "scale": None, "view_count": None} for n in sheet_names]
            title = self._read_title_block(doc, list(TITLE_BLOCK_DEFAULT_KEYS))
            missing = [k for k, v in title.items() if not v]
            datums = list(getattr(self, "_drawing_datums", []) or [])
            gdts = list(getattr(self, "_drawing_gdts", []) or [])
            # If session empty (e.g. opened drawing), scan annotations
            if not datums and not gdts:
                scanned_d, scanned_g = self._scan_gdt_annotations(doc)
                if scanned_d:
                    datums = scanned_d
                if scanned_g:
                    gdts = scanned_g
            return {
                "view_count": len(views),
                "views": views,
                "annotation_count": ann_count,
                "paper": paper,
                "scale": scale,
                "tolerances": [],
                "missing_tolerances": [],
                "untoleranced_dimensions": [],
                "sheet_count": len(sheet_names),
                "active_sheet": active_name or (sheet_names[0] if sheet_names else ""),
                "sheets": sheets,
                "title_block": title,
                "missing_title_fields": missing,
                "datum_count": len(datums),
                "datums": datums,
                "gdt_count": len(gdts),
                "gdts": gdts,
            }

        return self._call(_fn)

    def _scan_gdt_annotations(self, doc: Any) -> tuple[list[dict], list[dict]]:
        """Best-effort datum/GD&T from annotations (including Note fallback)."""
        datums: list[dict] = []
        gdts: list[dict] = []
        try:
            ann = _get(doc, "GetFirstAnnotation2") or _get(doc, "GetFirstAnnotation")
        except Exception:
            ann = None
        seen = 0
        while ann is not None and seen < 500:
            seen += 1
            kind = ""
            text = ""
            try:
                kind = str(_get(ann, "GetType") or _get(ann, "GetType2") or "")
            except Exception:
                kind = ""
            try:
                text = str(_get(ann, "GetText") or _get(ann, "GetName") or "")
            except Exception:
                text = ""
            low = text.upper()
            # swAnnotationType: DatumTag/GTol codes vary; also inspect text
            if "DATUM" in low or "\u57fa\u51c6" in text or "DATUMTAG" in str(kind).upper():
                datums.append({"name": text or f"datum_scan_{len(datums)+1}", "mode": "scanned", "raw_type": kind})
            elif "GDT" in low or "GTOL" in str(kind).upper() or "TOLERANCE" in str(kind).upper():
                gdts.append({"name": text or f"gdt_scan_{len(gdts)+1}", "mode": "scanned", "raw_type": kind})
            try:
                ann = _get(ann, "GetNext3") or _get(ann, "GetNext2") or _get(ann, "GetNext")
            except Exception:
                break
        return datums, gdts

    def add_drawing_sheet(self, name: str, paper: str, scale: tuple[float, float]) -> dict:
        """risk: unverified — NewSheet4 params depend on template; fallback NewSheet3."""

        def _fn() -> dict:
            doc = self.sw.ActiveDoc
            self._require_drawing_doc(doc, "Call new_drawing first")
            raw = str(name).strip()
            if not raw:
                raise fail("INVALID_ARGUMENT", "Sheet name cannot be empty", "Pass name, e.g.  Sheet2")
            if raw in self._sheet_names(doc):
                raise fail("INVALID_ARGUMENT", f"Sheet already exists: {raw}", "Use another name")
            paper_u = str(paper).strip().upper()
            n, d = float(scale[0]), float(scale[1])
            code = DRAWING_PAPER_CODES.get(paper_u, 12)
            # swDwgTemplateNONE=2; width/height may be 0 for standard paper
            created = False
            try:
                created = bool(
                    doc.NewSheet4(raw, code, 2, n, d, True, "", 0.0, 0.0, "", 0.0, 0.0, 0.0, 0.0, 0, 0)
                )
            except Exception:
                log.debug("NewSheet4 failed: %s", traceback.format_exc())
                created = False
            if not created:
                try:
                    created = bool(doc.NewSheet3(raw, code, 2, n, d, True, "", 0.0, 0.0, ""))
                except Exception as exc:
                    log.debug("NewSheet3 failed: %s", traceback.format_exc())
                    raise fail(
                        "FEATURE_CREATE_FAILED",
                        f"Cannot create sheet {raw}",
                        "Confirm a drawing is open and the sheet name is free",
                    ) from exc
            if not created:
                raise fail("FEATURE_CREATE_FAILED", f"Cannot create sheet {raw}", "Confirm NewSheet* is available")
            try:
                doc.ActivateSheet(raw)
            except Exception:
                log.debug("ActivateSheet failed: %s", traceback.format_exc())
            sheet = _get(doc, "GetCurrentSheet")
            if sheet is not None:
                try:
                    sheet.SetProperties(code, 12, False, False, False, False, n, d)
                except Exception:
                    log.debug("New sheet SetProperties failed: %s", traceback.format_exc())
                    try:
                        sheet.SetScale(n, d, False, False)
                    except Exception:
                        log.debug("New sheet SetScale failed: %s", traceback.format_exc())
            return {"name": raw, "paper": paper_u, "scale": [n, d]}

        return self._call(_fn)

    def activate_drawing_sheet(self, name: str) -> str:
        def _fn() -> str:
            doc = self.sw.ActiveDoc
            self._require_drawing_doc(doc, "Call new_drawing first")
            raw = str(name).strip()
            names = self._sheet_names(doc)
            if raw not in names:
                raise fail(
                    "FEATURE_NOT_FOUND",
                    f"Sheet not found: {raw}",
                    f"Existing: {', '.join(names) or '(none)'}",
                )
            try:
                ok = doc.ActivateSheet(raw)
            except Exception as exc:
                raise fail("FEATURE_CREATE_FAILED", f"Cannot activate sheet {raw}", "Check sheet name") from exc
            if ok is False:
                raise fail("FEATURE_CREATE_FAILED", f"Cannot activate sheet {raw}", "Check sheet name")
            return raw

        return self._call(_fn)

    def list_drawing_sheets(self) -> list[str]:
        def _fn() -> list[str]:
            doc = self.sw.ActiveDoc
            self._require_drawing_doc(doc, "Call new_drawing first")
            return self._sheet_names(doc)

        return self._call(_fn)

    def _cpm(self, doc: Any) -> Any:
        try:
            return doc.Extension.CustomPropertyManager("")
        except Exception as exc:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "Cannot get CustomPropertyManager",
                "Confirm active document is a drawing",
            ) from exc

    def _read_title_block(self, doc: Any, keys: list[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        cpm = self._cpm(doc)
        for key in keys:
            val = ""
            try:
                # Get6/Get5 out-params vary; prefer Get
                got = _get(cpm, "Get", key)
                if isinstance(got, (list, tuple)) and got:
                    val = str(got[0] if not isinstance(got[0], (list, tuple)) else got[-1] or "")
                elif got is not None:
                    val = str(got)
            except Exception:
                try:
                    # Get5(...) — skip when late binding unstable
                    res = cpm.Get5(key, False, "", "")
                    if isinstance(res, (list, tuple)) and len(res) >= 3:
                        val = str(res[2] or res[1] or "")
                except Exception:
                    log.debug("Read property %s failed: %s", key, traceback.format_exc())
            out[key] = val
        return out

    def set_title_block(self, props: dict[str, str]) -> dict:
        """risk: unverified — depends on template linking matching custom properties."""

        def _fn() -> dict:
            doc = self.sw.ActiveDoc
            self._require_drawing_doc(doc, "Call new_drawing first")
            cpm = self._cpm(doc)
            written: dict[str, str] = {}
            for k, v in props.items():
                key = str(k).strip()
                if not key:
                    continue
                text = str(v)
                ok = False
                try:
                    # Add3(FieldName, FieldType=swCustomInfoText=30, FieldValue, DeleteExisting)
                    cpm.Add3(key, 30, text, 1)
                    ok = True
                except Exception:
                    log.debug("Add3 %s failed: %s", key, traceback.format_exc())
                if not ok:
                    try:
                        cpm.Set2(key, text)
                        ok = True
                    except Exception:
                        try:
                            cpm.Set(key, text)
                            ok = True
                        except Exception:
                            log.debug("Set property %s failed: %s", key, traceback.format_exc())
                if ok:
                    written[key] = text
            if not written and props:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Failed to write any title block properties",
                    "Confirm template custom props are writable, or probe CustomPropertyManager",
                )
            return written

        return self._call(_fn)

    def get_title_block(self, keys: list[str] | None = None) -> dict:
        def _fn() -> dict:
            doc = self.sw.ActiveDoc
            self._require_drawing_doc(doc, "Call new_drawing first")
            want = list(keys) if keys else list(TITLE_BLOCK_DEFAULT_KEYS)
            return self._read_title_block(doc, want)

        return self._call(_fn)

    def insert_datum(
        self, label: str, x_m: float = 0.1, y_m: float = 0.1, edge: int | None = None
    ) -> str:
        """InsertDatumTag2 (_get dual path); preselect visible edge via SelectEntity. Note fallback on failure."""

        def _fn() -> str:
            doc = self.sw.ActiveDoc
            self._require_drawing_doc(doc, "Call new_drawing first")
            raw = str(label).strip()
            if not raw:
                raise fail("INVALID_ARGUMENT", "Datum label cannot be empty", "Pass label, e.g.  A")
            selected = self._preselect_drawing_edge(doc, edge)
            tag = self._com_insert_annotation(doc, "InsertDatumTag2", (True,), (False,))
            if tag is not None:
                try:
                    _get(tag, "SetLabel", raw)
                except Exception:
                    try:
                        tag.SetLabel2(raw)
                    except Exception:
                        log.debug("SetLabel failed: %s", traceback.format_exc())
                try:
                    ann = _get(tag, "GetAnnotation")
                    if ann is not None:
                        _get(ann, "SetPosition", float(x_m), float(y_m), 0.0)
                except Exception:
                    log.debug("Datum placement failed: %s", traceback.format_exc())
                name = f"datum_{raw}"
                self._drawing_datums.append(
                    {
                        "name": name,
                        "label": raw,
                        "mode": "native",
                        "edge_selected": selected,
                        "x_m": float(x_m),
                        "y_m": float(y_m),
                    }
                )
                return name
            # Fallback: text note (honest fallback; name still datum_)
            try:
                note = doc.InsertNote(f"DATUM {raw}")
                if note is not None:
                    ann = _get(note, "GetAnnotation") or note
                    try:
                        _get(ann, "SetPosition2", float(x_m), float(y_m), 0.0)
                    except Exception:
                        _get(ann, "SetPosition", float(x_m), float(y_m), 0.0)
                    name = f"datum_{raw}"
                    self._drawing_datums.append(
                        {
                            "name": name,
                            "label": raw,
                            "mode": "note",
                            "edge_selected": selected,
                            "x_m": float(x_m),
                            "y_m": float(y_m),
                        }
                    )
                    return name
            except Exception as exc:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    f"Cannot insert datum {raw}",
                    "Confirm model view has visible edges; or pass edge index",
                ) from exc
            raise fail(
                "FEATURE_CREATE_FAILED",
                f"Cannot insert datum {raw}",
                "Confirm model view has visible edges; or pass edge index",
            )

        return self._call(_fn)

    def insert_gdt(
        self,
        symbol: str,
        tolerance: str,
        datums: tuple[str, ...] = (),
        x_m: float = 0.1,
        y_m: float = 0.1,
        edge: int | None = None,
    ) -> str:
        """InsertGtol (_get dual path) + SetFrame*; preselect visible edge. Note fallback on failure."""

        def _fn() -> str:
            doc = self.sw.ActiveDoc
            self._require_drawing_doc(doc, "Call new_drawing first")
            sym = str(symbol).strip().lower()
            if sym not in GDT_SYMBOLS:
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Unknown GD&T symbol: {symbol!r}",
                    f"Options: {', '.join(GDT_SYMBOLS)}",
                )
            tol = str(tolerance).strip()
            if not tol:
                raise fail("INVALID_ARGUMENT", "Tolerance value cannot be empty", "Pass tolerance, e.g.  0.1")
            refs = [str(d).strip() for d in datums if str(d).strip()]
            frame_sym = GDT_FRAME_SYMBOLS.get(sym, "<POS>")
            selected = self._preselect_drawing_edge(doc, edge)
            gtol = self._com_insert_annotation(doc, "InsertGtol")
            if gtol is not None:
                try:
                    # SetFrameSymbols2(Frame#, GCS, ...)
                    _get(gtol, "SetFrameSymbols2", 1, frame_sym, False, "", False, "", False, "", False)
                except Exception:
                    try:
                        _get(gtol, "SetFrameSymbols", 1, frame_sym, "", "", "")
                    except Exception:
                        log.debug("SetFrameSymbols failed: %s", traceback.format_exc())
                d1 = refs[0] if len(refs) > 0 else ""
                d2 = refs[1] if len(refs) > 1 else ""
                d3 = refs[2] if len(refs) > 2 else ""
                try:
                    _get(gtol, "SetFrameValues", 1, tol, "", d1, d2, d3)
                except Exception:
                    log.debug("SetFrameValues failed: %s", traceback.format_exc())
                try:
                    ann = _get(gtol, "GetAnnotation")
                    if ann is not None:
                        _get(ann, "SetPosition", float(x_m), float(y_m), 0.0)
                except Exception:
                    log.debug("GDT placement failed: %s", traceback.format_exc())
                name = f"gdt_{sym}"
                self._drawing_gdts.append(
                    {
                        "name": name,
                        "symbol": sym,
                        "tolerance": tol,
                        "datums": list(refs),
                        "mode": "native",
                        "edge_selected": selected,
                        "x_m": float(x_m),
                        "y_m": float(y_m),
                    }
                )
                return name
            text = f"GDT {sym} {tol}" + (f" | {' '.join(refs)}" if refs else "")
            try:
                note = doc.InsertNote(text)
                if note is not None:
                    ann = _get(note, "GetAnnotation") or note
                    try:
                        _get(ann, "SetPosition2", float(x_m), float(y_m), 0.0)
                    except Exception:
                        _get(ann, "SetPosition", float(x_m), float(y_m), 0.0)
                    name = f"gdt_{sym}"
                    self._drawing_gdts.append(
                        {
                            "name": name,
                            "symbol": sym,
                            "tolerance": tol,
                            "datums": list(refs),
                            "mode": "note",
                            "edge_selected": selected,
                            "x_m": float(x_m),
                            "y_m": float(y_m),
                        }
                    )
                    return name
            except Exception as exc:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    f"Cannot insert GD&T {sym}",
                    "Confirm model view has visible edges; or pass edge index",
                ) from exc
            raise fail(
                "FEATURE_CREATE_FAILED",
                f"Cannot insert GD&T {sym}",
                "Confirm model view has visible edges; or pass edge index",
            )

        return self._call(_fn)
