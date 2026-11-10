"""Fake backend · feature domain · extrude/cut（S8e-1）。

S8e-1：extrude_blind / extrude_cut / _apply_extrude_geom / _thin_section_area /
       _upto_z_range / _solid_z_span + _profile_of / _polygon_profile / _chain_profile。

Dependencies (self, MRO):
- `_enter` / `_require_doc` / `_require_part` / `_put_length_dim` / `list_faces`（FakeBackend）
- `_pending_sketch` / `_consume_sketch`（FakeSketchMixin）
- `_plane_frame` / `_uv_xyz`（FakePlaneAxisMixin）
- `_ray_hit_t`（FakeBackend，S8b alias）

Imports:
- `cadmcp.backend.protocol.constants`（EXTRUDE_DEPTHLESS）
- `cadmcp.backend.protocol.geometry_engine`（extrude_z_range_m）
- `cadmcp.backend.protocol.models`（FeatureInfo）
- `cadmcp.backend.protocol.validators`（validate_extrude_options / validate_thin_options）
- `cadmcp.errors`（fail）
- `.._engine` (_ray_hit_t via FakeBackend alias, not imported directly)
- `.._state`（_Doc / _Sketch / _CHAIN_TOL / _vadd / _vmul）
"""
from __future__ import annotations

import math

from cadmcp.backend.protocol.constants import EXTRUDE_DEPTHLESS
from cadmcp.backend.protocol.geometry_engine import extrude_z_range_m
from cadmcp.backend.protocol.models import FeatureInfo
from cadmcp.backend.protocol.validators import (
    validate_extrude_options,
    validate_thin_options,
)
from cadmcp.errors import fail

from .._state import _CHAIN_TOL, _Doc, _Sketch, _vadd, _vmul


class FakeExtrudeMixin:
    """extrude/cut + profile parse (S8e-1: 7 methods)."""

    def _init_state(self) -> None:
        pass

    # ---------- Extrude ----------

    def extrude_blind(
        self,
        depth_m: float,
        sketch: str | None = None,
        *,
        direction: str = "blind",
        depth2_m: float | None = None,
        reverse: bool = False,
        end_face: int | None = None,
        end_vertex: int | None = None,
        end_body: int | None = None,
        merge: bool = True,
        thin: bool = False,
        thickness_m: float | None = None,
        thin_type: str = "one",
    ) -> FeatureInfo:
        self._enter(
            "extrude_blind",
            depth=depth_m, sketch=sketch, direction=direction, depth2=depth2_m,
            reverse=reverse, end_face=end_face, end_vertex=end_vertex,
            end_body=end_body, merge=merge,
            thin=thin, thickness=thickness_m, thin_type=thin_type,
        )
        doc, pending = self._pending_sketch(sketch)
        validate_extrude_options(direction, depth2_m, end_face, end_vertex, end_body)
        validate_thin_options(thin, thickness_m, thin_type, direction)
        if direction not in EXTRUDE_DEPTHLESS and depth_m <= 0:
            raise fail(
                "INVALID_ARGUMENT",
                f"Extrude depth must be positive (internal meters): {depth_m}",
                "Pass depth > 0 (unit from unit param, default mm)",
            )
        hit_face = end_face
        upto_dir = direction
        if direction == "up_to_body":
            hit_face = self._resolve_body_hit_face(doc, int(end_body))
            upto_dir = "up_to_surface"
        f = self._profile_of(pending)
        if thin:
            f["area"] = self._thin_section_area(f, float(thickness_m), thin_type)
        if direction == "through_all":
            z0, z1 = self._solid_z_span(doc)
        elif direction in ("up_to_next", "up_to_surface", "up_to_vertex", "up_to_body"):
            z0, z1 = self._upto_z_range(
                pending, upto_dir, reverse, hit_face, end_vertex
            )
        else:
            z0, z1 = extrude_z_range_m(depth_m, direction, depth2_m, reverse)
        n = sum(1 for x in doc.features if x["kind"] == "extrude") + 1
        f.update(
            kind="extrude", sign=1, depth=depth_m, name=f"Boss-Extrude{n}",
            direction=direction, reverse=reverse, depth2=depth2_m,
            plane=pending.plane, end_face=hit_face, end_vertex=end_vertex,
            end_body=end_body,
            thin=thin, thin_type=thin_type, thickness=thickness_m,
        )
        self._apply_extrude_geom(f, z0, z1)
        f["source_sketch"] = pending
        doc.features.append(f)
        if direction not in EXTRUDE_DEPTHLESS:
            self._put_length_dim(doc, f"D1@{f['name']}", depth_m, f, "depth")
        if direction == "both" and depth2_m is not None:
            self._put_length_dim(doc, f"D2@{f['name']}", depth2_m, f, "depth2")
        self._consume_sketch(doc, pending)  # profile consumed by feature
        doc.modified = True
        return FeatureInfo(name=f["name"], kind="extrude")

    def _apply_extrude_geom(self, feat: dict, z0: float, z1: float) -> None:
        x0, y0, x1, y1 = feat["bbox2d"]
        thick = z1 - z0
        feat["vol"] = feat["area"] * thick
        if feat["kind"] in ("extrude", "base_flange"):
            feat["surf"] = 2 * feat["area"] + feat["perimeter"] * thick
        else:
            feat["surf"] = feat["area"] + feat["perimeter"] * thick
        origin, uu, vv, nn = self._plane_frame(str(feat.get("plane") or "Front Plane"))
        feat["com"] = _vadd(
            origin, _vmul(uu, (x0 + x1) / 2), _vmul(vv, (y0 + y1) / 2), _vmul(nn, (z0 + z1) / 2)
        )
        corners: list[tuple[float, float, float]] = []
        for u in (x0, x1):
            for v in (y0, y1):
                base = _vadd(origin, _vmul(uu, u), _vmul(vv, v))
                corners.append(_vadd(base, _vmul(nn, z0)))
                corners.append(_vadd(base, _vmul(nn, z1)))
        xs, ys, zs = zip(*corners, strict=True)
        bbox = (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))
        # Same as loft: real GetPartBox barely counts zero-thickness sketch; up-to face/vertex/body bosses expand bbox.
        if feat.get("direction") in (
            "up_to_next", "up_to_surface", "up_to_vertex", "up_to_body",
        ):
            pad = 1e-7
            bbox = (bbox[0] - pad, bbox[1] - pad, bbox[2] - pad, bbox[3] + pad, bbox[4] + pad, bbox[5] + pad)
        feat["bbox3d"] = bbox

    @staticmethod
    def _thin_section_area(feat: dict, thickness_m: float, thin_type: str) -> float:
        x0, y0, x1, y1 = feat["bbox2d"]
        w, h = abs(x1 - x0), abs(y1 - y0)
        t = float(thickness_m)
        if feat.get("profile") == "circle":
            r = 0.5 * min(w, h)
            if thin_type == "mid":
                r_out, r_in = r + t / 2.0, max(0.0, r - t / 2.0)
            elif thin_type == "both":
                r_out, r_in = r + t, max(0.0, r - t)
            else:
                r_out, r_in = r, max(0.0, r - t)
            return math.pi * (r_out * r_out - r_in * r_in)
        if thin_type == "mid":
            wo, ho, wi, hi = w + t, h + t, max(0.0, w - t), max(0.0, h - t)
        elif thin_type == "both":
            wo, ho, wi, hi = w + 2 * t, h + 2 * t, max(0.0, w - 2 * t), max(0.0, h - 2 * t)
        else:
            wo, ho, wi, hi = w, h, max(0.0, w - 2 * t), max(0.0, h - 2 * t)
        return wo * ho - wi * hi

    def extrude_cut(
        self,
        depth_m: float,
        sketch: str | None = None,
        *,
        direction: str = "blind",
        depth2_m: float | None = None,
        reverse: bool | None = None,
        end_face: int | None = None,
        end_vertex: int | None = None,
        end_body: int | None = None,
        thin: bool = False,
        thickness_m: float | None = None,
        thin_type: str = "one",
    ) -> FeatureInfo:
        self._enter(
            "extrude_cut",
            depth=depth_m, sketch=sketch, direction=direction, depth2=depth2_m,
            reverse=reverse, end_face=end_face, end_vertex=end_vertex,
            end_body=end_body,
            thin=thin, thickness=thickness_m, thin_type=thin_type,
        )
        doc, pending = self._pending_sketch(sketch)
        validate_extrude_options(direction, depth2_m, end_face, end_vertex, end_body)
        validate_thin_options(thin, thickness_m, thin_type, direction)
        if direction not in EXTRUDE_DEPTHLESS and depth_m <= 0:
            raise fail(
                "INVALID_ARGUMENT",
                f"Cut depth must be positive (internal meters): {depth_m}",
                "Pass depth > 0 (unit from unit param, default mm)",
            )
        if not any(x["sign"] > 0 for x in doc.features):
            raise fail(
                "FEATURE_CREATE_FAILED",
                "No material to cut (no solid features yet)",
                "Create a base solid with extrude or revolve before cut",
            )
        hit_face = end_face
        upto_dir = direction
        if direction == "up_to_body":
            hit_face = self._resolve_body_hit_face(doc, int(end_body))
            upto_dir = "up_to_surface"
        f = self._profile_of(pending)
        if thin:
            f["area"] = self._thin_section_area(f, float(thickness_m), thin_type)
        if direction == "through_all":
            z0, z1 = self._solid_z_span(doc)
        elif direction in ("up_to_next", "up_to_surface", "up_to_vertex", "up_to_body"):
            z0, z1 = self._upto_z_range(
                pending, upto_dir, bool(reverse), hit_face, end_vertex
            )
        else:
            z0, z1 = extrude_z_range_m(depth_m, direction, depth2_m, bool(reverse))
        n = sum(1 for x in doc.features if x["kind"] == "extrude_cut") + 1
        f.update(
            kind="extrude_cut", sign=-1, depth=depth_m, name=f"Cut-Extrude{n}",
            direction=direction, reverse=bool(reverse), depth2=depth2_m,
            plane=pending.plane, end_face=hit_face, end_vertex=end_vertex,
            end_body=end_body,
            faces=2, edges=4,  # canned: +1 bottom + open loop
            thin=thin, thin_type=thin_type, thickness=thickness_m,
        )
        self._apply_extrude_geom(f, z0, z1)
        f["source_sketch"] = pending
        doc.features.append(f)
        if direction not in EXTRUDE_DEPTHLESS:
            self._put_length_dim(doc, f"D1@{f['name']}", depth_m, f, "depth")
        if direction == "both" and depth2_m is not None:
            self._put_length_dim(doc, f"D2@{f['name']}", depth2_m, f, "depth2")
        self._consume_sketch(doc, pending)
        doc.modified = True
        return FeatureInfo(name=f["name"], kind="extrude_cut")

    def _resolve_body_hit_face(self, doc: _Doc, end_body: int) -> int:
        """Fake single-body: pick plane with max centroid z (aligns COM Front offset scenario)."""
        mats = [x for x in doc.features if x.get("sign", 0) > 0]
        n_bodies = 1 if mats else 0
        if n_bodies == 0:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "Up-to-body extrude requires an existing solid",
                "Extrude a base body first, then direction=up_to_body",
            )
        if end_body < 0 or end_body >= n_bodies:
            raise fail(
                "INVALID_ARGUMENT",
                f"Body index out of range: {end_body}",
                f"Valid range 0..{n_bodies - 1}; single-body parts are usually 0",
                index=end_body,
            )
        planes = [
            f for f in self.list_faces()
            if f.kind == "plane" and f.normal_m is not None
        ]
        if not planes:
            raise fail(
                "FEATURE_CREATE_FAILED",
                f"Body {end_body} has no usable planar end face",
                "Change end_body, or use direction=up_to_surface with end_face",
                index=end_body,
            )
        return max(planes, key=lambda f: f.centroid_m[2]).index

    def _upto_z_range(
        self,
        pending: _Sketch,
        direction: str,
        reverse: bool,
        end_face: int | None,
        end_vertex: int | None = None,
    ) -> tuple[float, float]:
        origin, uu, vv, nn = self._plane_frame(str(pending.plane))
        x0, y0, x1, y1 = self._profile_of(pending)["bbox2d"]
        p0 = _vadd(origin, _vmul(uu, (x0 + x1) / 2), _vmul(vv, (y0 + y1) / 2))
        if direction == "up_to_vertex":
            verts = self.list_vertices()
            if not verts:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Up-to-vertex extrude requires an existing solid",
                    "Extrude a base body first, then direction=up_to_vertex",
                )
            idx = int(end_vertex)  # type: ignore[arg-type]
            if idx < 0 or idx >= len(verts):
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Vertex index out of range: {idx}",
                    f"Use get_vertices; valid range 0..{len(verts) - 1}",
                    index=idx,
                )
            vx, vy, vz = verts[idx].position_m
            delta = (vx - p0[0], vy - p0[1], vz - p0[2])
            n_dir = _vmul(nn, -1.0 if reverse else 1.0)
            t = delta[0] * n_dir[0] + delta[1] * n_dir[1] + delta[2] * n_dir[2]
            if t <= 1e-12:
                n_dir = _vmul(nn, 1.0 if reverse else -1.0)
                t = delta[0] * n_dir[0] + delta[1] * n_dir[1] + delta[2] * n_dir[2]
                reverse = not reverse
            if t <= 1e-12:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Sketch normal cannot reach end vertex",
                    "Try reverse, or verify end_vertex with get_vertices",
                )
            if reverse:
                return (-t, 0.0)
            return (0.0, t)

        faces = self.list_faces()
        if direction == "up_to_surface":
            if not faces:
                raise fail(
                    "INVALID_ARGUMENT",
                    "No solid face usable as end face",
                    "Extrude a base body first, then use get_faces for index",
                )
            idx = int(end_face)  # type: ignore[arg-type]
            if idx < 0 or idx >= len(faces):
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Face index out of range: {idx}",
                    f"Use get_faces；Valid range 0..{len(faces) - 1}",
                    index=idx,
                )
            pool = [faces[idx]]
            if pool[0].kind != "plane" or pool[0].normal_m is None:
                raise fail(
                    "INVALID_ARGUMENT",
                    f"End face {idx} is not a plane",
                    "up_to_surface needs a face with kind=plane from get_faces",
                    index=idx,
                )
        else:
            pool = list(faces)
            if not pool:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Up-to-next extrude requires an existing solid",
                    "Extrude a base body first, then direction=up_to_next",
                )

        def _nearest(rev: bool) -> float | None:
            n_dir = _vmul(nn, -1.0 if rev else 1.0)
            hit: float | None = None
            for fr in pool:
                t = self._ray_hit_t(p0, n_dir, fr)
                if t is None:
                    continue
                if hit is None or t < hit:
                    hit = t
            return hit

        t = _nearest(reverse)
        used_rev = reverse
        if t is None:
            t = _nearest(not reverse)
            used_rev = not reverse
        if t is None:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "Sketch normal cannot hit end face",
                "Try reverse, or verify end_face with get_faces",
            )
        if used_rev:
            return (-t, 0.0)
        return (0.0, t)

    def _solid_z_span(self, doc: _Doc) -> tuple[float, float]:
        mats = [x for x in doc.features if x.get("sign", 0) > 0]
        if not mats:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "Through-all extrude requires an existing solid",
                "Extrude a base body first, then direction=through_all",
            )
        z0 = min(float(x["bbox3d"][2]) for x in mats)
        z1 = max(float(x["bbox3d"][5]) for x in mats)
        if z1 - z0 <= 1e-12:
            raise fail("FEATURE_CREATE_FAILED", "Solid thickness is zero; cannot through-all", "Create a base body with thickness first")
        return z0, z1

    # ---------- Profile parse ----------

    def _profile_of(self, sk: _Sketch) -> dict:
        if not sk.entities:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "Sketch is empty; no usable profile",
                "sketch_rectangle or sketch_circle for a closed profile, then end_sketch",
            )
        rects = [e for e in sk.entities if e.get("kind") == "rect" and not e.get("construction")]
        if len(rects) == 2 and all(
            e.get("kind") == "rect" or e.get("construction") for e in sk.entities
        ):
            def _ra(e: dict) -> float:
                return abs(float(e["x1"] - e["x0"]) * float(e["y1"] - e["y0"]))

            a0, a1 = _ra(rects[0]), _ra(rects[1])
            if a0 != a1:
                outer, inner = (rects[0], rects[1]) if a0 > a1 else (rects[1], rects[0])

                def _bb(e: dict) -> tuple[float, float, float, float]:
                    return (
                        min(float(e["x0"]), float(e["x1"])),
                        min(float(e["y0"]), float(e["y1"])),
                        max(float(e["x0"]), float(e["x1"])),
                        max(float(e["y0"]), float(e["y1"])),
                    )

                ox0, oy0, ox1, oy1 = _bb(outer)
                ix0, iy0, ix1, iy1 = _bb(inner)
                if ox0 <= ix0 and oy0 <= iy0 and ox1 >= ix1 and oy1 >= iy1:
                    def _peri(e: dict) -> float:
                        return 2.0 * (
                            abs(float(e["x1"] - e["x0"])) + abs(float(e["y1"] - e["y0"]))
                        )

                    return {
                        "profile": "frame",
                        "area": abs(a0 - a1),
                        "perimeter": _peri(rects[0]) + _peri(rects[1]),
                        "bbox2d": (ox0, oy0, ox1, oy1),
                        "faces": 10, "edges": 16,
                    }
        if len(sk.entities) == 2 and all(e.get("kind") == "circle" for e in sk.entities):
            c0, c1 = sk.entities
            if (c0["cx"], c0["cy"]) != (c1["cx"], c1["cy"]) or c0["r"] == c1["r"]:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Two-circle profile must be concentric with different radii",
                    "Draw two concentric circles on one sketch for a tube",
                )
            r_out, r_in = max(c0["r"], c1["r"]), min(c0["r"], c1["r"])
            cx, cy = c0["cx"], c0["cy"]
            return {
                "profile": "tube",
                "area": math.pi * (r_out * r_out - r_in * r_in),
                "perimeter": 2 * math.pi * (r_out + r_in),
                "bbox2d": (cx - r_out, cy - r_out, cx + r_out, cy + r_out),
                "faces": 4, "edges": 4,
                "r_in": r_in, "r_out": r_out,
            }
        poly = self._polygon_profile(sk)
        if poly is not None:
            return poly
        chain = self._chain_profile(sk)
        if chain is not None:
            return chain
        if len(sk.entities) != 1:
            kinds = ", ".join(e["kind"] for e in sk.entities)
            raise fail(
                "FEATURE_CREATE_FAILED",
                f"Unsupported profile: sketch has {len(sk.entities)} entities ({kinds})",
                "fake supports one rectangle, one circle, two concentric circles, closed polygon, or closed line+arc chain (slot/R)",
            )
        e = sk.entities[0]
        if e["kind"] == "spline":
            pts = [(float(p[0]), float(p[1])) for p in (e.get("points") or ())]
            if not e.get("closed") or len(pts) < 4:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Open spline cannot extrude to a solid",
                    "Pass closed=true with at least 3 distinct points",
                )
            ring = pts[:-1] if pts[0] == pts[-1] else pts
            area = 0.0
            peri = 0.0
            n = len(ring)
            for i in range(n):
                x0, y0 = ring[i]
                x1, y1 = ring[(i + 1) % n]
                area += x0 * y1 - x1 * y0
                peri += math.hypot(x1 - x0, y1 - y0)
            area = abs(area) * 0.5
            if area <= 0:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Closed spline has zero area",
                    "Point set must not be colinear",
                )
            xs = [p[0] for p in ring]
            ys = [p[1] for p in ring]
            return {
                "profile": "spline",
                "area": area,
                "perimeter": peri,
                "bbox2d": (min(xs), min(ys), max(xs), max(ys)),
                "faces": 3,
                "edges": 2,
            }
        if e["kind"] == "rect":
            w, h = abs(e["x1"] - e["x0"]), abs(e["y1"] - e["y0"])
            return {
                "profile": "rect", "area": w * h, "perimeter": 2 * (w + h),
                "bbox2d": (min(e["x0"], e["x1"]), min(e["y0"], e["y1"]),
                           max(e["x0"], e["x1"]), max(e["y0"], e["y1"])),
                "faces": 6, "edges": 12,
            }
        if e["kind"] == "circle":
            r = e["r"]
            return {
                "profile": "circle", "area": math.pi * r * r, "perimeter": 2 * math.pi * r,
                "bbox2d": (e["cx"] - r, e["cy"] - r, e["cx"] + r, e["cy"] + r),
                "faces": 3, "edges": 2,
            }
        raise fail(
            "FEATURE_CREATE_FAILED",
            f"Open profile {e.get('kind')!r} cannot extrude to a solid",
            "Solid extrude needs closed rect/circle; open curves use extrude_surface",
        )

    @staticmethod
    def _polygon_profile(sk: _Sketch) -> dict | None:
        lines = [e for e in sk.entities if e.get("kind") == "line"]
        if len(lines) < 3 or len(lines) != len(sk.entities):
            return None
        unused = list(lines)
        pts = [(unused[0]["x0"], unused[0]["y0"]), (unused[0]["x1"], unused[0]["y1"])]
        unused.pop(0)
        while unused:
            tx, ty = pts[-1]
            hit = None
            for i, e in enumerate(unused):
                ends = ((e["x0"], e["y0"]), (e["x1"], e["y1"]))
                for j, (ax, ay) in enumerate(ends):
                    if math.hypot(ax - tx, ay - ty) > 1e-9:
                        continue
                    ox, oy = ends[1 - j]
                    pts.append((ox, oy))
                    hit = i
                    break
                if hit is not None:
                    break
            if hit is None:
                return None
            unused.pop(hit)
        if math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) > 1e-6:
            return None
        ring = pts[:-1]
        area = 0.5 * abs(
            sum(ring[i][0] * ring[(i + 1) % len(ring)][1] - ring[(i + 1) % len(ring)][0] * ring[i][1]
                for i in range(len(ring)))
        )
        if area <= 0:
            return None
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        n = len(ring)
        peri = sum(
            math.hypot(ring[(i + 1) % n][0] - ring[i][0], ring[(i + 1) % n][1] - ring[i][1])
            for i in range(n)
        )
        return {
            "profile": "polygon",
            "area": area,
            "perimeter": peri,
            "bbox2d": (min(xs), min(ys), max(xs), max(ys)),
            "faces": n + 2,
            "edges": 3 * n,
        }

    @staticmethod
    def _chain_profile(sk: _Sketch) -> dict | None:
        ents = [e for e in sk.entities if e.get("kind") in {"line", "arc"}]
        if len(ents) < 2 or len(ents) != len(sk.entities) or not any(e["kind"] == "arc" for e in ents):
            return None
        unused = list(ents)
        first = unused.pop(0)
        path: list[tuple[dict, bool]] = [(first, False)]
        curr = (first["x1"], first["y1"])
        start = (first["x0"], first["y0"])
        while unused:
            hit = None
            for i, e in enumerate(unused):
                a, b = (e["x0"], e["y0"]), (e["x1"], e["y1"])
                if math.hypot(a[0] - curr[0], a[1] - curr[1]) <= _CHAIN_TOL:
                    hit = (i, e, False, b)
                    break
                if math.hypot(b[0] - curr[0], b[1] - curr[1]) <= _CHAIN_TOL:
                    hit = (i, e, True, a)
                    break
            if hit is None:
                return None
            i, e, rev, nxt = hit
            unused.pop(i)
            path.append((e, rev))
            curr = nxt
        if math.hypot(curr[0] - start[0], curr[1] - start[1]) > 1e-6:
            return None
        verts: list[tuple[float, float]] = []
        peri = 0.0
        extra = 0.0
        for e, rev in path:
            a, b = (e["x0"], e["y0"]), (e["x1"], e["y1"])
            if rev:
                a, b = b, a
            verts.append(a)
            if e["kind"] == "line":
                peri += math.hypot(b[0] - a[0], b[1] - a[1])
            else:
                sweep = -float(e["sweep"]) if rev else float(e["sweep"])
                peri += abs(e["r"] * sweep)
                extra += 0.5 * e["r"] * e["r"] * (sweep - math.sin(sweep))
        n = len(verts)
        signed = 0.5 * sum(
            verts[i][0] * verts[(i + 1) % n][1] - verts[(i + 1) % n][0] * verts[i][1]
            for i in range(n)
        )
        area = abs(signed + extra)
        if area <= 0:
            return None
        xs = [p[0] for p in verts]
        ys = [p[1] for p in verts]
        for e, _ in path:
            if e["kind"] != "arc":
                continue
            for t in (0.25, 0.5, 0.75):
                ang = math.atan2(e["y0"] - e["cy"], e["x0"] - e["cx"]) + t * e["sweep"]
                xs.append(e["cx"] + e["r"] * math.cos(ang))
                ys.append(e["cy"] + e["r"] * math.sin(ang))
        return {
            "profile": "chain",
            "area": area,
            "perimeter": peri,
            "bbox2d": (min(xs), min(ys), max(xs), max(ys)),
            "faces": n + 2,
            "edges": 3 * n,
        }
        