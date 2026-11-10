"""COM backend · sketch · offset / fillet trim / mirror.

Split from com/sketch.py by domain; method bodies unchanged (COM call order and sketch state machine).

Dependencies (self, MRO):
- `_call` / `_map_error` (STAThreadMixin)
- `_find_feature` / `_features_of` / `_register` / `_aliases` (NamingMixin)
- `_clear_selection` / `_select_plane` / `_select_sketch_seg` / `_select_sketch_endpoint_pair` (SelectionMixin)
- `_plane_uv_root` (PlaneAxisMixin)
"""

from __future__ import annotations

from cadmcp.errors import fail

from .._helpers import _get


class SketchModifyMixin:
    """Sketch offset / fillet trim / mirror."""

    def sketch_offset(self, distance_m: float, inward: bool = False) -> None:
        def _fn() -> None:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            self._require_open_sketch(planar=True)
            if distance_m <= 0:
                raise fail("INVALID_ARGUMENT", "Offset distance must be positive", "Pass distance > 0")
            segs = self._sketch_segments(doc)
            self._clear_selection(doc)
            n = 0
            for seg in segs:
                if self._segment_is_construction(seg):
                    continue
                if self._select_sketch_seg(doc, seg, append=n > 0, mark=0):
                    n += 1
            if n == 0:
                raise fail(
                    "SKETCH_OP_FAILED",
                    "No closed profile to offset",
                    "Call sketch_rectangle or sketch_circle first",
                )
            sm = _get(doc, "SketchManager")
            dist = -abs(float(distance_m)) if inward else abs(float(distance_m))
            try:
                ret = sm.SketchOffset2(dist, False, False, 0, 0, True)
            except Exception as exc:
                raise self._map_error(exc) from exc
            if ret is False:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Sketch offset failed",
                    "Confirm the profile is closed and distance does not collapse it",
                )
            self._sketch_entities = len(self._sketch_segments(doc))

        return self._call(_fn)


    def sketch_trim(self, entity1: int, entity2: int, radius_m: float) -> None:
        def _fn() -> None:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            self._require_open_sketch(planar=True)
            if radius_m <= 0:
                raise fail("INVALID_ARGUMENT", "Fillet radius must be positive", "Pass radius > 0")
            if entity1 == entity2:
                raise fail("INVALID_ARGUMENT", "Fillet trim needs two different entities", "entity1 and entity2 must differ")
            segs = self._sketch_segments(doc)
            s1 = self._seg_at(segs, entity1)
            s2 = self._seg_at(segs, entity2)
            self._clear_selection(doc)
            ok1 = self._select_sketch_seg(doc, s1, append=False, mark=0)
            ok2 = self._select_sketch_seg(doc, s2, append=True, mark=0)
            if not ok1 or not ok2:
                raise fail(
                    "SELECT_FAILED",
                    f"Could not select sketch entities {entity1}/{entity2}",
                    "Confirm indices match GetSketchSegments order",
                )
            sm = _get(doc, "SketchManager")
            n0 = len(segs)
            try:
                ret = sm.CreateFillet(float(radius_m), 1)
            except Exception as exc:
                raise self._map_error(exc) from exc
            n1 = len(self._sketch_segments(doc))
            if ret is False and n1 <= n0:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Sketch fillet failed",
                    "Select adjacent edges and reduce radius",
                )
            self._sketch_entities = n1

        return self._call(_fn)


    def sketch_mirror(self, axis: int) -> None:
        def _fn() -> None:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            self._require_open_sketch(planar=True)
            segs = self._sketch_segments(doc)
            ax = self._seg_at(segs, axis)
            try:
                ax.ConstructionGeometry = True
            except Exception as exc:
                raise self._map_error(exc) from exc
            self._clear_selection(doc)
            if not self._select_sketch_seg(doc, ax, append=False, mark=2):
                raise fail("SELECT_FAILED", f"Could not select mirror axis {axis}", "Axis must be a sketch line")
            copied = 0
            for i, seg in enumerate(segs):
                if i == axis or self._segment_is_construction(seg):
                    continue
                if self._select_sketch_seg(doc, seg, append=True, mark=1):
                    copied += 1
            if copied == 0:
                raise fail("SKETCH_OP_FAILED", "No entities to mirror", "Draw the profile besides the axis line")
            n0 = len(segs)
            try:
                ret = doc.SketchMirror()
            except Exception as exc:
                raise self._map_error(exc) from exc
            n1 = len(self._sketch_segments(doc))
            if ret is False and n1 <= n0:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Sketch mirror failed",
                    "Confirm axis is a line and other entities are selected",
                )
            self._sketch_entities = n1

        return self._call(_fn)
