"""Annotation placement mechanics: Insert* dispatch, edge preselection, selection count.

Does not build labels or edit geometry; only datum and GD&T insertion use it.
Boundary: these helpers run inside the caller's `_call` lambda and never start their own.
"""

from __future__ import annotations

import logging
import traceback
from typing import Any

from .._helpers import _get

log = logging.getLogger(__name__)

class DrawingPlacementMixin:
    """Insert* dispatch, edge preselection and selection counting helpers."""

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
