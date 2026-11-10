"""COM backend · general selection helpers.

All selector methods compose with ComBackend via MRO; at runtime `self` is `ComBackend`.

Dependencies (self, resolved at runtime via MRO):
- `_features_of` / `_aliases` (NamingMixin)
- `_part_face_objects` / `_part_edge_objects` (GeometryMixin, S3-3)

imports:
- `cadmcp.backend.protocol.constants.PLANE_ALIASES / DEFAULT_PLANES`
- `._helpers._get`
"""
from __future__ import annotations

import logging
import math
import time
import traceback
from collections.abc import Sequence
from typing import Any

from cadmcp.backend.protocol.constants import DEFAULT_PLANES, PLANE_ALIASES
from cadmcp.errors import fail

from ._helpers import _get

log = logging.getLogger(__name__)


class SelectionMixin:
    """General selectors (faces / edges / planes / sketches / axes / components)."""

    def _init_state(self) -> None:
        pass  # stateless

    def _clear_selection(self, doc: Any) -> None:
        try:
            doc.ClearSelection2(True)
        except Exception:
            log.debug("ClearSelection2 failed: %s", traceback.format_exc())

    def _select_at(
        self, doc: Any, kind: str, x: float, y: float, z: float, *,
        append: bool = False, mark: int = 0,
    ) -> bool:
        """Select entity by coordinates: verified path (Extension.SelectByID2 + VARIANT callout; see scripts/probe_selection.py).

        Empty Name + type + coordinates is the standard SW face/edge pick; coordinates must lie on the surface,
        so a cylinder side centroid at the axis center will miss (callers raise SELECT_FAILED with alternate picks).
        """
        import pythoncom
        from win32com.client import VARIANT

        callout = VARIANT(pythoncom.VT_DISPATCH, None)
        try:
            return bool(doc.Extension.SelectByID2("", kind, x, y, z, append, mark, callout, 0))
        except Exception:
            log.debug(
                "SelectByID2(%r @ %.4f,%.4f,%.4f) failed: %s",
                kind, x, y, z, traceback.format_exc(),
            )
            return False

    def _select_plane(self, doc: Any, plane: str, *, append: bool, mark: int) -> bool:
        import pythoncom
        from win32com.client import VARIANT

        callout = VARIANT(pythoncom.VT_DISPATCH, None)
        names: list[str] = []
        if plane in PLANE_ALIASES:
            names.extend(PLANE_ALIASES[plane])
        else:
            names.append(plane)
        real = self._aliases.get(plane)
        if real and real not in names:
            names.append(real)
        for name in names:
            try:
                if bool(doc.Extension.SelectByID2(name, "PLANE", 0, 0, 0, append, mark, callout, 0)):
                    return True
            except Exception:
                log.debug("SelectByID2(%r) failed: %s", name, traceback.format_exc())
        if plane in DEFAULT_PLANES:  # fallback: default reference plane order in feature tree
            idx = DEFAULT_PLANES.index(plane)
            try:
                ref_planes = [
                    f for f in self._features_of(doc)
                    if str(_get(f, "GetTypeName2")) == "RefPlane"
                ]
                if idx < len(ref_planes):
                    return bool(ref_planes[idx].Select2(append, mark))
            except Exception:
                log.debug("Failed to select reference plane from feature tree: %s", traceback.format_exc())
        try:
            for feat in self._features_of(doc):
                if str(_get(feat, "GetTypeName2")) != "RefPlane":
                    continue
                fname = str(_get(feat, "Name"))
                if fname in names or fname == plane:
                    return bool(feat.Select2(append, mark))
        except Exception:
            log.debug("Failed to select reference plane by feature name: %s", traceback.format_exc())
        return False

    def _select_entity(self, doc: Any, entity: Any, mark: int = 0) -> bool:
        """Direct object selection (more reliable than by coordinates); mark is feature-command selection mark, usually 0."""
        data = _get(_get(doc, "SelectionManager"), "CreateSelectData")
        data.Mark = mark
        return bool(entity.Select4(False, data))

    def _select_edge_indexes(self, doc: Any, indexes: Sequence[int]) -> int:
        """Select edges by global index from get_edges (part document)."""
        if not indexes:
            raise fail("INVALID_ARGUMENT", "edges cannot be empty", "Pass get_edges indexes, or use target")
        pool = self._part_edge_objects(doc)
        if not pool:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "No edges available for fillet (no solid features yet)",
                "Create a solid with extrude or revolve first",
            )
        sm = _get(doc, "SelectionManager")
        data = _get(sm, "CreateSelectData")
        data.Mark = 1
        doc.ClearSelection2(True)
        count = 0
        seen: set[int] = set()
        for raw in indexes:
            idx = int(raw)
            if idx in seen:
                continue
            seen.add(idx)
            if idx < 0 or idx >= len(pool):
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Edge index out of range: {idx}",
                    f"Use get_edges; valid range 0..{len(pool) - 1}",
                    index=idx,
                )
            try:
                if pool[idx].Select4(True, data):
                    count += 1
            except Exception:
                log.debug("Failed to select edge by index: %s", traceback.format_exc())
        return count

    def _select_one_face(self, doc: Any, index: int, *, mark: int, clear: bool) -> int:
        pool = self._part_face_objects(doc)
        if not pool:
            raise fail(
                "INVALID_ARGUMENT",
                "No solid faces available as end condition",
                "Extrude a solid first, then use get_faces for index",
            )
        if index < 0 or index >= len(pool):
            raise fail(
                "INVALID_ARGUMENT",
                f"Face index out of range: {index}",
                f"Use get_faces; valid range 0..{len(pool) - 1}",
                index=index,
            )
        sm = _get(doc, "SelectionManager")
        data = _get(sm, "CreateSelectData")
        data.Mark = mark
        if clear:
            doc.ClearSelection2(True)
        try:
            return 1 if pool[index].Select4(True, data) else 0
        except Exception:
            log.debug("Failed to select face by mark: %s", traceback.format_exc())
            return 0

    def _select_one_vertex(self, doc: Any, index: int, *, mark: int, clear: bool) -> int:
        pool = self._part_vertex_objects(doc)
        if not pool:
            raise fail(
                "INVALID_ARGUMENT",
                "No solid vertices available as end condition",
                "Extrude a solid first, then use get_vertices for index",
            )
        if index < 0 or index >= len(pool):
            raise fail(
                "INVALID_ARGUMENT",
                f"Vertex index out of range: {index}",
                f"Use get_vertices; valid range 0..{len(pool) - 1}",
                index=index,
            )
        sm = _get(doc, "SelectionManager")
        data = _get(sm, "CreateSelectData")
        data.Mark = mark
        if clear:
            doc.ClearSelection2(True)
        try:
            return 1 if pool[index].Select4(True, data) else 0
        except Exception:
            log.debug("Failed to select vertex by mark: %s", traceback.format_exc())
            return 0

    def _select_face_indexes(self, doc: Any, indexes: Sequence[int]) -> int:
        if not indexes:
            raise fail(
                "INVALID_ARGUMENT",
                "faces cannot be empty",
                "Pass get_faces index list, or omit for closed shell",
            )
        pool = self._part_face_objects(doc)
        if not pool:
            raise fail("FEATURE_CREATE_FAILED", "No faces available for shell", "Create a solid with extrude or revolve first")
        sm = _get(doc, "SelectionManager")
        data = _get(sm, "CreateSelectData")
        data.Mark = 1
        doc.ClearSelection2(True)
        count = 0
        seen: set[int] = set()
        for raw in indexes:
            idx = int(raw)
            if idx in seen:
                continue
            seen.add(idx)
            if idx < 0 or idx >= len(pool):
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Face index out of range: {idx}",
                    f"Use get_faces; valid range 0..{len(pool) - 1}",
                    index=idx,
                )
            try:
                if pool[idx].Select4(True, data):
                    count += 1
            except Exception:
                log.debug("Failed to select face by index: %s", traceback.format_exc())
        return count

    def _select_one_edge(self, doc: Any, index: int, *, mark: int) -> int:
        return self._select_edge_indexes_marked(doc, [index], mark=mark, clear=False)

    def _select_edge_indexes_marked(
        self, doc: Any, indexes: Sequence[int], *, mark: int, clear: bool,
    ) -> int:
        pool = self._part_edge_objects(doc)
        if not pool:
            return 0
        sm = _get(doc, "SelectionManager")
        data = _get(sm, "CreateSelectData")
        data.Mark = mark
        if clear:
            doc.ClearSelection2(True)
        count = 0
        for raw in indexes:
            idx = int(raw)
            if idx < 0 or idx >= len(pool):
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Edge index out of range: {idx}",
                    f"Use get_edges; valid range 0..{len(pool) - 1}",
                    index=idx,
                )
            try:
                if pool[idx].Select4(True, data):
                    count += 1
            except Exception:
                log.debug("Failed to select edge by mark: %s", traceback.format_exc())
        return count

    def _select_sketch_seg(self, doc: Any, seg: Any, *, append: bool, mark: int) -> bool:
        ends = self._segment_xy(seg)
        if mark != 0 and ends is not None:
            (ax, ay), (bx, by) = ends
            if self._select_at(
                doc, "SKETCHSEGMENT", (ax + bx) / 2, (ay + by) / 2, 0.0, append=append, mark=mark
            ):
                return True
        try:
            if bool(seg.Select2(append, mark)):
                return True
        except Exception:
            log.debug("SketchSegment.Select2 failed: %s", traceback.format_exc())
        try:
            if mark == 0 and bool(seg.Select(append)):
                return True
        except Exception:
            log.debug("SketchSegment.Select failed: %s", traceback.format_exc())
        if ends is None:
            return False
        (ax, ay), (bx, by) = ends
        return self._select_at(
            doc, "SKETCHSEGMENT", (ax + bx) / 2, (ay + by) / 2, 0.0, append=append, mark=mark
        )

    def _select_sketch_endpoint_pair(self, s1: Any, s2: Any) -> bool:
        """Select the closest endpoint pair between two entities (line/arc coincident)."""
        pts1 = [_get(s1, "GetStartPoint2"), _get(s1, "GetEndPoint2")]
        pts2 = [_get(s2, "GetStartPoint2"), _get(s2, "GetEndPoint2")]
        best: tuple[float, Any, Any] | None = None
        for a in pts1:
            if a is None:
                continue
            ax, ay = float(_get(a, "X")), float(_get(a, "Y"))
            for b in pts2:
                if b is None:
                    continue
                d = math.hypot(ax - float(_get(b, "X")), ay - float(_get(b, "Y")))
                if best is None or d < best[0]:
                    best = (d, a, b)
        if best is None:
            return False
        _, a, b = best
        try:
            if not a.Select2(False, 0):
                return False
            return bool(b.Select2(True, 0))
        except Exception:
            log.debug("Failed to select sketch endpoints: %s", traceback.format_exc())
            return False

    def _select_sketch_midpoint_pair(self, point_seg: Any, line_seg: Any) -> bool:
        """Midpoint constraint: pick endpoint on point_seg nearest line midpoint + select line_seg."""
        try:
            a = _get(line_seg, "GetStartPoint2")
            b = _get(line_seg, "GetEndPoint2")
            mx = (float(_get(a, "X")) + float(_get(b, "X"))) / 2.0
            my = (float(_get(a, "Y")) + float(_get(b, "Y"))) / 2.0
        except Exception:
            log.debug("Failed to get midpoint target line: %s", traceback.format_exc())
            return False
        best: tuple[float, Any] | None = None
        for pt in (_get(point_seg, "GetStartPoint2"), _get(point_seg, "GetEndPoint2")):
            if pt is None:
                continue
            try:
                d = math.hypot(float(_get(pt, "X")) - mx, float(_get(pt, "Y")) - my)
            except Exception:
                continue
            if best is None or d < best[0]:
                best = (d, pt)
        if best is None:
            return False
        try:
            if not best[1].Select2(False, 0):
                return False
            return bool(line_seg.Select2(True, 0))
        except Exception:
            log.debug("Failed to select midpoint constraint endpoints/line: %s", traceback.format_exc())
            return False

    def _select_sketch_or_curve(
        self, doc: Any, name: str, *, append: bool, mark: int, is_sketch: bool,
    ) -> bool:
        """Select sketch/curve feature by name; SelectByID2 first, then feature-tree Select2."""
        import pythoncom
        from win32com.client import VARIANT

        callout = VARIANT(pythoncom.VT_DISPATCH, None)
        real = self._real_name(name)
        if is_sketch:
            for cand in (real, name):
                try:
                    if bool(doc.Extension.SelectByID2(cand, "SKETCH", 0, 0, 0, append, mark, callout, 0)):
                        return True
                except Exception:
                    log.debug("SelectByID2(%r, SKETCH) failed: %s", cand, traceback.format_exc())
        feat = self._find_feature(doc, real)
        if feat is None:
            return False
        try:
            return bool(feat.Select2(append, mark))
        except Exception:
            log.debug("Select2(%r, mark=%d) failed: %s", name, mark, traceback.format_exc())
            return False

    def _select_sketch_segments(self, doc: Any, name: str, *, mark: int) -> int:
        """Select sketch line segments (append, do not clear profile). Loft centerlines must pick segments, not sketch feature."""
        real = self._real_name(name)
        feat = self._find_feature(doc, real)
        if feat is None:
            feat = self._find_feature(doc, name)
        if feat is None:
            return 0
        try:
            sk = _get(feat, "GetSpecificFeature2")
            segs = [s for s in list(_get(sk, "GetSketchSegments") or []) if s is not None]
        except Exception:
            log.debug("Failed to read sketch segments: %s", traceback.format_exc())
            return 0
        sm = _get(doc, "SelectionManager")
        count = 0
        for seg in segs:
            try:
                data = _get(sm, "CreateSelectData")
                data.Mark = mark
                if bool(seg.Select4(True, data)):
                    count += 1
            except Exception:
                log.debug("Select4 sketch segment failed: %s", traceback.format_exc())
        return count

    def _select_axis_feat(self, doc: Any, name: str, *, append: bool, mark: int) -> bool:
        import pythoncom
        from win32com.client import VARIANT

        feat = self._find_feature(doc, name)
        if feat is not None:
            try:
                if bool(feat.Select2(append, mark)):
                    return True
            except Exception:
                log.debug("Select2 axis failed: %s", traceback.format_exc())
        callout = VARIANT(pythoncom.VT_DISPATCH, None)
        real = self._aliases.get(name, name)
        for nm in (name, real):
            try:
                if bool(doc.Extension.SelectByID2(nm, "AXIS", 0, 0, 0, append, mark, callout, 0)):
                    return True
            except Exception:
                log.debug("SelectByID2 AXIS %s failed: %s", nm, traceback.format_exc())
        return False

    def _select_ref_axis(self, doc: Any, axis_feat: Any, *, mark: int) -> bool:
        """Select reference axis for circular pattern. Prefer SelectByID2(AXIS), then feature Select2."""
        if axis_feat is None:
            return False
        import pythoncom
        from win32com.client import VARIANT

        callout = VARIANT(pythoncom.VT_DISPATCH, None)
        try:
            name = str(_get(axis_feat, "Name"))
        except Exception:
            name = ""
        if name:
            try:
                if bool(
                    doc.Extension.SelectByID2(name, "AXIS", 0, 0, 0, True, mark, callout, 0)
                ):
                    return True
            except Exception:
                log.debug("SelectByID2 AXIS %s failed: %s", name, traceback.format_exc())
        try:
            return bool(axis_feat.Select2(True, mark))
        except Exception:
            log.debug("RefAxis.Select2 failed: %s", traceback.format_exc())
            return False

    def _select_model_axis(self, doc: Any, axis: str, *, mark: int) -> bool:
        """Select origin axis for circular pattern. Locale names + feature-tree RefAxis fallback."""
        import pythoncom
        from win32com.client import VARIANT

        letter = axis[1].upper()
        names = (
            f"{letter} \u8f74",
            f"{letter}-Axis",
            f"{letter} Axis",
            f"Axis{ {'X': 1, 'Y': 2, 'Z': 3}[letter] }",
        )
        callout = VARIANT(pythoncom.VT_DISPATCH, None)
        for sel_type in ("AXIS", "EXTAXIS", "DATUMAXIS"):
            for name in names:
                try:
                    if bool(
                        doc.Extension.SelectByID2(name, sel_type, 0, 0, 0, True, mark, callout, 0)
                    ):
                        return True
                except Exception:
                    log.debug("SelectByID2 axis %s/%s failed: %s", name, sel_type, traceback.format_exc())
        try:
            refs = [
                f for f in self._features_of(doc)
                if str(_get(f, "GetTypeName2")) in {"RefAxis", "OriginProfileFeature"}
            ]
            order = {"x": 0, "y": 1, "z": 2}
            idx = order.get(axis[1], 2)
            if idx < len(refs) and bool(refs[idx].Select2(True, mark)):
                return True
        except Exception:
            log.debug("Failed to select axis from feature tree: %s", traceback.format_exc())
        return False

    def _select_component(
        self, asm: Any, comp: Any, *, append: bool = False, mark: int = 0,
    ) -> bool:
        if not append:
            self._clear_selection(asm)
        try:
            import pythoncom
            from win32com.client import VARIANT

            title = str(_get(asm, "GetTitle"))
            name = str(_get(comp, "Name2") or "")
            callout = VARIANT(pythoncom.VT_DISPATCH, None)
            ext = _get(asm, "Extension")
            if _get(
                ext,
                "SelectByID2",
                f"{name}@{title}",
                "COMPONENT",
                0.0, 0.0, 0.0,
                bool(append), mark, callout, 0,
            ):
                return True
        except Exception:
            log.debug("SelectByID2 component failed: %s", traceback.format_exc())
        for sel in ("Select4", "Select2"):
            try:
                if sel == "Select4":
                    if bool(_get(comp, "Select4", bool(append), None)):
                        return True
                elif bool(_get(comp, "Select2", bool(append), mark)):
                    return True
            except Exception:
                continue
        return False

    def _select_edges(self, doc: Any, target: str | None) -> int:
        """Select all edges (target=None) or edges of a feature; returns selection count."""
        t0 = time.perf_counter()

        sm = _get(doc, "SelectionManager")
        data = _get(sm, "CreateSelectData")
        data.Mark = 1
        doc.ClearSelection2(True)
        edge_lists: list[Any] = []
        if target is None:
            for body in _get(doc, "GetBodies2", 0, False) or ():
                edge_lists.append(_get(body, "GetEdges") or ())
        else:
            feat = self._resolve_feature(doc, target)
            for face in _get(feat, "GetFaces") or ():
                edge_lists.append(_get(face, "GetEdges") or ())
        count = 0
        for edges in edge_lists:
            for edge in edges:
                try:
                    if edge.Select4(True, data):
                        count += 1
                except Exception:
                    log.debug("Failed to select edge: %s", traceback.format_exc())

        log.debug("_select_edges target=%s selected %d edges in %.2fs", target, count, time.perf_counter() - t0)

        return count
