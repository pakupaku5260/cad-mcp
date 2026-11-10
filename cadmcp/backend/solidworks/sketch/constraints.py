"""COM backend · sketch · dimensions, constraints, and entity queries.

Split from com/sketch.py by domain; method bodies unchanged (COM call order and sketch state machine).

Dependencies (self, MRO):
- `_call` / `_map_error` (STAThreadMixin)
- `_find_feature` / `_features_of` / `_register` / `_aliases` (NamingMixin)
- `_clear_selection` / `_select_plane` / `_select_sketch_seg` / `_select_sketch_endpoint_pair` (SelectionMixin)
- `_plane_uv_root` (PlaneAxisMixin)
"""

from __future__ import annotations

import logging
import math
import traceback
from typing import Any

from cadmcp.backend.protocol.constants import SW_SKETCH_SPLINE
from cadmcp.backend.protocol.geometry_engine import (
    circle_matches_center_rim,
    line_matches_ends,
)
from cadmcp.backend.protocol.models import SketchEntityRef
from cadmcp.backend.protocol.parsers import resolve_sketch_relation
from cadmcp.errors import fail

from .._constants import (
    _SW_INPUT_DIM_VAL_ON_CREATE,
    _SW_SETVALUE_CURRENT_CFG,
)
from .._helpers import _get

log = logging.getLogger(__name__)

class SketchConstraintMixin:
    """Sketch dimensions, constraints, and entity queries."""

    def _segment_matches_line(
        self, seg: Any, x1: float, y1: float, x2: float, y2: float,
    ) -> bool:
        ends = self._segment_xy(seg)
        if ends is None:
            return False
        (ax, ay), (bx, by) = ends
        return line_matches_ends(ax, ay, bx, by, x1, y1, x2, y2)


    def _segment_matches_circle(
        self, seg: Any, x1: float, y1: float, x2: float, y2: float,
    ) -> bool:
        geom = self._segment_circle(seg)
        if geom is None:
            return False
        cx, cy, radius = geom
        return circle_matches_center_rim(cx, cy, radius, x1, y1, x2, y2)


    @staticmethod
    def _segment_circle(seg: Any) -> tuple[float, float, float] | None:
        try:
            if int(_get(seg, "GetType")) != 1:  # swSketchARC
                return None
            center = _get(seg, "GetCenterPoint2")
            radius = float(_get(seg, "GetRadius"))
            return float(_get(center, "X")), float(_get(center, "Y")), radius
        except Exception:
            log.debug("Failed to read sketch arc: %s", traceback.format_exc())
            return None


    @staticmethod
    def _segment_xy(seg: Any) -> tuple[tuple[float, float], tuple[float, float]] | None:
        try:
            p0 = _get(seg, "GetStartPoint2")
            p1 = _get(seg, "GetEndPoint2")
            return (
                (float(_get(p0, "X")), float(_get(p0, "Y"))),
                (float(_get(p1, "X")), float(_get(p1, "Y"))),
            )
        except Exception:
            log.debug("Failed to read sketch segment endpoints: %s", traceback.format_exc())
            return None


    @staticmethod
    def _segment_is_construction(seg: Any) -> bool:
        try:
            return bool(_get(seg, "ConstructionGeometry"))
        except Exception:
            return False


    @staticmethod
    def _point_line_dist(
        px: float, py: float, ax: float, ay: float, bx: float, by: float,
    ) -> float:
        vx, vy = bx - ax, by - ay
        den = vx * vx + vy * vy
        if den <= 1e-24:
            return math.hypot(px - ax, py - ay)
        t = ((px - ax) * vx + (py - ay) * vy) / den
        return math.hypot(px - (ax + t * vx), py - (ay + t * vy))


    def _entity_ref_from_seg(self, index: int, seg: Any) -> SketchEntityRef:
        construction = self._segment_is_construction(seg)
        circ = self._segment_circle(seg)
        ends = self._segment_xy(seg)
        kind = "line"
        points: tuple[tuple[float, float], ...] = ()
        radius = None
        stype = None
        try:
            stype = int(_get(seg, "GetType"))
        except Exception:
            stype = None
        if stype == SW_SKETCH_SPLINE:
            kind = "spline"
            if ends is not None:
                (ax, ay), (bx, by) = ends
                ax, ay = self._uv_from_sw(ax, ay)
                bx, by = self._uv_from_sw(bx, by)
                points = ((ax, ay), (bx, by))
            return SketchEntityRef(
                index=index, kind=kind, points_m=points, radius_m=None, construction=construction
            )
        if circ is not None:
            cx, cy, radius = circ
            cx, cy = self._uv_from_sw(cx, cy)
            if ends is not None:
                (ax, ay), (bx, by) = ends
                closed = math.hypot(bx - ax, by - ay) <= 1e-9
                if closed:
                    kind = "circle"
                    points = ((cx, cy),)
                else:
                    kind = "arc"
                    ax, ay = self._uv_from_sw(ax, ay)
                    bx, by = self._uv_from_sw(bx, by)
                    points = ((ax, ay), (bx, by), (cx, cy))
            else:
                kind = "circle"
                points = ((cx, cy),)
        elif ends is not None:
            (ax, ay), (bx, by) = ends
            ax, ay = self._uv_from_sw(ax, ay)
            bx, by = self._uv_from_sw(bx, by)
            points = ((ax, ay), (bx, by))
        return SketchEntityRef(
            index=index, kind=kind, points_m=points, radius_m=radius, construction=construction
        )


    def _segment_dim_points(self, seg: Any) -> tuple[float, float, float, float]:
        circ = self._segment_circle(seg)
        if circ is not None:
            cx, cy, radius = circ
            return cx, cy, cx + radius, cy
        ends = self._segment_xy(seg)
        if ends is None:
            return 0.0, 0.0, 0.0, 0.0
        (ax, ay), (bx, by) = ends
        return ax, ay, bx, by


    def _pair_dim_points(self, a: Any, b: Any) -> tuple[float, float, float, float]:
        ea, eb = self._segment_xy(a), self._segment_xy(b)
        if ea is None or eb is None:
            return 0.0, 0.0, 0.0, 0.0
        ax = (ea[0][0] + ea[1][0]) / 2.0
        ay = (ea[0][1] + ea[1][1]) / 2.0
        bx = (eb[0][0] + eb[1][0]) / 2.0
        by = (eb[0][1] + eb[1][1]) / 2.0
        return ax, ay, bx, by


    def _parallel_line_pair(
        self, segs: list, x1: float, y1: float, x2: float, y2: float,
    ) -> tuple[Any, Any] | None:
        """Polygon opposite edges: two points on parallel lines (e.g. midpoints of opposite sides)."""
        tol = 5e-4  # 0.5 mm
        lines: list[tuple[Any, float, float, float, float, float, float]] = []
        for seg in segs:
            if self._segment_circle(seg) is not None:
                continue
            ends = self._segment_xy(seg)
            if ends is None:
                continue
            (ax, ay), (bx, by) = ends
            if math.hypot(bx - ax, by - ay) <= 1e-12:
                continue
            if self._segment_is_construction(seg):
                continue
            lines.append((seg, ax, ay, bx, by, bx - ax, by - ay))
        near1 = [ln for ln in lines if self._point_line_dist(x1, y1, ln[1], ln[2], ln[3], ln[4]) <= tol]
        near2 = [ln for ln in lines if self._point_line_dist(x2, y2, ln[1], ln[2], ln[3], ln[4]) <= tol]
        uniq: list[tuple[Any, Any]] = []
        seen: set[frozenset[int]] = set()
        for a in near1:
            for b in near2:
                if a[0] is b[0]:
                    continue
                la = math.hypot(a[5], a[6])
                lb = math.hypot(b[5], b[6])
                if abs(a[5] * b[6] - a[6] * b[5]) > 1e-9 * (la * lb + 1e-18):
                    continue
                key = frozenset((id(a[0]), id(b[0])))
                if key in seen:
                    continue
                seen.add(key)
                uniq.append((a[0], b[0]))
        if not uniq:
            return None
        if len(uniq) > 1:
            raise fail(
                "REF_AMBIGUOUS",
                "Multiple parallel pairs match the opposite-edge dimension",
                "Move coordinates closer to the target edge midpoints",
            )
        return uniq[0]


    def add_sketch_dimension(
        self,
        x1_m: float,
        y1_m: float,
        x2_m: float,
        y2_m: float,
        value_m: float,
        entity1: int | None = None,
        entity2: int | None = None,
    ) -> None:
        def _fn() -> None:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            self._require_open_sketch(planar=True)
            if value_m <= 0:
                raise fail("INVALID_ARGUMENT", "Dimension value must be positive", "Pass value_m > 0")
            segs = self._sketch_segments(doc)
            pair = None
            target, diameter = None, False
            sx1, sy1 = self._uv_to_sw(x1_m, y1_m)
            sx2, sy2 = self._uv_to_sw(x2_m, y2_m)
            px1, py1, px2, py2 = sx1, sy1, sx2, sy2
            if entity1 is not None:
                s1 = self._seg_at(segs, entity1)
                if entity2 is None:
                    target, diameter = s1, self._segment_circle(s1) is not None
                    px1, py1, px2, py2 = self._segment_dim_points(s1)
                else:
                    pair = (s1, self._seg_at(segs, entity2))
                    px1, py1, px2, py2 = self._pair_dim_points(s1, pair[1])
            else:
                line_hits = [s for s in segs if self._segment_matches_line(s, sx1, sy1, sx2, sy2)]
                circle_hits = [s for s in segs if self._segment_matches_circle(s, sx1, sy1, sx2, sy2)]
                if line_hits:
                    if len(line_hits) > 1:
                        raise fail("REF_AMBIGUOUS", "Multiple lines share the same endpoints", "Move one line before dimensioning")
                    target, diameter = line_hits[0], False
                elif circle_hits:
                    if len(circle_hits) > 1:
                        raise fail("REF_AMBIGUOUS", "Multiple circles match the same center and radius point", "Use a different point on the circumference")
                    target, diameter = circle_hits[0], True
                else:
                    pair = self._parallel_line_pair(segs, sx1, sy1, sx2, sy2)
                    if pair is None:
                        raise fail(
                            "REF_NOT_FOUND",
                            "No line or circle matches the given endpoints",
                            "Lines: both endpoints; circles: center + rim point; polygon opposite edges: entity1/entity2",
                        )
            self._clear_selection(doc)
            if pair is not None:
                if not pair[0].Select2(False, 0) or not pair[1].Select2(True, 0):
                    raise fail("SELECT_FAILED", "Could not select lines for opposite-edge dimension", "Confirm sketch is in edit mode")
            elif not target.Select2(False, 0):
                raise fail("SELECT_FAILED", "Could not select entity to dimension", "Confirm sketch is in edit mode")
            mx, my = (px1 + px2) / 2.0, (py1 + py2) / 2.0
            dx, dy = px2 - px1, py2 - py1
            old = bool(_get(self.sw, "GetUserPreferenceToggle", _SW_INPUT_DIM_VAL_ON_CREATE))
            self.sw.SetUserPreferenceToggle(_SW_INPUT_DIM_VAL_ON_CREATE, False)
            try:
                if diameter:
                    disp = doc.AddDiameterDimension2(mx + abs(dx) * 0.4, my + abs(dy) * 0.4, 0.0)
                else:
                    disp = doc.AddDimension2(mx - dy * 0.2, my + dx * 0.2, 0.0)
            except Exception as exc:
                raise self._map_error(exc) from exc
            finally:
                self.sw.SetUserPreferenceToggle(_SW_INPUT_DIM_VAL_ON_CREATE, old)
            if disp is None:
                raise fail("SKETCH_OP_FAILED", "Failed to create dimension", "Confirm entities are selected and sketch is not over-defined")
            try:
                dim = _get(disp, "GetDimension")
                _get(dim, "SetSystemValue3", value_m, _SW_SETVALUE_CURRENT_CFG, None)
            except Exception as exc:
                raise self._map_error(exc) from exc

        return self._call(_fn)


    def add_sketch_relation(
        self,
        relation: str,
        entity1: int,
        entity2: int | None = None,
        entity3: int | None = None,
    ) -> None:
        def _fn() -> None:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            self._require_open_sketch(planar=True)
            sg, arity = resolve_sketch_relation(relation)
            segs = self._sketch_segments(doc)
            s1 = self._seg_at(segs, entity1)
            self._clear_selection(doc)
            if arity == 3:
                if entity2 is None or entity3 is None:
                    raise fail(
                        "INVALID_ARGUMENT",
                        f"Constraint {relation!r} requires three entities (including symmetry axis)",
                        "Pass entity1, entity2, and entity3 (symmetry axis line)",
                        relation=relation,
                    )
                s2 = self._seg_at(segs, entity2)
                s3 = self._seg_at(segs, entity3)
                # Real hardware: axis must be construction/centerline or SketchAddConstraints(sgSYMMETRIC) silently adds nothing
                try:
                    s3.ConstructionGeometry = True
                except Exception as exc:
                    raise self._map_error(exc) from exc
                # Select two entities first, axis last
                if not s1.Select2(False, 0):
                    raise fail("SELECT_FAILED", f"Could not select sketch entity {entity1}", "Confirm index matches GetSketchSegments order")
                if not s2.Select2(True, 0):
                    raise fail("SELECT_FAILED", f"Could not select sketch entity {entity2}", "Confirm index matches GetSketchSegments order")
                if not s3.Select2(True, 0):
                    raise fail("SELECT_FAILED", f"Could not select symmetry axis entity {entity3}", "Confirm index matches GetSketchSegments order")
            elif arity == 2:
                if entity2 is None:
                    raise fail(
                        "INVALID_ARGUMENT",
                        f"Constraint {relation!r} requires two entities",
                        "Pass both entity1 and entity2",
                        relation=relation,
                    )
                s2 = self._seg_at(segs, entity2)
                if sg == "sgCOINCIDENT2D":
                    if not self._select_sketch_endpoint_pair(s1, s2):
                        raise fail(
                            "SELECT_FAILED",
                            f"Could not select endpoints of entities {entity1}/{entity2}",
                            "Confirm index matches GetSketchSegments order",
                        )
                elif sg == "sgATMIDDLE":
                    # entity1 provides endpoint entity; entity2 is target line
                    if not self._select_sketch_midpoint_pair(s1, s2):
                        raise fail(
                            "SELECT_FAILED",
                            f"Could not select midpoint constraint: entity {entity1} endpoint / line {entity2}",
                            "entity1 is line/arc providing endpoint; entity2 is line to receive midpoint",
                        )
                else:
                    if not s1.Select2(False, 0):
                        raise fail("SELECT_FAILED", f"Could not select sketch entity {entity1}", "Confirm index matches GetSketchSegments order")
                    if not s2.Select2(True, 0):
                        raise fail("SELECT_FAILED", f"Could not select sketch entity {entity2}", "Confirm index matches GetSketchSegments order")
            else:
                if not s1.Select2(False, 0):
                    raise fail("SELECT_FAILED", f"Could not select sketch entity {entity1}", "Confirm index matches GetSketchSegments order")
            try:
                doc.SketchAddConstraints(sg)
            except Exception as exc:
                raise self._map_error(exc) from exc

        return self._call(_fn)


    def list_sketch_entities(self, sketch: str | None = None) -> list[SketchEntityRef]:
        def _fn() -> list[SketchEntityRef]:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            sk = self._sketch_dispatch(doc, sketch)
            segs = list(_get(sk, "GetSketchSegments") or ())
            return [self._entity_ref_from_seg(i, seg) for i, seg in enumerate(segs)]

        return self._call(_fn)
