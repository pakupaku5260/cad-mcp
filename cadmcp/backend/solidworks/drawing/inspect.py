"""Drawing inspection: read-only view/sheet/annotation summary for `inspect_drawing`.

Does not modify the document or create geometry.
Boundary: reads via `_get` inside `self._call`; session datum/GD&T lists may be replaced by a scan.
"""

from __future__ import annotations

import logging
import traceback
from typing import Any

from cadmcp.backend.drawing_checklist import compute_tolerance_gaps, model_doc_type_from_path
from cadmcp.backend.protocol.constants import (
    TITLE_BLOCK_DEFAULT_KEYS,
    WELD_ANNOTATION_TYPE,
    WELD_TEXT_ABOVE_SYMBOL,
    WELD_TEXT_BELOW_SYMBOL,
    WELD_TEXT_PROCESS,
)
from cadmcp.errors import fail

from .._helpers import _get

log = logging.getLogger(__name__)

# swTolType_NONE ≈ 0 on common SW builds (best-effort; probe may refine).
_SW_TOL_NONE = 0


class DrawingInspectMixin:
    """Read-only drawing inspection and annotation scanning."""

    def inspect_drawing(self) -> dict:
        def _fn() -> dict:
            doc = self.sw.ActiveDoc
            self._require_drawing_doc(doc, "Call new_drawing first")
            views: list[str] = []
            sheet = _get(doc, "GetFirstView")
            cur = _get(sheet, "GetNextView") if sheet is not None else None
            ann_count = 0
            first_view = None
            while cur is not None:
                if first_view is None:
                    first_view = cur
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
            welds = list(getattr(self, "_drawing_welds", []) or [])
            # If session empty (e.g. opened drawing), scan annotations
            if not datums and not gdts:
                scanned_d, scanned_g = self._scan_gdt_annotations(doc)
                if scanned_d:
                    datums = scanned_d
                if scanned_g:
                    gdts = scanned_g
            if not welds:
                welds = self._scan_weld_annotations(doc)

            model_path = self._drawing_model_path(doc, first_view)
            dim_names, toleranced = self._scan_display_dimensions(doc)
            session_applied = list(getattr(self, "_drawing_tol_applied", []) or [])
            session_failed = list(getattr(self, "_drawing_tol_failed", []) or [])
            for row in session_applied:
                n = str(row.get("dimension") or "").strip()
                if n:
                    toleranced.add(n)
                    if n not in dim_names:
                        dim_names.append(n)
            _, missing_tol, untoleranced = compute_tolerance_gaps(
                dimension_names=dim_names,
                toleranced_names=toleranced,
                failed_requests=session_failed,
            )
            tol_rows = session_applied if session_applied else [
                {"dimension": n} for n in sorted(toleranced)
            ]
            return {
                "view_count": len(views),
                "views": views,
                "annotation_count": ann_count,
                "paper": paper,
                "scale": scale,
                "tolerances": tol_rows,
                "missing_tolerances": missing_tol,
                "untoleranced_dimensions": untoleranced,
                "dimensions": dim_names,
                "model_path": model_path,
                "model_doc_type": model_doc_type_from_path(model_path),
                "sheet_count": len(sheet_names),
                "active_sheet": active_name or (sheet_names[0] if sheet_names else ""),
                "sheets": sheets,
                "title_block": title,
                "missing_title_fields": missing,
                "datum_count": len(datums),
                "datums": datums,
                "gdt_count": len(gdts),
                "gdts": gdts,
                "weld_count": len(welds),
                "welds": welds,
            }

        return self._call(_fn)

    def _drawing_model_path(self, doc: Any, first_view: Any) -> str:
        for view in (first_view,):
            if view is None:
                continue
            for meth in ("GetReferencedModelName", "GetReferencedDocument"):
                try:
                    raw = _get(view, meth)
                except Exception:
                    raw = None
                if raw is None:
                    continue
                if isinstance(raw, str) and raw.strip():
                    return str(raw).strip()
                try:
                    path = str(_get(raw, "GetPathName") or "")
                    if path:
                        return path
                except Exception:
                    pass
        try:
            # Drawing may expose referenced docs via Extension
            ext = _get(doc, "Extension")
            deps = _get(ext, "GetDependencies", True, True, False) if ext is not None else None
            if deps:
                for d in list(deps):
                    s = str(d or "")
                    if s.lower().endswith((".sldprt", ".sldasm")):
                        return s
        except Exception:
            log.debug("Resolve drawing model path failed: %s", traceback.format_exc())
        return ""

    def _scan_display_dimensions(self, doc: Any) -> tuple[list[str], set[str]]:
        """Best-effort: enumerate display dims and which already have a tolerance type."""
        names: list[str] = []
        toleranced: set[str] = set()
        try:
            disp = _get(doc, "GetFirstDisplayDimension2") or _get(doc, "GetFirstDisplayDimension")
        except Exception:
            disp = None
        seen = 0
        while disp is not None and seen < 500:
            seen += 1
            name = ""
            try:
                name = str(_get(disp, "GetNameForSelection") or _get(disp, "GetName") or "")
            except Exception:
                name = ""
            if not name:
                try:
                    dim = _get(disp, "GetDimension2", 0) or _get(disp, "GetDimension")
                    name = str(_get(dim, "FullName") or _get(dim, "Name") or "") if dim is not None else ""
                except Exception:
                    name = ""
            name = name.strip()
            if name and name not in names:
                names.append(name)
            tol_type = None
            try:
                dim = _get(disp, "GetDimension2", 0) or _get(disp, "GetDimension")
                if dim is not None:
                    tol_type = _get(dim, "GetToleranceType2") or _get(dim, "ToleranceType")
            except Exception:
                tol_type = None
            try:
                if name and tol_type is not None and int(tol_type) != _SW_TOL_NONE:
                    toleranced.add(name)
            except (TypeError, ValueError):
                pass
            try:
                disp = _get(disp, "GetNext2") or _get(disp, "GetNext") or _get(disp, "GetNext5")
            except Exception:
                break
        return names, toleranced

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

    def _iter_drawing_model_views(self, doc: Any) -> list[Any]:
        views: list[Any] = []
        try:
            cur = _get(doc, "GetFirstView")
            cur = _get(cur, "GetNextView") if cur is not None else None
        except Exception:
            cur = None
        while cur is not None:
            views.append(cur)
            try:
                cur = _get(cur, "GetNextView")
            except Exception:
                break
        return views

    def _collect_type8_annotations(self, doc: Any) -> list[tuple[Any, str]]:
        """Return [(annotation, view_name), ...] for GetType==WELD_ANNOTATION_TYPE."""
        found: list[tuple[Any, str]] = []
        for view in self._iter_drawing_model_views(doc):
            try:
                vname = str(_get(view, "Name") or "")
            except Exception:
                vname = ""
            try:
                raw = _get(view, "GetAnnotations")
                anns = [a for a in list(raw or []) if a is not None]
            except Exception:
                continue
            for ann in anns:
                if isinstance(ann, (tuple, list, int, float, str, bool)):
                    continue
                try:
                    kind = _get(ann, "GetType")
                except Exception:
                    try:
                        kind = _get(ann, "GetType2")
                    except Exception:
                        kind = None
                try:
                    kind_i = int(kind) if kind is not None else None
                except (TypeError, ValueError):
                    kind_i = None
                if kind_i == int(WELD_ANNOTATION_TYPE):
                    found.append((ann, vname))
        return found

    def _scan_weld_annotations(self, doc: Any) -> list[dict]:
        """Scan view annotations with GetType==WELD_ANNOTATION_TYPE (probe: 8)."""
        found: list[dict] = []
        for i, (_ann, vname) in enumerate(self._collect_type8_annotations(doc)):
            found.append(
                {
                    "index": i,
                    "name": f"weld_scan_{i + 1}",
                    "symbol": None,
                    "mode": "scanned",
                    "ann_type": int(WELD_ANNOTATION_TYPE),
                    "view": vname,
                }
            )
        return found

    def get_weld_annotations(self) -> list[dict]:
        """Enumerate type==8 weld annotations (no semantic GetText)."""

        def _fn() -> list[dict]:
            doc = self.sw.ActiveDoc
            self._require_drawing_doc(doc, "Call new_drawing first")
            return self._scan_weld_annotations(doc)

        return self._call(_fn)

    def inspect_weld_symbol(self, index: int = 0) -> dict:
        """Recover IWeldSymbol via GetSpecificAnnotation; GetText uses swWeldSymbolTextTypes_e."""

        def _fn() -> dict:
            doc = self.sw.ActiveDoc
            self._require_drawing_doc(doc, "Call new_drawing first")
            idx = int(index)
            if idx < 0:
                raise fail("INVALID_ARGUMENT", f"index must be >= 0, got {index}", "Pass weld annotation index")
            pairs = self._collect_type8_annotations(doc)
            if idx >= len(pairs):
                raise fail(
                    "FEATURE_NOT_FOUND",
                    f"No weld annotation at index {idx} (have {len(pairs)})",
                    "Call get_weld_annotations first",
                )
            ann, vname = pairs[idx]
            specific = None
            via = None
            for meth in ("GetSpecificAnnotation", "IGetSpecificAnnotation", "GetWeldSymbol", "IGetWeldSymbol"):
                try:
                    obj = _get(ann, meth)
                except Exception:
                    obj = None
                if obj is not None:
                    specific, via = obj, meth
                    break
            if specific is None:
                raise fail(
                    "FEATURE_NOT_FOUND",
                    f"Cannot recover IWeldSymbol for index {idx}",
                    "GetSpecificAnnotation returned None",
                )
            texts: dict[str, str] = {}
            for which in range(1, 10):
                try:
                    val = _get(specific, "GetText", which)
                    texts[str(which)] = "" if val is None else str(val)
                except Exception:
                    texts[str(which)] = ""
            symbol = texts.get(str(WELD_TEXT_ABOVE_SYMBOL)) or texts.get(str(WELD_TEXT_BELOW_SYMBOL)) or ""
            attached = None
            try:
                attached = bool(_get(specific, "IsAttached"))
            except Exception:
                pass
            return {
                "index": idx,
                "view": vname,
                "ann_type": int(WELD_ANNOTATION_TYPE),
                "via": via,
                "attached": attached,
                "symbol": symbol.strip() or None,
                "text_above_symbol": texts.get(str(WELD_TEXT_ABOVE_SYMBOL), ""),
                "text_below_symbol": texts.get(str(WELD_TEXT_BELOW_SYMBOL), ""),
                "text_process": texts.get(str(WELD_TEXT_PROCESS), ""),
                "texts": texts,
            }

        return self._call(_fn)
