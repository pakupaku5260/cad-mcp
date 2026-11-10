"""Fake backend · sketch domain（S8d）。

S8d: 34 methods (lifecycle + draw + dimensions/constraints + edit/solve + helpers).

Dependencies (self, MRO):
- `_enter` / `_require_doc`（FakeBackend）
- `_resolve_plane_name` / `_plane_names` (FakePlaneAxisMixin, S8d round 2; from FakeBackend)
- `_put_sketch_dim` (FakeBackend, pre-S8g)

Imports:
- `cadmcp.backend.protocol.models`（SketchInfo / SketchLineRef / SketchEntityRef / SketchSolveStatus）
- `cadmcp.backend.protocol.geometry_engine`（regular_polygon_lines）
- `cadmcp.backend.protocol.parsers`（normalize_spline_points / is_3d_sketch_plane / resolve_sketch_relation / line_matches_ends / circle_matches_center_rim）
- `cadmcp.errors`（fail）
- `._engine`（_arc_from_center / _arc_from_three_points / _reflect_xy）
- `._state`（_Doc / _Sketch）
"""
from __future__ import annotations

import math

from cadmcp.backend.protocol.geometry_engine import (
    circle_matches_center_rim,
    line_matches_ends,
    regular_polygon_lines,
)
from cadmcp.backend.protocol.models import (
    SketchEntityRef,
    SketchInfo,
    SketchLineRef,
    SketchSolveStatus,
)
from cadmcp.backend.protocol.parsers import (
    is_3d_sketch_plane,
    normalize_spline_points,
    resolve_sketch_relation,
)
from cadmcp.errors import fail

from ._engine import _reflect_xy
from ._state import _arc_from_center, _arc_from_three_points, _Doc, _Sketch


class FakeSketchMixin:
    """sketch domain (S8d: 34 methods)."""

    def _init_state(self) -> None:
        pass  # State owned by FakeBackend._init_state

    # ---------- Lifecycle ----------

    def begin_sketch(self, plane: str) -> None:
        self._enter("begin_sketch", plane=plane)
        doc = self._require_doc()
        if doc.open_sketch is not None:
            raise fail(
                "SKETCH_OP_FAILED",
                f"Sketch {doc.open_sketch.name or ''} is already open; cannot open a second",
                "Call end_sketch to close the current sketch before starting a new one",
            )
        if is_3d_sketch_plane(plane):
            resolved = "3D"
        else:
            resolved = self._resolve_plane_name(doc, plane)
            if resolved is None:
                raise fail(
                    "SKETCH_NOT_FOUND",
                    f"Reference plane does not exist：{plane!r}",
                    f"Available reference planes: {', '.join(self._plane_names(doc))} (use list_planes)",
                    requested=plane,
                )
        doc.sketch_seq += 1
        doc.open_sketch = _Sketch(plane=resolved, name=f"Sketch{doc.sketch_seq}")
        doc.modified = True

    def end_sketch(self) -> SketchInfo:
        self._enter("end_sketch")
        doc = self._require_doc()
        sk = doc.open_sketch
        if sk is None:
            raise fail(
                "NO_ACTIVE_SKETCH",
                "No sketch is open",
                "Call start_sketch on a reference plane and draw a profile",
            )
        if sk not in doc.ended_sketches:
            doc.ended_sketches.append(sk)
        doc.open_sketch = None
        doc.pending_sketch = sk
        doc.modified = True
        return SketchInfo(plane=sk.plane, entity_count=len(sk.entities), name=sk.name)

    def active_sketch(self) -> SketchInfo | None:
        self._enter("active_sketch")
        if self._doc is None or self._doc.open_sketch is None:
            return None
        sk = self._doc.open_sketch
        return SketchInfo(plane=sk.plane, entity_count=len(sk.entities), name=sk.name)

    # ---------- Draw ----------

    def draw_rectangle(
        self,
        x1_m: float,
        y1_m: float,
        x2_m: float,
        y2_m: float,
        z1_m: float = 0.0,
        z2_m: float = 0.0,
    ) -> None:
        self._enter(
            "draw_rectangle",
            x1=x1_m,
            y1=y1_m,
            x2=x2_m,
            y2=y2_m,
            z1=z1_m,
            z2=z2_m,
        )
        sk = self._open_sketch()
        three_d = is_3d_sketch_plane(sk.plane)
        if not three_d and (z1_m != 0.0 or z2_m != 0.0):
            raise fail(
                "INVALID_ARGUMENT",
                "Planar sketches cannot pass z for rectangles",
                "z1/z2 only for 3D sketches via start_sketch(plane=3D)",
            )
        if x1_m == x2_m and y1_m == y2_m and z1_m == z2_m:
            raise fail(
                "SKETCH_OP_FAILED",
                f"Rectangle degenerate (identical corners): ({x1_m}, {y1_m}, {z1_m})",
                "Diagonal corners cannot coincide",
            )
        if not three_d and (x1_m == x2_m or y1_m == y2_m):
            raise fail(
                "SKETCH_OP_FAILED",
                f"Rectangle degenerate (zero width or height): ({x1_m}, {y1_m}) → ({x2_m}, {y2_m})",
                "Diagonal corners must differ in both x and y",
            )
        sk.entities.append(
            {
                "kind": "rect",
                "x0": x1_m,
                "y0": y1_m,
                "z0": z1_m,
                "x1": x2_m,
                "y1": y2_m,
                "z1": z2_m,
            }
        )
        self._doc.modified = True  # type: ignore[union-attr]

    def draw_circle(
        self, cx_m: float, cy_m: float, radius_m: float, cz_m: float = 0.0
    ) -> None:
        self._enter("draw_circle", cx=cx_m, cy=cy_m, r=radius_m, cz=cz_m)
        sk = self._open_sketch()
        three_d = is_3d_sketch_plane(sk.plane)
        if not three_d and cz_m != 0.0:
            raise fail(
                "INVALID_ARGUMENT",
                "Planar sketches cannot pass cz for circles",
                "cz only for 3D sketches via start_sketch(plane=3D)",
            )
        if radius_m <= 0:
            raise fail(
                "SKETCH_OP_FAILED",
                f"Circle radius must be positive: {radius_m}",
                "Pass radius > 0",
            )
        sk.entities.append(
            {"kind": "circle", "cx": cx_m, "cy": cy_m, "cz": cz_m, "r": radius_m}
        )
        self._doc.modified = True  # type: ignore[union-attr]

    def sketch_line(
        self,
        x1_m: float,
        y1_m: float,
        x2_m: float,
        y2_m: float,
        z1_m: float = 0.0,
        z2_m: float = 0.0,
    ) -> None:
        self._enter("sketch_line", x1=x1_m, y1=y1_m, x2=x2_m, y2=y2_m, z1=z1_m, z2=z2_m)
        sk = self._open_sketch()
        three_d = is_3d_sketch_plane(sk.plane)
        if not three_d and (z1_m != 0.0 or z2_m != 0.0):
            raise fail(
                "INVALID_ARGUMENT",
                "Planar sketches cannot pass z for lines",
                "z1/z2 only for 3D sketches via start_sketch(plane=3D)",
            )
        if x1_m == x2_m and y1_m == y2_m and z1_m == z2_m:
            raise fail("SKETCH_OP_FAILED", "Line degenerates (identical endpoints)", "Use two distinct points")
        sk.entities.append(
            {
                "kind": "line",
                "x0": x1_m,
                "y0": y1_m,
                "z0": z1_m,
                "x1": x2_m,
                "y1": y2_m,
                "z1": z2_m,
            }
        )
        self._doc.modified = True  # type: ignore[union-attr]

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
        self._enter(
            "sketch_arc",
            x1=x1_m, y1=y1_m, x2=x2_m, y2=y2_m, x3=x3_m, y3=y3_m,
            cx=cx_m, cy=cy_m, ccw=ccw, z1=z1_m, z2=z2_m, z3=z3_m, cz=cz_m,
        )
        doc = self._require_doc()
        if doc.open_sketch is None:
            raise fail("NO_ACTIVE_SKETCH", "No sketch is open; cannot draw", "Call start_sketch and pick a reference plane")
        is_3d = is_3d_sketch_plane(doc.open_sketch.plane)
        z_used = (z1_m != 0.0 or z2_m != 0.0 or z3_m != 0.0 or cz_m != 0.0)
        if not is_3d and z_used:
            raise fail(
                "INVALID_ARGUMENT",
                "Planar sketches cannot pass z for arcs",
                "z1/z2/z3/cz only for 3D sketches via start_sketch(plane=3D)",
            )
        sk = doc.open_sketch
        if cx_m is not None or cy_m is not None:
            if cx_m is None or cy_m is None:
                raise fail("INVALID_ARGUMENT", "Center mode requires both cx and cy", "Provide center coordinates")
            ent = _arc_from_center(cx_m, cy_m, x1_m, y1_m, x2_m, y2_m, ccw)
            if is_3d:
                ent.update({"z0": z1_m, "z1": z2_m, "cz": cz_m})
            sk.entities.append(ent)
        else:
            if x3_m is None or y3_m is None:
                raise fail(
                    "INVALID_ARGUMENT",
                    "Three-point arc needs x3,y3 (end point)",
                    "Pass start (x1,y1), on-arc (x2,y2), end (x3,y3); or cx,cy with start/end",
                )
            if is_3d and (abs(z1_m - z2_m) > 1e-12 or abs(z1_m - z3_m) > 1e-12):
                # Non-XY coplanar: canned stores three points, skips planar circle math
                sk.entities.append(
                    {
                        "kind": "arc",
                        "x0": x1_m, "y0": y1_m, "z0": z1_m,
                        "xm": x2_m, "ym": y2_m, "zm": z2_m,
                        "x1": x3_m, "y1": y3_m, "z1": z3_m,
                        "r": 0.0, "sweep": 0.0, "cx": x1_m, "cy": y1_m,
                    }
                )
            else:
                ent = _arc_from_three_points(x1_m, y1_m, x2_m, y2_m, x3_m, y3_m)
                if is_3d:
                    ent.update({"z0": z1_m, "zm": z2_m, "z1": z3_m})
                sk.entities.append(ent)
        self._doc.modified = True  # type: ignore[union-attr]

    def sketch_spline(
        self, points_m: list[tuple[float, float, float]], closed: bool = False
    ) -> None:
        self._enter("sketch_spline", points=points_m, closed=closed)
        doc = self._require_doc()
        if doc.open_sketch is None:
            raise fail(
                "NO_ACTIVE_SKETCH",
                "No sketch is open; cannot draw",
                "Call start_sketch and pick a reference plane",
            )
        is_3d = is_3d_sketch_plane(doc.open_sketch.plane)
        pts = normalize_spline_points(list(points_m), closed)
        z_used = any(abs(z) > 0.0 for _, _, z in pts)
        if not is_3d and z_used:
            raise fail(
                "INVALID_ARGUMENT",
                "Planar sketches cannot pass z for splines",
                "z only for 3D sketches via start_sketch(plane=3D)",
            )
        sk = self._open_sketch(planar=not is_3d)
        sk.entities.append({"kind": "spline", "points": pts, "closed": bool(closed)})
        self._doc.modified = True  # type: ignore[union-attr]

    def sketch_polygon(
        self,
        sides: int,
        radius_or_distance: float,
        polygon_type: str = "inscribed",
        cx_m: float = 0.0,
        cy_m: float = 0.0,
        cz_m: float = 0.0,
    ) -> list[SketchLineRef]:
        self._enter(
            "sketch_polygon",
            sides=sides,
            radius_or_distance=radius_or_distance,
            polygon_type=polygon_type,
            cx=cx_m,
            cy=cy_m,
            cz=cz_m,
        )
        doc = self._require_doc()
        if doc.open_sketch is None:
            raise fail(
                "NO_ACTIVE_SKETCH",
                "No sketch is open; cannot draw",
                "Call start_sketch and pick a reference plane",
            )
        is_3d = is_3d_sketch_plane(doc.open_sketch.plane)
        if not is_3d and cz_m != 0.0:
            raise fail(
                "INVALID_ARGUMENT",
                "Planar sketches cannot pass cz for polygons",
                "cz only for 3D sketches via start_sketch(plane=3D)",
            )
        sk = self._open_sketch(planar=not is_3d)
        if sides < 3:
            raise fail("INVALID_ARGUMENT", "Polygon must have sides >= 3", "Pass sides >= 3")
        if radius_or_distance <= 0:
            raise fail("INVALID_ARGUMENT", "Radius/distance must be positive", "Pass radius_or_distance > 0")
        group = f"poly{sum(1 for e in sk.entities if e.get('group'))}"
        out: list[SketchLineRef] = []
        for x0, y0, x1, y1 in regular_polygon_lines(
            sides, radius_or_distance, polygon_type, cx_m, cy_m
        ):
            idx = len(sk.entities)
            ent: dict = {
                "kind": "line",
                "x0": x0,
                "y0": y0,
                "x1": x1,
                "y1": y1,
                "group": group,
            }
            if is_3d:
                ent["z0"] = cz_m
                ent["z1"] = cz_m
            sk.entities.append(ent)
            out.append(SketchLineRef(index=idx, x0_m=x0, y0_m=y0, x1_m=x1, y1_m=y1))
        self._doc.modified = True  # type: ignore[union-attr]
        return out

    # ---------- Dimensions / constraints ----------

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
        self._enter(
            "add_sketch_dimension", x1=x1_m, y1=y1_m, x2=x2_m, y2=y2_m, value=value_m,
            entity1=entity1, entity2=entity2,
        )
        sk = self._open_sketch(planar=True)
        if value_m <= 0:
            raise fail("INVALID_ARGUMENT", "Dimension value must be positive", "Pass value_m > 0")
        target: dict | None = None
        if entity1 is not None:
            target = self._dimension_by_index(sk, entity1, entity2, value_m)
        else:
            line = self._line_by_ends(sk, x1_m, y1_m, x2_m, y2_m, missing_ok=True)
            if line is not None:
                dx, dy = line["x1"] - line["x0"], line["y1"] - line["y0"]
                length = math.hypot(dx, dy)
                if length <= 0:
                    raise fail("SKETCH_OP_FAILED", "Line length is zero; cannot dimension", "Use two distinct points")
                scale = value_m / length
                line["x1"] = line["x0"] + dx * scale
                line["y1"] = line["y0"] + dy * scale
                line["dimensioned"] = True
                target = line
            else:
                circle = self._circle_by_center_rim(sk, x1_m, y1_m, x2_m, y2_m, missing_ok=True)
                if circle is not None:
                    circle["r"] = value_m / 2.0
                    circle["dimensioned"] = True
                    target = circle
                elif not self._across_flats_from_points(sk, x1_m, y1_m, x2_m, y2_m, value_m):
                    raise fail(
                        "REF_NOT_FOUND",
                        "No line or circle matching the given endpoints",
                        "Lines use both endpoints; circles use center + point on circumference; polygon opposite edges use entity indexes or parallel edge midpoints",
                    )
        if target is not None:
            self._put_sketch_dim(sk, target, value_m)
        self._doc.modified = True  # type: ignore[union-attr]

    def add_sketch_relation(
        self,
        relation: str,
        entity1: int,
        entity2: int | None = None,
        entity3: int | None = None,
    ) -> None:
        self._enter(
            "add_sketch_relation",
            relation=relation,
            entity1=entity1,
            entity2=entity2,
            entity3=entity3,
        )
        sk = self._open_sketch(planar=True)
        sg, arity = resolve_sketch_relation(relation)
        e1 = self._sketch_seg(sk, entity1)
        e2 = None
        e3 = None
        if arity == 3:
            if entity2 is None or entity3 is None:
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Relation {relation!r} needs three entities (including symmetry axis)",
                    "Pass entity1, entity2, and entity3 (symmetry axis line)",
                    relation=relation,
                )
            e2 = self._sketch_seg(sk, entity2)
            e3 = self._sketch_seg(sk, entity3)
            if sg == "sgSYMMETRIC":
                if e3["kind"] != "line":
                    raise fail(
                        "SKETCH_OP_FAILED",
                        "Symmetric relation entity3 must be a line (symmetry axis)",
                        "Draw the axis with sketch_line before adding symmetry",
                    )
                if e1["kind"] != "line" or e2["kind"] != "line":
                    raise fail(
                        "SKETCH_OP_FAILED",
                        "Symmetric relation only supports two lines about an axis",
                        "Draw entity1/entity2 with sketch_line",
                    )
                e3["construction"] = True
                self._mirror_line_about_axis(e2, e1, e3)
        elif arity == 2:
            if entity2 is None:
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Relation {relation!r} needs two entities",
                    "Pass both entity1 and entity2",
                    relation=relation,
                )
            e2 = self._sketch_seg(sk, entity2)
            if sg == "sgPARALLEL2D":
                if e1["kind"] != "line" or e2["kind"] != "line":
                    raise fail("SKETCH_OP_FAILED", "This relation currently supports lines only", "Draw with sketch_line before adding the relation")
                self._align_line_dir(e2, e1)
            elif sg == "sgPERPENDICULAR2D":
                if e1["kind"] != "line" or e2["kind"] != "line":
                    raise fail("SKETCH_OP_FAILED", "This relation currently supports lines only", "Draw with sketch_line before adding the relation")
                self._perp_line_dir(e2, e1)
            elif sg == "sgTANGENT":
                kinds = {e1["kind"], e2["kind"]}
                if "line" not in kinds or not kinds.intersection({"circle", "arc"}):
                    raise fail(
                        "SKETCH_OP_FAILED",
                        "Tangent relation needs one line and one circle or arc",
                        "sketch_line first, then sketch_circle / sketch_arc",
                    )
            elif sg == "sgCONCENTRIC":
                curved = {"circle", "arc"}
                if e1["kind"] not in curved or e2["kind"] not in curved:
                    raise fail("SKETCH_OP_FAILED", "Concentric relation needs two circles or arcs", "Use sketch_circle / sketch_arc")
                e2["cx"], e2["cy"] = e1["cx"], e1["cy"]
            elif sg == "sgSAMELENGTH":
                if e1["kind"] != "line" or e2["kind"] != "line":
                    raise fail("SKETCH_OP_FAILED", "Equal length needs two lines", "Draw with sketch_line before adding the relation")
                self._equal_line_len(e2, e1)
            elif sg == "sgCOINCIDENT2D":
                if e1["kind"] in {"line", "arc"} and e2["kind"] in {"line", "arc"}:
                    self._snap_sketch_endpoints(e1, e2)
            elif sg == "sgCOLINEAR":
                if e1["kind"] != "line" or e2["kind"] != "line":
                    raise fail("SKETCH_OP_FAILED", "Colinear relation needs two lines", "Draw with sketch_line before adding the relation")
                self._colinear_lines(e2, e1)
            elif sg == "sgATMIDDLE":
                if e2["kind"] != "line":
                    raise fail(
                        "SKETCH_OP_FAILED",
                        "Midpoint relation entity2 must be a line",
                        "entity1 supplies an endpoint; entity2 is the line being mid-pointed",
                    )
                if e1["kind"] not in {"line", "arc"}:
                    raise fail(
                        "SKETCH_OP_FAILED",
                        "Midpoint relation entity1 must be a line or arc",
                        "Draw with sketch_line / sketch_arc before adding the relation",
                    )
                self._snap_to_midpoint(e1, e2)
        else:
            if sg == "sgFIXED":
                if e1["kind"] not in {"line", "arc", "circle", "rect", "spline"}:
                    raise fail("SKETCH_OP_FAILED", "Fixed relation needs a sketch entity", "Draw an entity first, then fixed")
            else:
                if e1["kind"] != "line":
                    raise fail("SKETCH_OP_FAILED", "This relation currently supports lines only", "Draw with sketch_line before adding the relation")
                if sg == "sgHORIZONTAL2D":
                    e1["y1"] = e1["y0"]
                elif sg == "sgVERTICAL2D":
                    e1["x1"] = e1["x0"]
        e1.setdefault("relations", []).append(sg)
        if arity >= 2 and e2 is not None:
            e2.setdefault("relations", []).append(sg)
        if arity >= 3 and e3 is not None:
            e3.setdefault("relations", []).append(sg)
        self._doc.modified = True  # type: ignore[union-attr]

    # ---------- Query / edit ----------

    def _sketch_by_name(self, doc: _Doc, sketch: str | None) -> _Sketch:
        if sketch is None:
            if doc.open_sketch is not None:
                return doc.open_sketch
            raise fail(
                "NO_ACTIVE_SKETCH",
                "No sketch is open",
                "Call start_sketch first, or pass sketch=Sketch1",
            )
        if doc.open_sketch is not None and doc.open_sketch.name == sketch:
            return doc.open_sketch
        for sk in doc.ended_sketches:
            if sk.name == sketch:
                return sk
        raise fail(
            "FEATURE_NOT_FOUND",
            f"Sketch not found {sketch!r}",
            "Use name from end_sketch or list_features",
            requested=sketch,
        )

    @staticmethod
    def _entity_ref(index: int, ent: dict) -> SketchEntityRef:
        kind = str(ent.get("kind") or "line")
        radius = float(ent["r"]) if "r" in ent else None
        if kind == "line":
            points = ((float(ent["x0"]), float(ent["y0"])), (float(ent["x1"]), float(ent["y1"])))
        elif kind == "circle":
            points = ((float(ent["cx"]), float(ent["cy"])),)
        elif kind == "arc":
            points = (
                (float(ent["x0"]), float(ent["y0"])),
                (float(ent["x1"]), float(ent["y1"])),
                (float(ent["cx"]), float(ent["cy"])),
            )
        elif kind == "rect":
            points = ((float(ent["x0"]), float(ent["y0"])), (float(ent["x1"]), float(ent["y1"])))
        elif kind == "spline":
            raw = ent.get("points") or ()
            points = tuple((float(p[0]), float(p[1])) for p in raw)
        else:
            points = ()
        return SketchEntityRef(
            index=index,
            kind=kind,
            points_m=points,
            radius_m=radius,
            construction=bool(ent.get("construction")),
        )

    def list_sketch_entities(self, sketch: str | None = None) -> list[SketchEntityRef]:
        self._enter("list_sketch_entities", sketch=sketch)
        doc = self._require_doc()
        sk = self._sketch_by_name(doc, sketch)
        return [self._entity_ref(i, e) for i, e in enumerate(sk.entities)]

    # ---------- Offset / fillet trim / mirror ----------

    def sketch_offset(self, distance_m: float, inward: bool = False) -> None:
        self._enter("sketch_offset", distance=distance_m, inward=inward)
        sk = self._open_sketch(planar=True)
        if distance_m <= 0:
            raise fail("INVALID_ARGUMENT", "Offset distance must be positive", "Pass distance > 0")
        d = float(distance_m)
        added = False
        for e in list(sk.entities):
            if e.get("construction"):
                continue
            if e.get("kind") == "rect":
                x0, x1 = min(e["x0"], e["x1"]), max(e["x0"], e["x1"])
                y0, y1 = min(e["y0"], e["y1"]), max(e["y0"], e["y1"])
                if inward:
                    nx0, ny0, nx1, ny1 = x0 + d, y0 + d, x1 - d, y1 - d
                else:
                    nx0, ny0, nx1, ny1 = x0 - d, y0 - d, x1 + d, y1 + d
                if nx0 >= nx1 or ny0 >= ny1:
                    raise fail(
                        "FEATURE_CREATE_FAILED",
                        "Offset too large; profile collapsed",
                        "Reduce distance, or use outward",
                    )
                sk.entities.append({"kind": "rect", "x0": nx0, "y0": ny0, "x1": nx1, "y1": ny1})
                added = True
            elif e.get("kind") == "circle":
                r = float(e["r"]) + (-d if inward else d)
                if r <= 0:
                    raise fail(
                        "FEATURE_CREATE_FAILED",
                        "Offset too large; circle collapsed",
                        "Reduce distance",
                    )
                sk.entities.append({"kind": "circle", "cx": e["cx"], "cy": e["cy"], "r": r})
                added = True
        if not added:
            raise fail(
                "SKETCH_OP_FAILED",
                "No closed profile to offset",
                "sketch_rectangle or sketch_circle first",
            )
        self._doc.modified = True  # type: ignore[union-attr]

    def sketch_trim(self, entity1: int, entity2: int, radius_m: float) -> None:
        self._enter("sketch_trim", entity1=entity1, entity2=entity2, radius=radius_m)
        sk = self._open_sketch(planar=True)
        if radius_m <= 0:
            raise fail("INVALID_ARGUMENT", "Fillet radius must be positive", "Pass radius > 0")
        e1 = self._sketch_seg(sk, entity1)
        e2 = self._sketch_seg(sk, entity2)
        if entity1 == entity2:
            raise fail("INVALID_ARGUMENT", "Fillet trim needs two different entities", "entity1 and entity2 must differ")
        if e1.get("kind") not in {"line", "rect"} or e2.get("kind") not in {"line", "rect"}:
            raise fail("SKETCH_OP_FAILED", "Sketch fillet trim only supports line or rectangle edges", "Use adjacent rectangle edges")
        sk.entities.append({"kind": "arc", "r": float(radius_m), "fillet": True, "cx": 0.0, "cy": 0.0, "x0": 0.0, "y0": 0.0, "x1": 0.0, "y1": 0.0, "sweep": math.pi / 2})
        if e1.get("kind") == "rect":
            e1["fillet_r"] = float(radius_m)
        self._doc.modified = True  # type: ignore[union-attr]

    def sketch_mirror(self, axis: int) -> None:
        self._enter("sketch_mirror", axis=axis)
        sk = self._open_sketch(planar=True)
        ax = self._sketch_seg(sk, axis)
        if ax.get("kind") != "line":
            raise fail("INVALID_ARGUMENT", "Mirror axis must be a line", "Draw the axis with sketch_line first")
        ax["construction"] = True
        copies: list[dict] = []
        for i, e in enumerate(sk.entities):
            if i == axis or e.get("construction"):
                continue
            copies.append(self._mirror_entity(e, ax))
        if not copies:
            raise fail("SKETCH_OP_FAILED", "No entities to mirror", "Draw the profile besides the axis line")
        sk.entities.extend(copies)
        self._doc.modified = True  # type: ignore[union-attr]

    def _mirror_entity(self, ent: dict, axis: dict) -> dict:
        def _pt(x: float, y: float) -> tuple[float, float]:
            return _reflect_xy(x, y, axis["x0"], axis["y0"], axis["x1"], axis["y1"])

        out = dict(ent)
        if ent.get("kind") == "line":
            x0, y0 = _pt(ent["x0"], ent["y0"])
            x1, y1 = _pt(ent["x1"], ent["y1"])
            out.update({"x0": x0, "y0": y0, "x1": x1, "y1": y1})
        elif ent.get("kind") == "rect":
            x0, y0 = _pt(ent["x0"], ent["y0"])
            x1, y1 = _pt(ent["x1"], ent["y1"])
            out.update({"x0": x0, "y0": y0, "x1": x1, "y1": y1})
        elif ent.get("kind") == "circle":
            cx, cy = _pt(ent["cx"], ent["cy"])
            out.update({"cx": cx, "cy": cy})
        elif ent.get("kind") == "arc":
            x0, y0 = _pt(ent["x0"], ent["y0"])
            x1, y1 = _pt(ent["x1"], ent["y1"])
            cx, cy = _pt(ent["cx"], ent["cy"])
            out.update({"x0": x0, "y0": y0, "x1": x1, "y1": y1, "cx": cx, "cy": cy})
        return out

    def edit_sketch(self, name: str) -> SketchInfo:
        self._enter("edit_sketch", name=name)
        doc = self._require_doc()
        if doc.open_sketch is not None:
            raise fail(
                "SKETCH_OP_FAILED",
                f"Sketch {doc.open_sketch.name or ''} is already open; cannot open a second",
                "Call end_sketch to close the current sketch before edit_sketch",
            )
        sk = self._sketch_by_name(doc, name)
        doc.open_sketch = sk
        doc.modified = True
        return SketchInfo(plane=sk.plane, entity_count=len(sk.entities), name=sk.name)

    def sketch_solve_status(self, sketch: str | None = None) -> SketchSolveStatus:
        self._enter("sketch_solve_status", sketch=sketch)
        doc = self._require_doc()
        sk = self._sketch_by_name(doc, sketch)
        over = False
        directed = 0
        lines = 0
        dimmed = 0
        for e in sk.entities:
            rels = set(e.get("relations") or ())
            if e.get("kind") == "line":
                lines += 1
                length = math.hypot(e["x1"] - e["x0"], e["y1"] - e["y0"])
                if "sgHORIZONTAL2D" in rels and "sgVERTICAL2D" in rels and length > 1e-12:
                    over = True
                if "sgHORIZONTAL2D" in rels or "sgVERTICAL2D" in rels:
                    directed += 1
            if e.get("dimensioned"):
                dimmed += 1
        if over:
            return SketchSolveStatus(state="over_defined", dof=0)
        if lines > 0 and directed >= lines and dimmed > 0:
            return SketchSolveStatus(state="fully_defined", dof=0)
        return SketchSolveStatus(state="under_defined", dof=None)

    # ---------- Helpers: sketch entities ----------

    def _sketch_seg(self, sk: _Sketch, index: int) -> dict:
        if index < 0 or index >= len(sk.entities):
            raise fail(
                "INVALID_ARGUMENT",
                f"Sketch entity index out of range: {index}",
                f"Valid range 0..{len(sk.entities) - 1}" if sk.entities else "Draw sketch entities first",
            )
        return sk.entities[index]

    @staticmethod
    def _snap_sketch_endpoints(e1: dict, e2: dict) -> None:
        keys = (("x0", "y0"), ("x1", "y1"))
        best = None
        for a0, a1 in keys:
            for b0, b1 in keys:
                d = math.hypot(e1[a0] - e2[b0], e1[a1] - e2[b1])
                if best is None or d < best[0]:
                    best = (d, a0, a1, b0, b1)
        assert best is not None
        _, a0, a1, b0, b1 = best
        e2[b0], e2[b1] = e1[a0], e1[a1]

    @staticmethod
    def _colinear_lines(target: dict, src: dict) -> None:
        """Align target to src line (same direction, start projects onto src line)。"""
        FakeSketchMixin._align_line_dir(target, src)
        ax, ay = float(src["x0"]), float(src["y0"])
        bx, by = float(src["x1"]), float(src["y1"])
        vx, vy = bx - ax, by - ay
        den = vx * vx + vy * vy
        if den <= 1e-24:
            return
        px, py = float(target["x0"]), float(target["y0"])
        t = ((px - ax) * vx + (py - ay) * vy) / den
        qx, qy = ax + t * vx, ay + t * vy
        dx, dy = qx - px, qy - py
        target["x0"] = float(target["x0"]) + dx
        target["y0"] = float(target["y0"]) + dy
        target["x1"] = float(target["x1"]) + dx
        target["y1"] = float(target["y1"]) + dy

    @staticmethod
    def _snap_to_midpoint(point_ent: dict, line: dict) -> None:
        mx = (float(line["x0"]) + float(line["x1"])) / 2.0
        my = (float(line["y0"]) + float(line["y1"])) / 2.0
        keys = (("x0", "y0"), ("x1", "y1"))
        best = None
        for a0, a1 in keys:
            if a0 not in point_ent:
                continue
            d = math.hypot(float(point_ent[a0]) - mx, float(point_ent[a1]) - my)
            if best is None or d < best[0]:
                best = (d, a0, a1)
        if best is None:
            return
        _, a0, a1 = best
        point_ent[a0], point_ent[a1] = mx, my

    @staticmethod
    def _reflect_point_about_line(
        px: float, py: float, ax: float, ay: float, bx: float, by: float,
    ) -> tuple[float, float]:
        vx, vy = bx - ax, by - ay
        den = vx * vx + vy * vy
        if den <= 1e-24:
            return px, py
        t = ((px - ax) * vx + (py - ay) * vy) / den
        qx, qy = ax + t * vx, ay + t * vy
        return 2.0 * qx - px, 2.0 * qy - py

    @staticmethod
    def _mirror_line_about_axis(target: dict, src: dict, axis: dict) -> None:
        """Mirror target from src about axis line (endpoints reflected pairwise)。"""
        ax, ay = float(axis["x0"]), float(axis["y0"])
        bx, by = float(axis["x1"]), float(axis["y1"])
        x0, y0 = FakeSketchMixin._reflect_point_about_line(
            float(src["x0"]), float(src["y0"]), ax, ay, bx, by
        )
        x1, y1 = FakeSketchMixin._reflect_point_about_line(
            float(src["x1"]), float(src["y1"]), ax, ay, bx, by
        )
        target["x0"], target["y0"] = x0, y0
        target["x1"], target["y1"] = x1, y1

    def _line_by_ends(
        self, sk: _Sketch, x1: float, y1: float, x2: float, y2: float, *, missing_ok: bool = False
    ) -> dict | None:
        hits = [
            e for e in sk.entities
            if e.get("kind") == "line"
            and line_matches_ends(e["x0"], e["y0"], e["x1"], e["y1"], x1, y1, x2, y2)
        ]
        if not hits:
            if missing_ok:
                return None
            raise fail(
                "REF_NOT_FOUND",
                "No line or circle matching the given endpoints",
                "Lines use both endpoints; circles use center + point on circumference",
            )
        if len(hits) > 1:
            raise fail("REF_AMBIGUOUS", "Multiple lines share the same endpoints", "Move one line before dimensioning")
        return hits[0]

    def _circle_by_center_rim(
        self, sk: _Sketch, x1: float, y1: float, x2: float, y2: float, *, missing_ok: bool = False
    ) -> dict | None:
        hits = [
            e for e in sk.entities
            if e.get("kind") == "circle"
            and circle_matches_center_rim(e["cx"], e["cy"], e["r"], x1, y1, x2, y2)
        ]
        if not hits:
            if missing_ok:
                return None
            raise fail(
                "REF_NOT_FOUND",
                "No line or circle matching the given endpoints",
                "Lines use both endpoints; circles use center + point on circumference",
            )
        if len(hits) > 1:
            raise fail("REF_AMBIGUOUS", "Multiple circles match the same center and radius point", "Use a different point on the circumference")
        return hits[0]

    def _dimension_by_index(
        self, sk: _Sketch, entity1: int, entity2: int | None, value_m: float
    ) -> dict:
        e1 = self._sketch_seg(sk, entity1)
        if entity2 is None:
            if e1.get("kind") == "line":
                dx, dy = e1["x1"] - e1["x0"], e1["y1"] - e1["y0"]
                length = math.hypot(dx, dy)
                if length <= 0:
                    raise fail("SKETCH_OP_FAILED", "Line length is zero; cannot dimension", "Use two distinct points")
                scale = value_m / length
                e1["x1"] = e1["x0"] + dx * scale
                e1["y1"] = e1["y0"] + dy * scale
                e1["dimensioned"] = True
                return e1
            if e1.get("kind") == "circle":
                e1["r"] = value_m / 2.0
                e1["dimensioned"] = True
                return e1
            raise fail("SKETCH_OP_FAILED", "This entity cannot be dimensioned alone", "Dimension line length or circle diameter")
        e2 = self._sketch_seg(sk, entity2)
        if e1.get("kind") != "line" or e2.get("kind") != "line":
            raise fail("SKETCH_OP_FAILED", "Opposite-edge dimension needs two lines", "Pass indexes of two polygon edges")
        self._drive_across_flats(sk, e1, e2, value_m)
        return e1

    @staticmethod
    def _parallel_gap(e1: dict, e2: dict) -> float:
        dx, dy = e1["x1"] - e1["x0"], e1["y1"] - e1["y0"]
        nlen = math.hypot(dx, dy)
        if nlen <= 0:
            return 0.0
        nx, ny = -dy / nlen, dx / nlen
        mx = (e2["x0"] + e2["x1"]) / 2.0 - (e1["x0"] + e1["x1"]) / 2.0
        my = (e2["y0"] + e2["y1"]) / 2.0 - (e1["y0"] + e1["y1"]) / 2.0
        return abs(mx * nx + my * ny)

    def _drive_across_flats(self, sk: _Sketch, e1: dict, e2: dict, value_m: float) -> None:
        dist = self._parallel_gap(e1, e2)
        if dist <= 1e-12:
            raise fail("SKETCH_OP_FAILED", "Edges coincide; cannot dimension opposite edges", "Pick a pair of parallel opposite edges")
        scale = value_m / dist
        group = e1.get("group")
        targets = [e for e in sk.entities if e.get("kind") == "line" and e.get("group") == group] if group else [e1, e2]
        for e in targets:
            for key in ("x0", "y0", "x1", "y1"):
                e[key] *= scale

    def _across_flats_from_points(
        self, sk: _Sketch, x1: float, y1: float, x2: float, y2: float, value_m: float
    ) -> bool:
        tol = 5e-4
        lines = [e for e in sk.entities if e.get("kind") == "line"]

        def dist_pt(e: dict, px: float, py: float) -> float:
            ax, ay, bx, by = e["x0"], e["y0"], e["x1"], e["y1"]
            vx, vy = bx - ax, by - ay
            den = vx * vx + vy * vy
            if den <= 1e-24:
                return math.hypot(px - ax, py - ay)
            t = ((px - ax) * vx + (py - ay) * vy) / den
            return math.hypot(px - (ax + t * vx), py - (ay + t * vy))

        near1 = [e for e in lines if dist_pt(e, x1, y1) <= tol]
        near2 = [e for e in lines if dist_pt(e, x2, y2) <= tol]
        uniq: list[tuple[dict, dict]] = []
        seen: set[frozenset[int]] = set()
        for a in near1:
            for b in near2:
                if a is b:
                    continue
                ax, ay = a["x1"] - a["x0"], a["y1"] - a["y0"]
                bx, by = b["x1"] - b["x0"], b["y1"] - b["y0"]
                la, lb = math.hypot(ax, ay), math.hypot(bx, by)
                if la <= 1e-12 or lb <= 1e-12:
                    continue
                if abs(ax * by - ay * bx) > 1e-9 * la * lb:
                    continue
                key = frozenset((id(a), id(b)))
                if key in seen:
                    continue
                seen.add(key)
                uniq.append((a, b))
        if not uniq:
            return False
        if len(uniq) > 1:
            raise fail("REF_AMBIGUOUS", "Multiple parallel pairs match the opposite-edge dimension", "Specify two edges with entity1/entity2")
        self._drive_across_flats(sk, uniq[0][0], uniq[0][1], value_m)
        return True

    @staticmethod
    def _equal_line_len(target: dict, src: dict) -> None:
        sdx, sdy = src["x1"] - src["x0"], src["y1"] - src["y0"]
        tdx, tdy = target["x1"] - target["x0"], target["y1"] - target["y0"]
        slen, tlen = math.hypot(sdx, sdy), math.hypot(tdx, tdy)
        if slen <= 0 or tlen <= 0:
            return
        target["x1"] = target["x0"] + tdx / tlen * slen
        target["y1"] = target["y0"] + tdy / tlen * slen

    @staticmethod
    def _align_line_dir(target: dict, src: dict) -> None:
        sdx, sdy = src["x1"] - src["x0"], src["y1"] - src["y0"]
        slen = math.hypot(sdx, sdy)
        tlen = math.hypot(target["x1"] - target["x0"], target["y1"] - target["y0"])
        if slen <= 0 or tlen <= 0:
            return
        target["x1"] = target["x0"] + sdx / slen * tlen
        target["y1"] = target["y0"] + sdy / slen * tlen

    @staticmethod
    def _perp_line_dir(target: dict, src: dict) -> None:
        sdx, sdy = src["x1"] - src["x0"], src["y1"] - src["y0"]
        tlen = math.hypot(target["x1"] - target["x0"], target["y1"] - target["y0"])
        slen = math.hypot(sdx, sdy)
        if slen <= 0 or tlen <= 0:
            return
        target["x1"] = target["x0"] + (-sdy) / slen * tlen
        target["y1"] = target["y0"] + sdx / slen * tlen

    # ---------- Helpers: open / pending sketch ----------

    def _open_sketch(self, *, planar: bool = False) -> _Sketch:
        doc = self._require_doc()
        if doc.open_sketch is None:
            raise fail(
                "NO_ACTIVE_SKETCH",
                "No sketch is open; cannot draw",
                "Call start_sketch and pick a reference plane",
            )
        if planar and is_3d_sketch_plane(doc.open_sketch.plane):
            raise fail(
                "INVALID_ARGUMENT",
                "This operation only supports planar sketches",
                "end_sketch, then start_sketch on a reference plane; for 3D use entities that accept z/cz",
            )
        return doc.open_sketch

    def _pending_sketch(self, sketch: str | None) -> tuple[_Doc, _Sketch]:
        """Shared pre-check for extrude/revolve/cut: doc → no open sketch → matching ended sketch."""
        doc = self._require_doc()
        if doc.open_sketch is not None:
            raise fail(
                "SKETCH_OP_FAILED",
                f"Sketch {doc.open_sketch.name or ''} is still open; cannot create a feature",
                "Call end_sketch to close the sketch, then run the feature",
            )
        pending = doc.pending_sketch
        if pending is None or (sketch is not None and pending.name != sketch):
            have = pending.name if pending else "none"
            raise fail(
                "SKETCH_NOT_FOUND",
                f"No ended sketch for features (requested  {sketch!r}, current: {have}）",
                "Call start_sketch → draw → end_sketch, then run the feature",
                requested=sketch,
            )
        return doc, pending

    @staticmethod
    def _consume_sketch(doc: _Doc, sk: _Sketch | None) -> None:
        """Feature consumes sketch: clear pending and remove from ended-sketch history."""
        if sk is not None:
            doc.ended_sketches = [x for x in doc.ended_sketches if x is not sk]
        if doc.pending_sketch is sk:
            doc.pending_sketch = None
