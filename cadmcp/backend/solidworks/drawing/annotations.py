"""Drawing annotations: model items, balloons, datums, GD&T, welds and dimension tolerances.

Does not create views, sheets, layers or report inspection results.
Boundary: every COM call stays inside `self._call`; note fallbacks keep the datum_/gdt_ names.
Weld has no Note fallback (probe: native InsertWeldSymbol3 only).
"""

from __future__ import annotations

import logging
import traceback

from cadmcp.backend.protocol.constants import GDT_FRAME_SYMBOLS, GDT_SYMBOLS, WELD_SYMBOLS
from cadmcp.errors import fail

from .._helpers import _get

log = logging.getLogger(__name__)

class DrawingAnnotationsMixin:
    """Model items, balloons, datums, GD&T, weld symbols and dimension tolerances."""

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

    def apply_drawing_tolerances(self, tolerances: list[dict]) -> int:
        """risk: unverified — only successful SetTolerance* calls count toward the return value."""

        def _fn() -> int:
            doc = self.sw.ActiveDoc
            self._require_drawing_doc(doc, "Call new_drawing first")
            applied_rows: list[dict] = []
            failed: list[str] = []
            for item in tolerances:
                name = str(item.get("dimension") or "").strip()
                if not name:
                    continue
                ok = False
                try:
                    disp = doc.Extension.GetDisplayDimensionByName2(name, 1)
                except Exception:
                    disp = None
                if disp is not None:
                    try:
                        dim = _get(disp, "GetDimension2", 0) or _get(disp, "GetDimension")
                        if dim is not None:
                            tol_type = int(item.get("type", 1) or 1)
                            _get(dim, "SetToleranceType2", tol_type, True)
                            vals = item.get("values") or []
                            if isinstance(vals, list) and len(vals) >= 2:
                                _get(dim, "SetToleranceValues", float(vals[0]), float(vals[1]))
                            ok = True
                    except Exception:
                        log.debug("Write tolerance failed %s: %s", name, traceback.format_exc())
                        ok = False
                if ok:
                    applied_rows.append(dict(item))
                else:
                    failed.append(name)
            self._drawing_tol_applied = applied_rows
            self._drawing_tol_failed = failed
            return len(applied_rows)

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

    def insert_weld_symbol(
        self,
        symbol: str,
        x_m: float = 0.1,
        y_m: float = 0.1,
        edge: int | None = None,
    ) -> str:
        """InsertWeldSymbol3 + SetText(Top,Left,Symbol,Right,Stagger,Contour). No Note fallback.

        risk: unverified for GetText content / post-reopen GetWeldSymbol; session + ann type 8 for inspect.
        """

        def _fn() -> str:
            doc = self.sw.ActiveDoc
            self._require_drawing_doc(doc, "Call new_drawing first")
            sym = str(symbol).strip().upper()
            if sym not in WELD_SYMBOLS:
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Unknown weld symbol: {symbol!r}",
                    f"Options: {', '.join(WELD_SYMBOLS)}",
                )
            selected = self._preselect_drawing_edge(doc, edge)
            weld = None
            for name in ("InsertWeldSymbol3", "IInsertWeldSymbol3", "InsertWeldSymbol2", "InsertWeldSymbol"):
                weld = self._com_insert_annotation(doc, name)
                if weld is not None:
                    break
            if weld is None:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    f"Cannot insert weld symbol {sym}",
                    "Confirm model view has visible edges; or pass edge index",
                )
            attached = None
            try:
                attached = bool(_get(weld, "IsAttached"))
            except Exception:
                log.debug("IsAttached failed: %s", traceback.format_exc())
            try:
                ann = _get(weld, "GetAnnotation")
                if ann is not None:
                    try:
                        _get(ann, "SetPosition2", float(x_m), float(y_m), 0.0)
                    except Exception:
                        _get(ann, "SetPosition", float(x_m), float(y_m), 0.0)
            except Exception:
                log.debug("Weld placement failed: %s", traceback.format_exc())
            settext_ok = False
            try:
                # Official: Top, Left, Symbol, Right, Stagger, Contour
                ret = _get(weld, "SetText", True, "", sym, "", "", 0)
                settext_ok = ret is not False
            except Exception:
                log.debug("SetText failed: %s", traceback.format_exc())
                settext_ok = False
            if not settext_ok:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    f"Weld symbol {sym} inserted but SetText failed",
                    "Probe used SetText(True,'',SYMBOL,'','',0); confirm gtol.sym name",
                )
            if attached is False:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    f"Weld symbol {sym} IsAttached=False",
                    "Pre-select a visible edge; pass edge index",
                )
            name = f"weld_{sym}_{len(self._drawing_welds) + 1}"
            self._drawing_welds.append(
                {
                    "name": name,
                    "symbol": sym,
                    "mode": "native",
                    "edge_selected": selected,
                    "attached": attached,
                    "x_m": float(x_m),
                    "y_m": float(y_m),
                }
            )
            return name

        return self._call(_fn)
