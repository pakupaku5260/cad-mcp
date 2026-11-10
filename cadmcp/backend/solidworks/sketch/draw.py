"""COM backend · sketch · drawing (line/arc/spline/polygon/rectangle/circle).

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

from cadmcp.backend.protocol.constants import PLANE_ALIASES
from cadmcp.backend.protocol.geometry_engine import (
    polygon_vertex_point_m,
    regular_polygon_lines,
)
from cadmcp.backend.protocol.models import SketchLineRef
from cadmcp.backend.protocol.parsers import normalize_spline_points
from cadmcp.errors import CadMcpError, fail

from .._helpers import _get

log = logging.getLogger(__name__)

class SketchDrawMixin:
    """Sketch drawing (line/arc/spline/polygon/rectangle/circle)."""

    def _uv_to_sw(self, u: float, v: float) -> tuple[float, float]:
        """Tool sketch coordinates -> SolidWorks sketch space.

        Top Plane: CreateLine +Y maps to model -Z. After flipping Y, tool +Y is model +Z
        (matches fake revolve axis and cone-tip-outward usage).
        """
        plane = self._sketch_plane or ""
        root = self._plane_uv_root.get(plane, plane)
        if root == "Top Plane" or root in PLANE_ALIASES.get("Top Plane", ()):
            return float(u), -float(v)
        return float(u), float(v)


    def _uv_from_sw(self, u: float, v: float) -> tuple[float, float]:
        return self._uv_to_sw(u, v)


    def sketch_line(
        self,
        x1_m: float,
        y1_m: float,
        x2_m: float,
        y2_m: float,
        z1_m: float = 0.0,
        z2_m: float = 0.0,
    ) -> None:
        def _fn() -> None:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            if not self._sketch_open:
                raise fail("NO_ACTIVE_SKETCH", "No sketch is open", "Call begin_sketch first")
            if not self._sketch_3d and (z1_m != 0.0 or z2_m != 0.0):
                raise fail(
                    "INVALID_ARGUMENT",
                    "Planar sketch lines cannot take z",
                    "z1/z2 are for start_sketch(plane=3D) 3D sketches only",
                )
            sm = doc.SketchManager
            try:
                if self._sketch_3d:
                    res = sm.CreateLine(x1_m, y1_m, z1_m, x2_m, y2_m, z2_m)
                else:
                    x1s, y1s = self._uv_to_sw(x1_m, y1_m)
                    x2s, y2s = self._uv_to_sw(x2_m, y2_m)
                    res = sm.CreateLine(x1s, y1s, 0, x2s, y2s, 0)
                if res is None:
                    raise fail("SKETCH_OP_FAILED", "Failed to create line (coincident endpoints?)", "Use two distinct points")
            except Exception as exc:
                raise self._map_error(exc) from exc
            self._sketch_entities += 1

        return self._call(_fn)


    def sketch_arc(
        self,
        x1_m: float,
        y1_m: float,
        x2_m: float,
        y2_m: float,
        x3_m: float | None = None,
        y3_m: float | None = None,
        cx_m: float | None = None,
        cy_m: float | None = None,
        ccw: bool = True,
        z1_m: float = 0.0,
        z2_m: float = 0.0,
        z3_m: float = 0.0,
        cz_m: float = 0.0,
    ) -> None:
        def _fn() -> None:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            if not self._sketch_open:
                raise fail("NO_ACTIVE_SKETCH", "No sketch is open", "Call begin_sketch first")
            z_used = (z1_m != 0.0 or z2_m != 0.0 or z3_m != 0.0 or cz_m != 0.0)
            if not self._sketch_3d and z_used:
                raise fail(
                    "INVALID_ARGUMENT",
                    "Planar sketch arcs cannot take z",
                    "z1/z2/z3/cz are for start_sketch(plane=3D) 3D sketches only",
                )
            if self._sketch_3d:
                self._require_open_sketch(planar=False)
            else:
                self._require_open_sketch(planar=True)
            sm = doc.SketchManager
            try:
                if self._sketch_3d:
                    if cx_m is not None or cy_m is not None:
                        if cx_m is None or cy_m is None:
                            raise fail("INVALID_ARGUMENT", "Center mode requires both cx and cy", "Provide center coordinates")
                        direction = 1 if ccw else -1
                        res = sm.CreateArc(
                            float(cx_m), float(cy_m), float(cz_m),
                            float(x1_m), float(y1_m), float(z1_m),
                            float(x2_m), float(y2_m), float(z2_m),
                            direction,
                        )
                    else:
                        if x3_m is None or y3_m is None:
                            raise fail(
                                "INVALID_ARGUMENT",
                                "Three-point arc requires x3,y3 (end point)",
                                "Pass start, point on arc, end; or use cx,cy + start/end",
                            )
                        # Create3PointArc(start, end, through) — same parameter order as planar path
                        res = sm.Create3PointArc(
                            float(x1_m), float(y1_m), float(z1_m),
                            float(x3_m), float(y3_m), float(z3_m),
                            float(x2_m), float(y2_m), float(z2_m),
                        )
                else:
                    x1s, y1s = self._uv_to_sw(x1_m, y1_m)
                    x2s, y2s = self._uv_to_sw(x2_m, y2_m)
                    if cx_m is not None or cy_m is not None:
                        if cx_m is None or cy_m is None:
                            raise fail("INVALID_ARGUMENT", "Center mode requires both cx and cy", "Provide center coordinates")
                        direction = 1 if ccw else -1
                        cxs, cys = self._uv_to_sw(cx_m, cy_m)
                        res = sm.CreateArc(cxs, cys, 0.0, x1s, y1s, 0.0, x2s, y2s, 0.0, direction)
                    else:
                        if x3_m is None or y3_m is None:
                            raise fail(
                                "INVALID_ARGUMENT",
                                "Three-point arc requires x3,y3 (end point)",
                                "Pass start, point on arc, end; or use cx,cy + start/end",
                            )
                        x3s, y3s = self._uv_to_sw(x3_m, y3_m)
                        res = sm.Create3PointArc(x1s, y1s, 0.0, x3s, y3s, 0.0, x2s, y2s, 0.0)
            except CadMcpError:
                raise
            except Exception as exc:
                raise self._map_error(exc) from exc
            if res is None:
                raise fail(
                    "SKETCH_OP_FAILED",
                    "Failed to create arc (collinear points or zero radius?)",
                    "Check points are not collinear and radius is positive",
                )
            self._sketch_entities = len(self._sketch_segments(doc))

        return self._call(_fn)


    def sketch_spline(
        self, points_m: list[tuple[float, float, float]], closed: bool = False
    ) -> None:
        def _fn() -> None:
            import pythoncom
            from win32com.client import VARIANT

            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            pts = normalize_spline_points(list(points_m), closed)
            z_used = any(abs(z) > 0.0 for _, _, z in pts)
            if self._sketch_3d:
                self._require_open_sketch(planar=False)
            else:
                if z_used:
                    raise fail(
                        "INVALID_ARGUMENT",
                        "Planar sketch splines cannot take z",
                        "z is for start_sketch(plane=3D) 3D sketches only",
                    )
                self._require_open_sketch(planar=True)
            data: list[float] = []
            if self._sketch_3d:
                for x, y, z in pts:
                    data.extend([float(x), float(y), float(z)])
            else:
                for u, v, _z in pts:
                    xs, ys = self._uv_to_sw(u, v)
                    data.extend([xs, ys, 0.0])
            arr = VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, data)
            sm = doc.SketchManager
            try:
                res = sm.CreateSpline2(arr, True)
            except Exception as exc:
                raise self._map_error(exc) from exc
            if res is None:
                raise fail("SKETCH_OP_FAILED", "Spline creation failed", "Check point count and collinearity")
            self._sketch_entities = len(self._sketch_segments(doc))

        return self._call(_fn)


    def sketch_polygon(
        self,
        sides: int,
        radius_or_distance: float,
        polygon_type: str = "inscribed",
        cx_m: float = 0.0,
        cy_m: float = 0.0,
        cz_m: float = 0.0,
    ) -> list[SketchLineRef]:
        def _fn() -> list[SketchLineRef]:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            if not self._sketch_open:
                raise fail("NO_ACTIVE_SKETCH", "No sketch is open", "Call begin_sketch first")
            if not self._sketch_3d and cz_m != 0.0:
                raise fail(
                    "INVALID_ARGUMENT",
                    "Planar sketch polygons cannot take cz",
                    "cz is for start_sketch(plane=3D) 3D sketches only",
                )
            if self._sketch_3d:
                self._require_open_sketch(planar=False)
            else:
                self._require_open_sketch(planar=True)
            if sides < 3:
                raise fail("INVALID_ARGUMENT", "Polygon must have sides >= 3", "Pass sides >= 3")
            if radius_or_distance <= 0:
                raise fail("INVALID_ARGUMENT", "Radius/distance must be positive", "Pass radius_or_distance > 0")
            sm = doc.SketchManager
            before = len(self._sketch_segments(doc))
            try:
                if self._sketch_3d:
                    # CreatePolygon RPC-faults in 3D sketch and edges are non-coplanar when cz!=0; synthesize with CreateLine.
                    for x0, y0, x1, y1 in regular_polygon_lines(
                        sides, radius_or_distance, polygon_type, cx_m, cy_m
                    ):
                        res = sm.CreateLine(
                            float(x0), float(y0), float(cz_m),
                            float(x1), float(y1), float(cz_m),
                        )
                        if res is None:
                            raise fail("SKETCH_OP_FAILED", "Failed to create polygon", "Check edge count and radius")
                else:
                    # Real hardware treats construction point as vertex; inscribed unchanged on opposite edge;
                    # circumscribed uses circumradius.
                    xp, yp = polygon_vertex_point_m(sides, radius_or_distance, polygon_type)
                    cxs, cys = self._uv_to_sw(cx_m, cy_m)
                    vxs, vys = self._uv_to_sw(cx_m + xp, cy_m + yp)
                    res = sm.CreatePolygon(
                        cxs, cys, 0.0, vxs, vys, 0.0, sides, True,
                    )
                    if not res:
                        raise fail("SKETCH_OP_FAILED", "Failed to create polygon", "Check edge count and radius")
                    self._drop_construction_segments(doc)
            except Exception as exc:
                raise self._map_error(exc) from exc
            segs = self._sketch_segments(doc)
            self._sketch_entities = len(segs)
            return [r for r in self._line_refs_from_segments(segs) if r.index >= before]

        return self._call(_fn)


    def draw_rectangle(
        self,
        x1_m: float,
        y1_m: float,
        x2_m: float,
        y2_m: float,
        z1_m: float = 0.0,
        z2_m: float = 0.0,
    ) -> None:
        def _fn() -> None:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")

            if not self._sketch_open:
                raise fail("NO_ACTIVE_SKETCH", "No sketch is open", "Call begin_sketch first")
            if not self._sketch_3d and (z1_m != 0.0 or z2_m != 0.0):
                raise fail(
                    "INVALID_ARGUMENT",
                    "Planar sketch rectangles cannot take z",
                    "z1/z2 are for start_sketch(plane=3D) 3D sketches only",
                )
            if x1_m == x2_m and y1_m == y2_m and z1_m == z2_m:
                raise fail(
                    "SKETCH_OP_FAILED",
                    f"Degenerate rectangle (identical corners): ({x1_m}, {y1_m}, {z1_m})",
                    "Diagonal corners must not coincide",
                )
            if not self._sketch_3d and (x1_m == x2_m or y1_m == y2_m):
                raise fail(
                    "SKETCH_OP_FAILED",
                    f"Degenerate rectangle (zero width or height): ({x1_m}, {y1_m}) -> ({x2_m}, {y2_m})",
                    "Diagonal corners must differ in both x and y",
                )

            try:
                sm = doc.SketchManager
                if self._sketch_3d:
                    res = sm.CreateCornerRectangle(
                        float(x1_m), float(y1_m), float(z1_m),
                        float(x2_m), float(y2_m), float(z2_m),
                    )
                else:
                    x1s, y1s = self._uv_to_sw(x1_m, y1_m)
                    x2s, y2s = self._uv_to_sw(x2_m, y2_m)
                    res = sm.CreateCornerRectangle(x1s, y1s, 0, x2s, y2s, 0)
            except Exception as exc:
                raise self._map_error(exc) from exc
            if res is None:
                raise fail("SKETCH_OP_FAILED", "CreateCornerRectangle returned None", "Confirm sketch edit mode is active")

            self._sketch_entities += 1

        self._call(_fn)


    def draw_circle(
        self, cx_m: float, cy_m: float, radius_m: float, cz_m: float = 0.0
    ) -> None:
        def _fn() -> None:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")

            if not self._sketch_open:
                raise fail("NO_ACTIVE_SKETCH", "No sketch is open", "Call begin_sketch first")
            if not self._sketch_3d and cz_m != 0.0:
                raise fail(
                    "INVALID_ARGUMENT",
                    "Planar sketch circles cannot take cz",
                    "cz is for start_sketch(plane=3D) 3D sketches only",
                )
            if radius_m <= 0:
                raise fail(
                    "SKETCH_OP_FAILED",
                    f"Circle radius must be positive: {radius_m}",
                    "Pass radius > 0",
                )

            try:
                sm = doc.SketchManager
                if self._sketch_3d:
                    res = sm.CreateCircleByRadius(
                        float(cx_m), float(cy_m), float(cz_m), float(radius_m)
                    )
                else:
                    cxs, cys = self._uv_to_sw(cx_m, cy_m)
                    rxs, rys = self._uv_to_sw(cx_m + radius_m, cy_m)
                    try:
                        res = sm.CreateCircleByRadius(cxs, cys, 0, radius_m)
                    except Exception:
                        res = sm.CreateCircle(cxs, cys, 0, rxs, rys, 0)
            except Exception as exc:
                raise self._map_error(exc) from exc
            if res is None:
                raise fail("SKETCH_OP_FAILED", "Failed to create circle", "Confirm sketch edit mode is active")

            self._sketch_entities += 1

        self._call(_fn)


    def _drop_construction_segments(self, doc: Any) -> None:
        segs = self._sketch_segments(doc)
        self._clear_selection(doc)
        n = 0
        for seg in segs:
            if not self._segment_is_construction(seg):
                continue
            try:
                if seg.Select2(n > 0, 0):
                    n += 1
            except Exception:
                log.debug("Failed to select construction entity: %s", traceback.format_exc())
        if n == 0:
            return
        try:
            _get(doc, "EditDelete")
        except Exception:
            try:
                _get(_get(doc, "Extension"), "DeleteSelection2", 0)
            except Exception:
                log.debug("Failed to delete polygon construction circle: %s", traceback.format_exc())
        self._clear_selection(doc)


    def _line_refs_from_segments(self, segs: list) -> list[SketchLineRef]:
        out: list[SketchLineRef] = []
        for i, seg in enumerate(segs):
            if self._segment_circle(seg) is not None or self._segment_is_construction(seg):
                continue
            ends = self._segment_xy(seg)
            if ends is None:
                continue
            (ax, ay), (bx, by) = ends
            if math.hypot(bx - ax, by - ay) <= 1e-12:
                continue
            ax, ay = self._uv_from_sw(ax, ay)
            bx, by = self._uv_from_sw(bx, by)
            out.append(SketchLineRef(index=i, x0_m=ax, y0_m=ay, x1_m=bx, y1_m=by))
        return out
