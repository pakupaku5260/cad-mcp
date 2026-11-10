"""Fake backend · feature domain · surface features（S8e-8 + SURF3–5）。

S8e-8：extrude_surface / knit / thicken / fill_surface / boundary_surface /
       rib / draft；SURF3–6：trim / extend / fillet / untrim_surface。

Dependencies (self, MRO):
- `_enter` / `_require_doc` / `_doc`（FakeBackend）
- `_require_part`（FakeQueryMixin，S8e-3）
- `_pending_sketch` / `_consume_sketch`（FakeSketchMixin，S8d）
- `_profile_of` / `_solid_z_span`（FakeExtrudeMixin，S8e-1）
- `_plane_frame`（FakePlaneAxisMixin，S8d-2）
- `_loft_sketches` / `_sketch_bbox3d`（FakeLoftMixin，S8e-6）
- `list_faces`（FakeSelectionMixin，S8e-4）
- `_checked_indexes`（FakeModifyMixin，S8e-5）

Imports:
- `cadmcp.backend.protocol.geometry_engine`（extrude_z_range_m）
- `cadmcp.backend.protocol.models`（FeatureInfo）
- `cadmcp.errors`（fail）
- `.._state`（_union_boxes）
"""
from __future__ import annotations

import math
from collections.abc import Sequence

from cadmcp.backend.protocol.geometry_engine import extrude_z_range_m
from cadmcp.backend.protocol.models import FeatureInfo
from cadmcp.errors import CadMcpError, fail

from .._state import _union_boxes, _vadd, _vmul


class FakeSurfaceMixin:
    """surface features（S8e-8 + trim/extend/fillet_surface）。"""

    def _init_state(self) -> None:
        pass  # State owned by FakeBackend._init_state

    # ---------- Surface extrude ----------

    def extrude_surface(self, depth_m: float, sketch: str | None = None) -> FeatureInfo:
        self._enter("extrude_surface", depth=depth_m, sketch=sketch)
        doc = self._require_part("Use a part document for surface extrude")
        doc, pending = self._pending_sketch(sketch)
        if depth_m <= 0:
            raise fail(
                "INVALID_ARGUMENT",
                f"Surface extrude depth must be positive (meters internally): {depth_m}",
                "Pass depth > 0 (unit from unit param, default mm)",
            )
        closed = True
        try:
            prof = self._profile_of(pending)
        except CadMcpError as exc:
            if not pending.entities:
                raise
            closed = False
            xs, ys = [], []
            peri = 0.0
            for e in pending.entities:
                if e.get("kind") == "line":
                    xs.extend((e["x0"], e["x1"]))
                    ys.extend((e["y0"], e["y1"]))
                    peri += math.hypot(e["x1"] - e["x0"], e["y1"] - e["y0"])
                elif e.get("kind") == "circle":
                    xs.extend((e["cx"] - e["r"], e["cx"] + e["r"]))
                    ys.extend((e["cy"] - e["r"], e["cy"] + e["r"]))
                    peri += 2.0 * math.pi * e["r"]
            if not xs:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Sketch empty; no usable surface profile",
                    "Draw closed rect/circle or open curve, end_sketch, then extrude_surface",
                ) from exc
            prof = {
                "profile": "open",
                "area": 0.0,
                "perimeter": peri,
                "bbox2d": (min(xs), min(ys), max(xs), max(ys)),
                "faces": 1,
                "edges": 4,
            }
        n = sum(1 for x in doc.features if x["kind"] == "extrude_surface") + 1
        z0, z1 = extrude_z_range_m(depth_m, "blind", None, False)
        f = dict(prof)
        f.update(
            kind="extrude_surface",
            sign=0,
            depth=depth_m,
            name=f"Surface-Extrude{n}",
            plane=pending.plane,
            closed=closed,
            source_sketch=pending,
        )
        x0, y0, x1, y1 = f["bbox2d"]
        origin, uu, vv, nn = self._plane_frame(str(pending.plane or "Front Plane"))
        corners: list[tuple[float, float, float]] = []
        for u in (x0, x1):
            for v in (y0, y1):
                base = _vadd(origin, _vmul(uu, u), _vmul(vv, v))
                corners.append(_vadd(base, _vmul(nn, z0)))
                corners.append(_vadd(base, _vmul(nn, z1)))
        xs, ys, zs = zip(*corners, strict=True)
        f["bbox3d"] = (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))
        f["com"] = _vadd(
            origin, _vmul(uu, (x0 + x1) / 2), _vmul(vv, (y0 + y1) / 2), _vmul(nn, (z0 + z1) / 2)
        )
        doc.features.append(f)
        self._consume_sketch(doc, pending)
        doc.modified = True
        return FeatureInfo(name=f["name"], kind="extrude_surface")

    # ---------- Knit ----------

    def knit(self, surfaces: Sequence[str] | None = None) -> FeatureInfo:
        self._enter("knit", surfaces=surfaces)
        doc = self._require_part("Use a part document to knit surfaces")
        sheets = [x for x in doc.features if x["kind"] == "extrude_surface"]
        if surfaces:
            picked: list[dict] = []
            for raw in surfaces:
                hit = next((x for x in doc.features if x["name"] == str(raw)), None)
                if hit is None or hit["kind"] not in ("extrude_surface", "knit"):
                    raise fail(
                        "FEATURE_NOT_FOUND",
                        f"Surface not found: {raw!r}",
                        "Use Surface-ExtrudeN from list_features, or omit surfaces to knit the latest two",
                        requested=raw,
                    )
                picked.append(hit)
        else:
            picked = sheets[-2:]
        if len(picked) < 2:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "Knit needs at least two surfaces",
                "extrude_surface twice, then knit",
            )
        n = sum(1 for x in doc.features if x["kind"] == "knit") + 1
        boxes = [x["bbox3d"] for x in picked if "bbox3d" in x]
        bbox = boxes[0]
        for b in boxes[1:]:
            bbox = (
                min(bbox[0], b[0]), min(bbox[1], b[1]), min(bbox[2], b[2]),
                max(bbox[3], b[3]), max(bbox[4], b[4]), max(bbox[5], b[5]),
            )
        feat = {
            "kind": "knit",
            "name": f"Surface-Knit{n}",
            "sign": 0,
            "open": True,
            "bbox3d": bbox,
            "sources": [x["name"] for x in picked],
        }
        doc.features.append(feat)
        doc.modified = True
        return FeatureInfo(name=feat["name"], kind="knit")

    # ---------- Thicken ----------

    def thicken(self, thickness_m: float, surface: str | None = None) -> FeatureInfo:
        self._enter("thicken", thickness=thickness_m, surface=surface)
        doc = self._require_part("Use a part document to thicken a surface")
        if thickness_m <= 0:
            raise fail(
                "INVALID_ARGUMENT",
                f"Thicken thickness must be positive (meters internally): {thickness_m}",
                "Pass thickness > 0 (unit from unit param, default mm)",
            )
        if surface is not None:
            src = next((x for x in doc.features if x["name"] == str(surface)), None)
            if src is None:
                raise fail(
                    "FEATURE_NOT_FOUND",
                    f"Surface not found: {surface!r}",
                    "Use Surface-ExtrudeN from list_features",
                    requested=surface,
                )
        else:
            src = next(
                (x for x in reversed(doc.features) if x["kind"] in ("extrude_surface", "knit")),
                None,
            )
        if src is None:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "No surface to thicken",
                "extrude_surface a closed profile, then thicken",
            )
        if src["kind"] == "knit" or src.get("open"):
            raise fail(
                "FEATURE_CREATE_FAILED",
                "Open surface cannot thicken to a solid",
                "Thicken closed surface extrude; knitted open sheets cannot thicken",
            )
        if not src.get("closed", True):
            raise fail(
                "FEATURE_CREATE_FAILED",
                "Open surface cannot thicken to a solid",
                "extrude_surface with closed rect/circle, then thicken",
            )
        depth = float(src.get("depth") or 0.0)
        area = float(src.get("area") or 0.0)
        if area <= 0 or depth <= 0:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "Open surface cannot thicken to a solid",
                "extrude_surface with closed profile, then thicken",
            )
        n = sum(1 for x in doc.features if x["kind"] == "thicken") + 1
        x0, y0, x1, y1 = src["bbox2d"]
        w, h = abs(x1 - x0), abs(y1 - y0)
        vol = area * depth
        surf = 2.0 * (w * h + w * depth + h * depth)
        b = src["bbox3d"]
        t = float(thickness_m)
        feat = {
            "kind": "thicken",
            "name": f"Thicken{n}",
            "sign": 1,
            "vol": vol,
            "surf": surf,
            "faces": 6,
            "edges": 12,
            "bbox3d": (b[0] - t, b[1] - t, b[2] - t, b[3] + t, b[4] + t, b[5] + t),
            "com": src.get("com", (0.0, 0.0, 0.0)),
            "source": src["name"],
        }
        doc.features.append(feat)
        doc.modified = True
        return FeatureInfo(name=feat["name"], kind="thicken")

    # ---------- Fill ----------

    def fill_surface(self, surface: str | None = None, edge: int = 0) -> FeatureInfo:
        self._enter("fill_surface", surface=surface, edge=edge)
        doc = self._require_part("Use a part document for fill surface")
        if doc.open_sketch is not None:
            raise fail(
                "SKETCH_OP_FAILED",
                f"Sketch {doc.open_sketch.name or ''} is still open; cannot create a feature",
                "Call end_sketch to close the sketch, then fill_surface",
            )
        sheets = [x for x in doc.features if x["kind"] in ("extrude_surface", "knit", "boundary_surface")]
        if surface is not None:
            src = next((x for x in doc.features if x["name"] == str(surface)), None)
            if src is None or src["kind"] not in ("extrude_surface", "knit", "boundary_surface", "fill_surface"):
                raise fail(
                    "FEATURE_NOT_FOUND",
                    f"Surface not found: {surface!r}",
                    "Use Surface-ExtrudeN from list_features",
                    requested=surface,
                )
        else:
            src = sheets[-1] if sheets else None
        if src is None:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "No sheet to fill",
                "extrude_surface an open sheet, then fill_surface to cap edges",
            )
        idx = int(edge)
        if idx < 0 or idx > 1:
            raise fail(
                "INVALID_ARGUMENT",
                f"Edge index out of range: {idx}",
                "Circular surface extrude has two open edges; use edge 0 or 1",
                index=idx,
            )
        n = sum(1 for x in doc.features if x["kind"] == "fill_surface") + 1
        bbox = src.get("bbox3d") or (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        feat = {
            "kind": "fill_surface",
            "name": f"Surface-Fill{n}",
            "sign": 0,
            "bbox3d": bbox,
            "source": src["name"],
        }
        doc.features.append(feat)
        doc.modified = True
        return FeatureInfo(name=feat["name"], kind="fill_surface")

    # ---------- Boundary surface ----------

    def boundary_surface(self, profiles: Sequence[str] | None = None) -> FeatureInfo:
        self._enter("boundary_surface", profiles=profiles)
        doc = self._require_part("Use a part document for boundary surface")
        sketches = self._loft_sketches(doc, profiles)
        p0 = self._profile_of(sketches[0])
        p1 = self._profile_of(sketches[-1])
        o0, _u0, _v0, n0 = self._plane_frame(str(sketches[0].plane or "Front Plane"))
        o1, _u1, _v1, _n1 = self._plane_frame(str(sketches[-1].plane or "Front Plane"))
        delta = (o1[0] - o0[0], o1[1] - o0[1], o1[2] - o0[2])
        h = abs(delta[0] * n0[0] + delta[1] * n0[1] + delta[2] * n0[2])
        if h < 1e-12:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "Boundary profiles are coplanar; cannot build surface",
                "Sketch the second profile on an offset plane (create_plane)",
            )
        boxes = [b for sk in (sketches[0], sketches[-1]) if (b := self._sketch_bbox3d(sk)) is not None]
        bbox = _union_boxes(boxes)
        n = sum(1 for x in doc.features if x["kind"] == "boundary_surface") + 1
        feat = {
            "kind": "boundary_surface",
            "name": f"Surface-Boundary{n}",
            "sign": 0,
            "bbox3d": bbox,
            "area0": p0.get("area", 0.0),
            "area1": p1.get("area", 0.0),
        }
        doc.features.append(feat)
        for sk in sketches:
            self._consume_sketch(doc, sk)
        doc.modified = True
        return FeatureInfo(name=feat["name"], kind="boundary_surface")

    # ---------- Trim ----------

    def _sheet_features(self, doc) -> list[dict]:
        return [
            x
            for x in doc.features
            if x["kind"]
            in (
                "extrude_surface",
                "knit",
                "fill_surface",
                "boundary_surface",
                "trim_surface",
                "extend_surface",
                "fillet_surface",
                "untrim_surface",
            )
        ]

    def trim_surface(
        self,
        tool: str | None = None,
        target: str | None = None,
        keep: int = 0,
    ) -> FeatureInfo:
        self._enter("trim_surface", trim_tool=tool, trim_target=target, keep=keep)
        doc = self._require_part("Use a part document to trim surfaces")
        if doc.open_sketch is not None:
            raise fail(
                "SKETCH_OP_FAILED",
                f"Sketch {doc.open_sketch.name or ''} is still open; cannot create a feature",
                "Call end_sketch to close the sketch, then trim_surface",
            )
        if int(keep) < 0:
            raise fail(
                "INVALID_ARGUMENT",
                f"keep cannot be negative: {keep}",
                "Pass keep>=0 (piece index, default 0)",
                index=int(keep),
            )
        sheets = self._sheet_features(doc)

        def _find(name: str) -> dict:
            hit = next((x for x in doc.features if x["name"] == str(name)), None)
            if hit is None or hit["kind"] not in {
                "extrude_surface",
                "knit",
                "fill_surface",
                "boundary_surface",
                "trim_surface",
            }:
                raise fail(
                    "FEATURE_NOT_FOUND",
                    f"Surface not found: {name!r}",
                    "Use Surface-ExtrudeN from list_features",
                    requested=name,
                )
            return hit

        if tool is None and target is None:
            if len(sheets) < 2:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Trim needs at least two surfaces",
                    "extrude_surface twice (intersecting), then trim_surface",
                )
            tool_feat, target_feat = sheets[-1], sheets[-2]
        elif tool is not None and target is not None:
            tool_feat, target_feat = _find(tool), _find(target)
        elif tool is not None:
            tool_feat = _find(tool)
            others = [x for x in sheets if x["name"] != tool_feat["name"]]
            if not others:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "No target surface to trim",
                    "extrude_surface another sheet intersecting tool, or pass target explicitly",
                )
            target_feat = others[-1]
        else:
            target_feat = _find(target)  # type: ignore[arg-type]
            others = [x for x in sheets if x["name"] != target_feat["name"]]
            if not others:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Trim tool surface not found",
                    "extrude_surface another sheet intersecting target, or pass tool explicitly",
                )
            tool_feat = others[-1]
        if tool_feat["name"] == target_feat["name"]:
            raise fail(
                "INVALID_ARGUMENT",
                "tool and target cannot be the same surface",
                "Specify trim tool and target sheet separately",
            )
        idx = int(keep)
        # canned: intersecting extrudes always 2 pieces; OOB aligns COM INVALID_ARGUMENT
        if idx > 1:
            raise fail(
                "INVALID_ARGUMENT",
                f"keep out of piece range: {idx} (2 pieces total)",
                "Sheets must intersect; use keep 0 or 1",
                index=idx,
            )
        n = sum(1 for x in doc.features if x["kind"] == "trim_surface") + 1
        bbox = target_feat.get("bbox3d") or (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        # slightly shrink bbox for kept piece (structural golden, not numeric)
        shrink = 1e-4
        bbox = (
            float(bbox[0]) + shrink,
            float(bbox[1]) + shrink,
            float(bbox[2]),
            float(bbox[3]) - shrink,
            float(bbox[4]) - shrink,
            float(bbox[5]),
        )
        feat = {
            "kind": "trim_surface",
            "name": f"Surface-Trim{n}",
            "sign": 0,
            "bbox3d": bbox,
            "tool": tool_feat["name"],
            "target": target_feat["name"],
            "keep": idx,
        }
        doc.features.append(feat)
        doc.modified = True
        return FeatureInfo(name=feat["name"], kind="trim_surface")

    # ---------- Extend ----------

    def extend_surface(
        self,
        distance_m: float,
        surface: str | None = None,
        edge: int | None = None,
        linear: bool = True,
    ) -> FeatureInfo:
        self._enter(
            "extend_surface",
            distance=distance_m,
            surface=surface,
            edge=edge,
            linear=linear,
        )
        doc = self._require_part("Use a part document to extend a surface")
        if doc.open_sketch is not None:
            raise fail(
                "SKETCH_OP_FAILED",
                f"Sketch {doc.open_sketch.name or ''} is still open; cannot create a feature",
                "Call end_sketch to close the sketch, then extend_surface",
            )
        if distance_m <= 0:
            raise fail(
                "INVALID_ARGUMENT",
                f"Extension distance must be positive: {distance_m}",
                "Pass distance > 0",
            )
        sheets = self._sheet_features(doc)
        kinds = {
            "extrude_surface",
            "knit",
            "fill_surface",
            "boundary_surface",
            "trim_surface",
            "extend_surface",
        }
        if surface is not None:
            src = next((x for x in doc.features if x["name"] == str(surface)), None)
            if src is None or src["kind"] not in kinds:
                raise fail(
                    "FEATURE_NOT_FOUND",
                    f"Surface not found: {surface!r}",
                    "Use Surface-ExtrudeN from list_features",
                    requested=surface,
                )
        else:
            src = sheets[-1] if sheets else None
        if src is None:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "No sheet to extend",
                "extrude_surface an open sheet, then extend_surface",
            )
        if edge is not None:
            idx = int(edge)
            # canned: circular surface extrude has two open edges; OOB aligns COM
            if idx < 0 or idx > 1:
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Edge index out of range: {idx}",
                    "Circular surface extrude has two open edges; use edge 0 or 1; or omit edge for whole face",
                    index=idx,
                )
        n = sum(1 for x in doc.features if x["kind"] == "extend_surface") + 1
        bbox = list(src.get("bbox3d") or (0.0, 0.0, 0.0, 0.0, 0.0, 0.0))
        # expand along longest axis by distance; structural golden, not numeric
        spans = (bbox[3] - bbox[0], bbox[4] - bbox[1], bbox[5] - bbox[2])
        axis = max(range(3), key=lambda i: spans[i])
        bbox[axis + 3] = float(bbox[axis + 3]) + float(distance_m)
        feat = {
            "kind": "extend_surface",
            "name": f"Surface-Extend{n}",
            "sign": 0,
            "bbox3d": tuple(float(x) for x in bbox),
            "source": src["name"],
            "distance": float(distance_m),
            "linear": bool(linear),
            "edge": None if edge is None else int(edge),
        }
        doc.features.append(feat)
        doc.modified = True
        return FeatureInfo(name=feat["name"], kind="extend_surface")

    # ---------- Surface fillet ----------

    def fillet_surface(
        self, radius_m: float, surface: str | None = None, edge: int = 0
    ) -> FeatureInfo:
        self._enter("fillet_surface", radius=radius_m, surface=surface, edge=edge)
        doc = self._require_part("Use a part document for surface fillet")
        if doc.open_sketch is not None:
            raise fail(
                "SKETCH_OP_FAILED",
                f"Sketch {doc.open_sketch.name or ''} is still open; cannot create a feature",
                "Call end_sketch to close the sketch, then fillet_surface",
            )
        if radius_m <= 0:
            raise fail(
                "INVALID_ARGUMENT",
                f"Fillet radius must be positive: {radius_m}",
                "Pass radius > 0",
            )
        sheets = self._sheet_features(doc)
        kinds = {
            "extrude_surface",
            "knit",
            "fill_surface",
            "boundary_surface",
            "trim_surface",
            "extend_surface",
            "fillet_surface",
        }
        if surface is not None:
            src = next((x for x in doc.features if x["name"] == str(surface)), None)
            if src is None or src["kind"] not in kinds:
                raise fail(
                    "FEATURE_NOT_FOUND",
                    f"Surface not found: {surface!r}",
                    "Use Surface-ExtrudeN from list_features",
                    requested=surface,
                )
        else:
            src = sheets[-1] if sheets else None
        if src is None:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "No sheet to fillet",
                "extrude_surface an open sheet, then fillet_surface",
            )
        idx = int(edge)
        if idx < 0 or idx > 1:
            raise fail(
                "INVALID_ARGUMENT",
                f"Edge index out of range: {idx}",
                "Circular surface extrude has two open edges; use edge 0 or 1",
                index=idx,
            )
        n = sum(1 for x in doc.features if x["kind"] == "fillet_surface") + 1
        bbox = src.get("bbox3d") or (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        feat = {
            "kind": "fillet_surface",
            "name": f"Surface-Fillet{n}",
            "sign": 0,
            "bbox3d": bbox,
            "source": src["name"],
            "radius": float(radius_m),
            "edge": idx,
        }
        doc.features.append(feat)
        doc.modified = True
        return FeatureInfo(name=feat["name"], kind="fillet_surface")

    # ---------- Untrim ----------

    def untrim_surface(self, surface: str | None = None) -> FeatureInfo:
        self._enter("untrim_surface", surface=surface)
        doc = self._require_part("Use a part document to untrim a surface")
        if doc.open_sketch is not None:
            raise fail(
                "SKETCH_OP_FAILED",
                f"Sketch {doc.open_sketch.name or ''} is still open; cannot create a feature",
                "Call end_sketch to close the sketch, then untrim_surface",
            )
        sheets = self._sheet_features(doc)
        kinds = {
            "extrude_surface",
            "knit",
            "fill_surface",
            "boundary_surface",
            "trim_surface",
            "extend_surface",
            "fillet_surface",
            "untrim_surface",
        }
        if surface is not None:
            src = next((x for x in doc.features if x["name"] == str(surface)), None)
            if src is None or src["kind"] not in kinds:
                raise fail(
                    "FEATURE_NOT_FOUND",
                    f"Surface not found: {surface!r}",
                    "Use Surface-TrimN / Surface-ExtrudeN from list_features",
                    requested=surface,
                )
        else:
            src = sheets[-1] if sheets else None
        if src is None:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "No sheet to untrim",
                "trim_surface first, then untrim_surface",
            )
        n = sum(1 for x in doc.features if x["kind"] == "untrim_surface") + 1
        bbox = src.get("bbox3d") or (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        feat = {
            "kind": "untrim_surface",
            "name": f"Surface-Untrim{n}",
            "sign": 0,
            "bbox3d": bbox,
            "source": src["name"],
        }
        doc.features.append(feat)
        doc.modified = True
        return FeatureInfo(name=feat["name"], kind="untrim_surface")

    # ---------- Rib ----------

    def rib(self, thickness_m: float, sketch: str | None = None) -> FeatureInfo:
        self._enter("rib", thickness=thickness_m, sketch=sketch)
        doc, pending = self._pending_sketch(sketch)
        if thickness_m <= 0:
            raise fail("INVALID_ARGUMENT", "Rib thickness must be positive", "Pass thickness > 0")
        mats = [x for x in doc.features if x.get("sign", 0) > 0]
        if not mats:
            raise fail("FEATURE_CREATE_FAILED", "Rib requires an existing solid", "Extrude a base solid, then sketch the rib line")
        lines = [e for e in pending.entities if e.get("kind") == "line" and not e.get("construction")]
        if len(lines) != 1:
            raise fail("FEATURE_CREATE_FAILED", "Rib sketch needs one line", "sketch_line the rib path before end_sketch")
        ln = lines[0]
        length = math.hypot(float(ln["x1"] - ln["x0"]), float(ln["y1"] - ln["y0"]))
        if length <= 1e-12:
            raise fail("FEATURE_CREATE_FAILED", "Rib path length is zero", "Line endpoints cannot coincide")
        z0, z1 = self._solid_z_span(doc)
        span = z1 - z0
        n = sum(1 for x in doc.features if x["kind"] == "rib") + 1
        vol = length * float(thickness_m) * span
        feat = {
            "kind": "rib", "sign": 1, "name": f"Rib{n}",
            "vol": vol, "surf": 2 * (length * span + length * thickness_m + span * thickness_m),
            "faces": 6, "edges": 12,
            "bbox3d": (
                min(float(x["bbox3d"][0]) for x in mats),
                min(float(x["bbox3d"][1]) for x in mats),
                z0,
                max(float(x["bbox3d"][3]) for x in mats),
                max(float(x["bbox3d"][4]) for x in mats),
                z1,
            ),
            "com": (0.0, 0.0, 0.0),
        }
        doc.features.append(feat)
        self._consume_sketch(doc, pending)
        doc.modified = True
        return FeatureInfo(name=feat["name"], kind="rib")

    # ---------- Draft ----------

    def draft(
        self, angle_rad: float, faces: Sequence[int], neutral: int, flip: bool = False
    ) -> FeatureInfo:
        self._enter("draft", angle=angle_rad, faces=list(faces), neutral=neutral, flip=flip)
        doc = self._require_doc()
        if angle_rad <= 0 or angle_rad >= math.pi / 2:
            raise fail("INVALID_ARGUMENT", "Draft angle must be in (0, 90) degrees", "Pass angle_deg, e.g. 5")
        if not faces:
            raise fail("INVALID_ARGUMENT", "faces cannot be empty", "Pass get_faces indexes to draft")
        pool = self.list_faces()
        if not pool:
            raise fail("FEATURE_CREATE_FAILED", "No faces available for draft", "Extrude a base body first")
        self._checked_indexes(list(faces) + [neutral], len(pool), "face", "get_faces")
        if int(neutral) in {int(i) for i in faces}:
            raise fail("INVALID_ARGUMENT", "Neutral face cannot also be listed in faces", "Use another plane for neutral")
        n = sum(1 for x in doc.features if x["kind"] == "draft") + 1
        k = math.tan(float(angle_rad)) * 0.05
        for m in [x for x in doc.features if x.get("sign", 0) > 0]:
            m["vol"] = float(m.get("vol") or 0.0) * (1.0 - k)
            m["surf"] = float(m.get("surf") or 0.0) * (1.0 + k)
            bb = list(m["bbox3d"])
            bb[0] -= 1e-7
            bb[3] += 1e-7
            m["bbox3d"] = tuple(bb)
        feat = {
            "kind": "draft", "sign": 0, "name": f"Draft{n}",
            "vol": 0.0, "surf": 0.0, "faces": 0, "edges": 0,
            "angle": float(angle_rad), "flip": bool(flip),
        }
        doc.features.append(feat)
        doc.modified = True
        return FeatureInfo(name=feat["name"], kind="draft")
        