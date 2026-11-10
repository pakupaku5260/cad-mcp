"""COM backend · sketch · lifecycle and state (open/close/edit/solve).

Split from com/sketch.py by domain; method bodies unchanged (COM call order and sketch state machine).

Dependencies (self, MRO):
- `_call` / `_map_error` (STAThreadMixin)
- `_find_feature` / `_features_of` / `_register` / `_aliases` (NamingMixin)
- `_clear_selection` / `_select_plane` / `_select_sketch_seg` / `_select_sketch_endpoint_pair` (SelectionMixin)
- `_plane_uv_root` (PlaneAxisMixin)
"""

from __future__ import annotations

import logging
import traceback
from typing import Any

from cadmcp.backend.protocol.models import SketchInfo, SketchSolveStatus
from cadmcp.backend.protocol.parsers import is_3d_sketch_plane
from cadmcp.errors import fail

from .._constants import _SKETCH_FEATURE_TYPES
from .._helpers import _get

log = logging.getLogger(__name__)

class SketchLifecycleMixin:
    """Sketch lifecycle and state (open/close/edit/solve)."""

    def _init_state(self) -> None:
        self._pending_sketch_name: str | None = None
        self._sketch_open: bool = False
        self._sketch_editing: bool = False
        self._sketch_plane: str | None = None
        self._sketch_entities: int = 0
        self._completed_sketches: list[str] = []
        self._sketch_3d: bool = False


    def _sketch_dispatch(self, doc: Any, sketch: str | None) -> Any:
        if sketch is None:
            if not self._sketch_open:
                raise fail(
                    "NO_ACTIVE_SKETCH",
                    "No sketch is open",
                    "Call start_sketch first, or pass sketch=Sketch1",
                )
            active = _get(_get(doc, "SketchManager"), "ActiveSketch")
            if active is None:
                raise fail("NO_ACTIVE_SKETCH", "No sketch is open", "Call start_sketch first")
            return active
        feat = self._find_feature(doc, sketch)
        if feat is None:
            raise fail(
                "FEATURE_NOT_FOUND",
                f"Sketch not found {sketch!r}",
                "Use name from end_sketch, or list_features",
                requested=sketch,
            )
        try:
            spec = _get(feat, "GetSpecificFeature2") or feat
        except Exception:
            spec = feat
        return spec


    def _sketch_segments(self, doc: Any) -> list:
        sketch = _get(_get(doc, "SketchManager"), "ActiveSketch")
        if sketch is None:
            raise fail("NO_ACTIVE_SKETCH", "No sketch is open", "Call start_sketch first")
        return list(_get(sketch, "GetSketchSegments") or ())


    @staticmethod
    def _seg_at(segs: list, index: int) -> Any:
        if index < 0 or index >= len(segs):
            raise fail(
                "INVALID_ARGUMENT",
                f"Sketch entity index out of range: {index}",
                f"Valid range 0..{len(segs) - 1}" if segs else "Draw sketch entities first",
            )
        return segs[index]


    def _reset_sketch_state(self) -> None:
        """Clear only sketch lifecycle state (sole owner: SketchMixin).

        On document switch also call `_reset_naming_state` / `_reset_plane_state`
        (see DocumentMixin._reset_session_state).
        """
        self._sketch_open = False
        self._sketch_editing = False
        self._pending_sketch_name = None
        self._completed_sketches.clear()
        self._sketch_plane = None
        self._sketch_entities = 0
        self._sketch_3d = False


    def _last_sketch_feature(self, doc: Any) -> Any:
        last = None
        for feat in self._features_of(doc):
            try:
                if str(_get(feat, "GetTypeName2")) in _SKETCH_FEATURE_TYPES:
                    last = feat
            except Exception:
                continue
        return last


    def _select_pending_sketch(self, doc: Any, sketch: str | None) -> tuple[Any, str]:
        """Shared by revolve/cut: verify closed sketch, select it, return (sketch feature, name)."""
        if self._sketch_open:
            raise fail(
                "SKETCH_OP_FAILED",
                "Sketch is still open; cannot create a feature directly",
                "Call end_sketch to close the sketch, then run the feature operation",
            )
        pending = self._pending_sketch_name
        if pending is None or (sketch is not None and sketch != pending):
            raise fail(
                "SKETCH_NOT_FOUND",
                f"No closed sketch available for feature (requested {sketch!r}, current: {pending})",
                "Call start_sketch -> draw -> end_sketch, then run the feature operation",
                requested=sketch,
            )
        feat = self._find_feature(doc, pending)
        doc.ClearSelection2(True)
        if feat is None or not feat.Select2(False, 0):
            # raise fail("SKETCH_NOT_FOUND", f"Could not select sketch {pending}", "Confirm the sketch still exists")
            raise fail("SELECT_FAILED", f"Could not select sketch {pending}", "Confirm the sketch still exists")
        return feat, pending


    def _consume_sketch_name(self, name: str | None) -> None:
        """After feature absorbs sketch: remove from completed list and clear pending."""
        if name is not None:
            self._completed_sketches = [x for x in self._completed_sketches if x != name]
        if name is None or self._pending_sketch_name == name:
            self._pending_sketch_name = None


    def _solve_status_of(sketch: Any) -> SketchSolveStatus:
        raw = None
        for attr in ("GetConstrainedStatus2", "GetConstrainedStatus", "ConstrainedStatus"):
            try:
                raw = _get(sketch, attr)
            except Exception:
                raw = None
            if raw is not None:
                break
        try:
            if callable(raw):
                raw = raw()
        except Exception:
            raw = None
        code = None
        try:
            if raw is not None:
                code = int(raw)
        except Exception:
            code = None
        fully = False
        try:
            flag = _get(sketch, "IsFullyDefined")
            if callable(flag):
                flag = flag()
            fully = bool(flag)
        except Exception:
            fully = False
        # swConstrainedStatus_e: commonly 2 under, 3 fully, 4 over (1/0 treated as under-defined)
        if code in (4, 5):
            state = "over_defined"
        elif code == 3 or fully:
            state = "fully_defined"
        else:
            state = "under_defined"
        return SketchSolveStatus(state=state, dof=None)


    def edit_sketch(self, name: str) -> SketchInfo:
        def _fn() -> SketchInfo:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            if self._sketch_open:
                raise fail(
                    "SKETCH_OP_FAILED",
                    "A sketch is already open; cannot open two at once",
                    "Call end_sketch to close the current sketch, then edit_sketch",
                )
            feat = self._find_feature(doc, name)
            if feat is None:
                raise fail(
                    "FEATURE_NOT_FOUND",
                    f"Sketch not found {name!r}",
                    "Use name from end_sketch, or list_features",
                    requested=name,
                )
            self._clear_selection(doc)
            real = str(_get(feat, "Name") or name)
            selected = False
            try:
                selected = bool(feat.Select2(False, 0))
            except Exception:
                selected = False
            if not selected:
                import pythoncom
                from win32com.client import VARIANT

                callout = VARIANT(pythoncom.VT_DISPATCH, None)
                for typ in ("SKETCH", "PROFILEFEATURE", "EXTSKETCH"):
                    try:
                        selected = bool(
                            doc.Extension.SelectByID2(real, typ, 0, 0, 0, False, 0, callout, 0)
                        )
                    except Exception:
                        selected = False
                    if selected:
                        break
            if not selected:
                raise fail("SELECT_FAILED", f"Could not select sketch {name!r}", "Confirm the sketch is still in the feature tree")
            sm = _get(doc, "SketchManager")
            try:
                _get(doc, "EditSketch")
            except Exception:
                log.debug("EditSketch failed: %s", traceback.format_exc())
            active = _get(sm, "ActiveSketch")
            if active is None:
                try:
                    _get(sm, "InsertSketch", True)
                except Exception as exc:
                    raise self._map_error(exc) from exc
                active = _get(sm, "ActiveSketch")
            if active is None:
                raise fail(
                    "SKETCH_OP_FAILED",
                    f"Could not enter sketch {name!r}",
                    "Confirm the sketch is not suppressed and no other sketch editor is open",
                )
            self._sketch_open = True
            self._sketch_editing = True
            n = len(list(_get(active, "GetSketchSegments") or ()))
            self._sketch_entities = n
            logical = next((k for k, v in self._aliases.items() if v == real), name)
            plane = self._sketch_plane or "unknown"
            return SketchInfo(plane=plane, entity_count=n, name=logical)

        return self._call(_fn)


    def sketch_solve_status(self, sketch: str | None = None) -> SketchSolveStatus:
        def _fn() -> SketchSolveStatus:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            sk = self._sketch_dispatch(doc, sketch)
            return self._solve_status_of(sk)

        return self._call(_fn)


    def begin_sketch(self, plane: str) -> None:
        def _fn() -> None:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            if self._sketch_open:
                raise fail(
                    "SKETCH_OP_FAILED",
                    "A sketch is already open; cannot open two at once",
                    "Call end_sketch to close the current sketch before starting a new one",
                )

            doc.ClearSelection2(True)
            if is_3d_sketch_plane(plane):
                try:
                    doc.SketchManager.Insert3DSketch(True)
                except Exception as exc:
                    raise self._map_error(exc) from exc
                self._sketch_open = True
                self._sketch_3d = True
                self._sketch_plane = "3D"
                self._sketch_entities = 0
                return
            selected = self._select_plane(doc, plane, append=False, mark=0)

            if not selected:
                raise fail(
                    "SKETCH_NOT_FOUND",
                    f"Reference plane not found: {plane}",
                    "Use list_planes to see available reference plane names",
                )
            try:
                doc.SketchManager.InsertSketch(True)
            except Exception as exc:
                raise self._map_error(exc) from exc
            self._sketch_open = True
            self._sketch_3d = False
            self._sketch_plane = plane
            self._sketch_entities = 0

        self._call(_fn)


    def end_sketch(self) -> SketchInfo:
        def _fn() -> SketchInfo:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")

            self._require_open_sketch()

            try:
                if self._sketch_3d:
                    doc.SketchManager.Insert3DSketch(True)
                else:
                    doc.SketchManager.InsertSketch(True)
            except Exception as exc:
                raise self._map_error(exc) from exc

            self._sketch_open = False
            self._sketch_3d = False

            name = None
            feat = self._last_sketch_feature(doc)
            if feat is not None:
                try:
                    name = str(_get(feat, "Name"))
                except Exception:
                    log.debug("Failed to read sketch feature name: %s", traceback.format_exc())
                    name = None

            self._pending_sketch_name = name  # real name for Select2 / feature-tree lookup
            if self._sketch_editing:
                logical = next((k for k, v in self._aliases.items() if v == name), name)
            else:
                logical = self._register("Sketch", name) if name else None
                if name is not None:
                    self._completed_sketches.append(name)
            self._sketch_editing = False
            info = SketchInfo(
                plane=self._sketch_plane or "unknown",
                entity_count=self._sketch_entities,
                name=logical or name,
            )
            self._sketch_plane = None
            self._sketch_entities = 0
            return info

        return self._call(_fn)


    def active_sketch(self) -> SketchInfo | None:
        if not self._sketch_open:
            return None
        return SketchInfo(
            plane=self._sketch_plane or "unknown",
            entity_count=self._sketch_entities,
            name=None,
        )


    def _require_open_sketch(self, *, planar: bool = False) -> None:
        if not self._sketch_open:
            raise fail(
                "NO_ACTIVE_SKETCH",
                "No sketch is open",
                "Call start_sketch, pick a reference plane, and draw a profile",
            )
        if planar and self._sketch_3d:
            raise fail(
                "INVALID_ARGUMENT",
                "This operation supports planar sketches only",
                "Call end_sketch, then start_sketch on a reference plane; for 3D use entity tools that accept z/cz",
            )
