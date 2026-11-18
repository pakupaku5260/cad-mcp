"""Drawing sheets and title block: paper/scale props, sheet CRUD, custom properties.

Does not create views or annotations.
Boundary: every COM call stays inside `self._call`; title block values come from
CustomPropertyManager.
"""

from __future__ import annotations

import logging
import traceback
from typing import Any

from cadmcp.backend.protocol.constants import DRAWING_PAPER_CODES, TITLE_BLOCK_DEFAULT_KEYS
from cadmcp.errors import fail

from .._helpers import _get

log = logging.getLogger(__name__)

class DrawingSheetsMixin:
    """Sheet properties, sheet CRUD, title block read/write."""

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
