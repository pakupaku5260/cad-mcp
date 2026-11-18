"""Drawing views: model, section and detail view creation plus view selection.

Does not create annotations, sheets or layers.
Boundary: every COM call stays inside `self._call`; helpers only read the active document.
"""

from __future__ import annotations

import logging
import traceback
from pathlib import Path
from typing import Any

from cadmcp.backend.protocol.constants import DRAWING_VIEW_ALIASES
from cadmcp.backend.protocol.parsers import drawing_view_key
from cadmcp.errors import fail

from .._constants import SW_DOC_DRAWING
from .._helpers import _get

log = logging.getLogger(__name__)

class DrawingViewsMixin:
    """Model/section/detail view creation plus view selection helpers."""

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
