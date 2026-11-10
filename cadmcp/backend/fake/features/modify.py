"""Fake backend · feature domain · detail features（S8e-5）。

S8e-5: fillet/chamfer/shell/linear/circular pattern/mirror/combine/split/hole wizard
       + 6 geometry/selection helpers.

Dependencies (self, MRO):
- `_enter` / `_require_doc`（FakeBackend）
- `_require_part`（FakeQueryMixin，S8e-3）
- `_resolve_plane_name` / `_plane_frame`（FakePlaneAxisMixin，S8d-2）
- `_material_entities` / `list_faces`（FakeSelectionMixin，S8e-4）

Imports:
- `cadmcp.backend.protocol.constants`（COMBINE_OPS / HOLE_WIZARD_ENDS）
- `cadmcp.backend.protocol.models`（FeatureInfo）
- `cadmcp.errors`（fail）
- `.._engine`（_reflect_point / _reflected_bbox / _rotate_point / _rotated_bbox）
- `.._state`（_vdot）
"""
from __future__ import annotations

import math
from collections.abc import Sequence

from cadmcp.backend.protocol.constants import COMBINE_OPS, HOLE_WIZARD_ENDS
from cadmcp.backend.protocol.models import FeatureInfo
from cadmcp.errors import fail

from .._engine import (
    _reflect_point,
    _reflected_bbox,
    _rotate_point,
    _rotated_bbox,
)
from .._state import _vdot


class FakeModifyMixin:
    """detail features (S8e-5: 19 methods)."""

    def _init_state(self) -> None:
        pass  # State owned by FakeBackend._init_state

    # ---------- Geometry/selection helpers ----------

    @staticmethod
    def _extents(f: dict) -> tuple[float, float, float]:
        b = f["bbox3d"]
        return (b[3] - b[0], b[4] - b[1], b[5] - b[2])

    @staticmethod
    def _edge_length(f: dict) -> float:
        dx, dy, dz = FakeModifyMixin._extents(f)
        return 4.0 * (dx + dy + dz)  # prism 12-edge approximation (canned)

    def _edge_count(self) -> int:
        return sum(int(f.get("edges") or 0) for f in self._material_entities())

    def _checked_indexes(
        self, indexes: Sequence[int] | None, n_total: int, what: str, listing: str
    ) -> int | None:
        if indexes is None:
            return None
        if not indexes:
            raise fail("INVALID_ARGUMENT", f"{what} index list cannot be empty", f"Pass {listing} indexes from ")
        seen: set[int] = set()
        for raw in indexes:
            idx = int(raw)
            if idx < 0 or idx >= n_total:
                raise fail(
                    "INVALID_ARGUMENT",
                    f"{what}index out of range: {idx}",
                    f"Use {listing}; valid range 0..{max(n_total - 1, 0)}",
                    index=idx,
                )
            seen.add(idx)
        return len(seen)

    def _material_features(self, doc, target: str | None, op: str, hint: str) -> list[dict]:
        mats = [x for x in doc.features if x["sign"] > 0]
        if not mats:
            raise fail("FEATURE_CREATE_FAILED", f"No {op} edges (no solid features yet)", hint)
        if target is not None:
            hit = [x for x in mats if x["name"] == target]
            if not hit:
                raise fail(
                    "FEATURE_NOT_FOUND",
                    f"Solid feature not found: {target!r}",
                    "Use list_features; fillet/chamfer target solid features only",
                    requested=target,
                )
            return hit
        return mats

    def _pattern_source(self, doc, target: str) -> dict:
        """Pattern seed: boss or cut (cut circular pattern is the reliable real flange-hole path)."""
        hit = [x for x in doc.features if x["name"] == target and "vol" in x]
        if not hit:
            raise fail(
                "FEATURE_NOT_FOUND",
                f"Solid feature not found: {target!r}",
                "Use list_features; fillet/chamfer target solid features only",
                requested=target,
            )
        return hit[0]

    # ---------- Common detail-cut path ----------

    def _detail_cut(
        self,
        mats: list[dict],
        x_m: float,
        k: float,
        a: float,
        kind: str,
        op: str,
        unit_hint: str,
        edge_count: int | None = None,
    ) -> FeatureInfo:
        doc = self._require_doc()
        if x_m <= 0:
            raise fail(
                "INVALID_ARGUMENT", f"{op} size must be positive (meters internally): {x_m}", f"Pass {unit_hint} > 0"
            )
        for f in mats:
            ext = min(self._extents(f))
            if x_m >= 0.5 * ext:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    f"{op} size {x_m} m exceeds machinable range of feature {f['name']} (min extent {ext} m)",
                    f"Reduce {unit_hint} (must be less than half the min extent)",
                )
        l_eff = sum(self._edge_length(f) for f in mats)
        e_total = sum(f["edges"] for f in mats)
        if edge_count is not None:
            if e_total <= 0:
                raise fail("FEATURE_CREATE_FAILED", f"No edges available for {op}", "Create a solid with extrude or revolve first")
            l_eff = l_eff * (edge_count / e_total)
            e_total = edge_count
        n = sum(1 for x in doc.features if x["kind"] == kind) + 1
        f = {
            "kind": kind, "sign": -1, "name": f"{op}{n}",
            "vol": k * x_m**2 * l_eff, "surf": a * x_m * l_eff,
            "faces": e_total, "edges": e_total,  # face count + edges, edge count doubled (canned)
        }
        doc.features.append(f)
        doc.modified = True
        return FeatureInfo(name=f["name"], kind=kind)

    # ---------- Fillet / chamfer / shell ----------

    def fillet_blind(
        self,
        radius_m: float,
        target: str | None = None,
        edge_indexes: list[int] | None = None,
    ) -> FeatureInfo:
        self._enter("fillet_blind", radius=radius_m, target=target, edges=edge_indexes)
        doc = self._require_doc()
        n_sel = self._checked_indexes(edge_indexes, self._edge_count(), "edge", "get_edges")
        mats = self._material_features(
            doc,
            None if edge_indexes is not None else target,
            "fillet",
            "Create a solid with extrude or revolve first",
        )
        return self._detail_cut(
            mats,
            radius_m,
            1.0 - math.pi / 4,
            2.0 - math.pi / 2,
            "fillet",
            "Fillet",
            "radius",
            edge_count=n_sel,
        )

    def chamfer_blind(
        self,
        distance_m: float,
        target: str | None = None,
        edge_indexes: list[int] | None = None,
        angle_rad: float = math.pi / 4,
    ) -> FeatureInfo:
        self._enter(
            "chamfer_blind", distance=distance_m, target=target, edges=edge_indexes, angle=angle_rad
        )
        if angle_rad <= 0 or angle_rad >= math.pi / 2:
            raise fail("INVALID_ARGUMENT", "Chamfer angle must be between (0, 90) degrees", "Pass angle_deg, e.g. 30 or 45")
        doc = self._require_doc()
        if edge_indexes is not None:
            if not edge_indexes:
                raise fail("INVALID_ARGUMENT", "edges cannot be empty", "Pass get_edges indexes, or use target")
            n_edges = 0
            for f in self._material_entities():
                n_edges += int(f.get("edges") or 0)
            for raw in edge_indexes:
                idx = int(raw)
                if idx < 0 or idx >= n_edges:
                    raise fail(
                        "INVALID_ARGUMENT",
                        f"Edge index out of range: {idx}",
                        f"Use get_edges；Valid range 0..{max(n_edges - 1, 0)}",
                        index=idx,
                    )
        mats = self._material_features(
            doc,
            None if edge_indexes is not None else target,
            "chamfer",
            "Create a solid with extrude or revolve first",
        )
        tan_a = math.tan(angle_rad)
        k_vol = 0.5 * tan_a
        k_surf = 1.0 + tan_a - 1.0 / math.cos(angle_rad)
        return self._detail_cut(mats, distance_m, k_vol, k_surf, "chamfer", "Chamfer", "distance")

    def shell_blind(
        self, thickness_m: float, face_indexes: Sequence[int] | None = None
    ) -> FeatureInfo:
        self._enter("shell_blind", thickness=thickness_m, faces=face_indexes)
        doc = self._require_doc()
        mats = self._material_features(doc, None, "shell", "Create a solid with extrude or revolve first")
        if thickness_m <= 0:
            raise fail(
                "INVALID_ARGUMENT",
                f"Shell thickness must be positive (internal meters): {thickness_m}",
                "Pass thickness > 0",
            )
        n_faces = sum(min(int(f.get("faces") or 6), 6) for f in mats)
        self._checked_indexes(face_indexes, n_faces, "face", "get_faces")
        open_set = {int(i) for i in face_indexes} if face_indexes is not None else set()
        cavity = surf = 0.0
        faces_add = edges_add = 0
        face_cursor = 0
        for f in mats:
            ext = self._extents(f)
            if 2 * thickness_m >= min(ext):
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    f"Shell thickness {thickness_m} m exceeds half the min extent of feature {f['name']} ({min(ext)} m)",
                    "Reduce thickness (must be less than half the smallest bounding extent)",
                )
            a, b, c = (e - 2 * thickness_m for e in ext)
            inner = a * b * c
            # open faces: remove inner wall of thickness t; cavity grows by t * inner area
            slot_areas = (b * c, b * c, a * c, a * c, a * b, a * b)
            n_here = min(int(f.get("faces") or 6), 6)
            opened = 0
            for i in range(n_here):
                if (face_cursor + i) in open_set:
                    inner += thickness_m * slot_areas[i]
                    opened += 1
            face_cursor += n_here
            cavity += inner
            surf += 2 * (a * b + b * c + c * a)
            faces_add += 6 - opened
            edges_add += 12
        n = sum(1 for x in doc.features if x["kind"] == "shell") + 1
        feat = {
            "kind": "shell", "sign": -1, "name": f"Shell{n}",
            "vol": cavity, "surf": surf, "faces": faces_add, "edges": edges_add,
        }
        doc.features.append(feat)
        doc.modified = True
        return FeatureInfo(name=feat["name"], kind="shell")

    # ---------- Linear/circular patterns ----------

    def linear_pattern_blind(
        self, feature: str, dx_m: float, dy_m: float, dz_m: float, count: int
    ) -> FeatureInfo:
        self._enter(
            "linear_pattern_blind", feature=feature, dx=dx_m, dy=dy_m, dz=dz_m, count=count
        )
        doc = self._require_doc()
        src = self._material_features(doc, feature, "pattern", "Create a solid feature before patterning")[0]
        if count < 2:
            raise fail(
                "INVALID_ARGUMENT", f"Pattern instance count must be >= 2 (including seed): {count}", "Pass count >= 2"
            )
        if dx_m == 0.0 and dy_m == 0.0 and dz_m == 0.0:
            raise fail(
                "INVALID_ARGUMENT", "Pattern direction vector is zero", "At least one of dx/dy/dz must be non-zero (spacing vector)"
            )
        k = count - 1
        b = src["bbox3d"]
        boxes = [b] + [
            (
                b[0] + i * dx_m, b[1] + i * dy_m, b[2] + i * dz_m,
                b[3] + i * dx_m, b[4] + i * dy_m, b[5] + i * dz_m,
            )
            for i in range(1, count)
        ]
        bbox3d = (
            min(s[0] for s in boxes), min(s[1] for s in boxes), min(s[2] for s in boxes),
            max(s[3] for s in boxes), max(s[4] for s in boxes), max(s[5] for s in boxes),
        )
        n = sum(1 for x in doc.features if x["kind"] == "pattern") + 1
        sc = src["com"]
        m = (k + 1) / 2  # mean offset of all copies (seed at 0) — weighted equals overall centroid
        f = {
            "kind": "pattern", "sign": 1, "name": f"LPattern{n}",
            "vol": k * src["vol"], "surf": k * src["surf"],
            "faces": 0, "edges": 0,  # instances merge into body; topology adds no faces/edges (real probe)
            "com": (sc[0] + m * dx_m, sc[1] + m * dy_m, sc[2] + m * dz_m),
            "bbox3d": bbox3d,
        }
        doc.features.append(f)
        doc.modified = True
        return FeatureInfo(name=f["name"], kind="pattern")

    def circular_pattern_blind(
        self,
        feature: str,
        count: int,
        axis: str,
        edge_index: int | None = None,
    ) -> FeatureInfo:
        self._enter(
            "circular_pattern_blind",
            feature=feature,
            count=count,
            axis=axis,
            edge=edge_index,
        )
        doc = self._require_doc()
        src = self._pattern_source(doc, feature)
        if count < 2:
            raise fail(
                "INVALID_ARGUMENT", f"Pattern instance count must be >= 2 (including seed): {count}", "Pass count >= 2"
            )
        if axis not in ("+x", "-x", "+y", "-y", "+z", "-z"):
            raise fail(
                "INVALID_ARGUMENT",
                f"Unknown circular pattern axis: {axis!r}",
                "Axis: +x/-x/+y/-y/+z/-z",
                requested=axis,
            )
        if edge_index is not None:
            self._checked_indexes([edge_index], self._edge_count(), "edge", "get_edges")
        k = count - 1
        step = math.tau / count
        boxes = [
            _rotated_bbox(src["bbox3d"], axis, i * step) for i in range(count)
        ]
        bbox3d = (
            min(s[0] for s in boxes), min(s[1] for s in boxes), min(s[2] for s in boxes),
            max(s[3] for s in boxes), max(s[4] for s in boxes), max(s[5] for s in boxes),
        )
        n = sum(1 for x in doc.features if x["kind"] == "circular_pattern") + 1
        sign = int(src.get("sign") or 1)
        feat = {
            "kind": "circular_pattern",
            "sign": sign,
            "name": f"CirPattern{n}",
            "vol": k * src["vol"],
            "surf": k * src["surf"],
            # boss copies merge without new topology (same as linear pattern);
            # circular cut pattern: +1 cylinder face +2 circle edges per instance (real 1 hole 7/14 -> 4 holes 10/20).
            "faces": 0 if sign > 0 else k,
            "edges": 0 if sign > 0 else 2 * k,
        }
        if sign > 0:
            sc = src["com"]
            coms = [_rotate_point(sc, axis, i * step) for i in range(count)]
            feat["com"] = (
                sum(p[0] for p in coms) / count,
                sum(p[1] for p in coms) / count,
                sum(p[2] for p in coms) / count,
            )
            feat["bbox3d"] = bbox3d
        doc.features.append(feat)
        doc.modified = True
        return FeatureInfo(name=feat["name"], kind="circular_pattern")

    # ---------- Mirror ----------

    def mirror_feature(self, feature: str, plane: str, scope: str = "body") -> FeatureInfo:
        self._enter("mirror_feature", feature=feature, plane=plane, scope=scope)
        doc = self._require_part("Use a part document for mirror")
        if scope not in ("body", "feature"):
            raise fail(
                "INVALID_ARGUMENT",
                f"Unknown mirror scope: {scope!r}",
                "scope: body or feature",
                requested=scope,
            )
        src = self._pattern_source(doc, feature)
        resolved = self._resolve_plane_name(doc, plane)
        if resolved is None:
            raise fail(
                "INVALID_ARGUMENT",
                f"Reference plane not found: {plane!r}",
                f"Available reference planes: {', '.join(self._plane_names(doc))}",
                requested=plane,
            )
        origin, _u, _v, n = self._plane_frame(resolved)
        b = src["bbox3d"]
        mirrored = _reflected_bbox(b, origin, n)
        sc = src["com"]
        nfeat = sum(1 for x in doc.features if x["kind"] == "mirror") + 1
        sign = int(src.get("sign") or 1)
        f = {
            "kind": "mirror",
            "sign": sign,
            "name": f"Mirror{nfeat}",
            "vol": src["vol"],
            "surf": src["surf"],
            "faces": int(src.get("faces") or 0),
            "edges": int(src.get("edges") or 0),
            "com": _reflect_point(sc, origin, n),
            "bbox3d": mirrored,
        }
        doc.features.append(f)
        doc.modified = True
        return FeatureInfo(name=f["name"], kind="mirror")

    # ---------- Combine / split ----------

    def combine(self, op: str, keep: int = 0) -> FeatureInfo:
        self._enter("combine", op=op, keep=keep)
        if op not in COMBINE_OPS:
            raise fail(
                "INVALID_ARGUMENT",
                f"Unknown combine op: {op!r}",
                f"op：{', '.join(COMBINE_OPS)}",
                requested=op,
            )
        doc = self._require_doc()
        mats = [x for x in doc.features if x.get("sign", 0) > 0]
        if len(mats) < 2:
            raise fail("FEATURE_CREATE_FAILED", "Combine needs at least two bodies", "Two non-intersecting extrudes yield multiple bodies")
        if keep < 0 or keep >= len(mats):
            raise fail(
                "INVALID_ARGUMENT",
                f"Body index to keep out of range: {keep}",
                f"Valid range 0..{len(mats) - 1}",
            )
        vols = [float(x.get("vol") or 0.0) for x in mats]
        boxes = [tuple(x["bbox3d"]) for x in mats]

        def _ov(a: tuple, b: tuple) -> float:
            dx = max(0.0, min(a[3], b[3]) - max(a[0], b[0]))
            dy = max(0.0, min(a[4], b[4]) - max(a[1], b[1]))
            dz = max(0.0, min(a[5], b[5]) - max(a[2], b[2]))
            return dx * dy * dz

        if op == "add":
            vol = sum(vols)
            for i in range(len(mats)):
                for j in range(i + 1, len(mats)):
                    vol -= _ov(boxes[i], boxes[j])
        elif op == "cut":
            vol = vols[keep]
            for i in range(len(vols)):
                if i != keep:
                    vol -= _ov(boxes[keep], boxes[i])
            if vol <= 1e-16:
                raise fail("FEATURE_CREATE_FAILED", "No body left after combine cut", "Bodies must intersect; keep is the retained body index")
        else:
            vol = None
            for i, b in enumerate(boxes):
                if i == keep:
                    continue
                o = _ov(boxes[keep], b)
                vol = o if vol is None else min(vol, o)
            if not vol:
                raise fail("FEATURE_CREATE_FAILED", "Bodies do not intersect; cannot intersect", "Both extrude segments must overlap")
        n = sum(1 for x in doc.features if x["kind"] == "combine") + 1
        xs0 = min(b[0] for b in boxes)
        ys0 = min(b[1] for b in boxes)
        zs0 = min(b[2] for b in boxes)
        xs1 = max(b[3] for b in boxes)
        ys1 = max(b[4] for b in boxes)
        zs1 = max(b[5] for b in boxes)
        old_faces = sum(int(x.get("faces") or 0) for x in mats)
        old_edges = sum(int(x.get("edges") or 0) for x in mats)
        old_surf = sum(float(x.get("surf") or 0.0) for x in mats)
        for x in mats:
            x["sign"] = 0
            x["faces"] = 0
            x["edges"] = 0
            x["vol"] = 0.0
            x["surf"] = 0.0
        feat = {
            "kind": "combine", "sign": 1, "name": f"Combine{n}",
            "vol": float(vol), "surf": old_surf * 0.85,
            "faces": old_faces + 2, "edges": old_edges + 4,
            "bbox3d": (xs0, ys0, zs0, xs1, ys1, zs1),
            "com": ((xs0 + xs1) / 2, (ys0 + ys1) / 2, (zs0 + zs1) / 2),
            "op": op,
        }
        doc.features.append(feat)
        doc.modified = True
        return FeatureInfo(name=feat["name"], kind="combine")

    def split_body(self, plane: str) -> FeatureInfo:
        self._enter("split_body", plane=plane)
        doc = self._require_part("Use a part document to split a body")
        mats = [x for x in doc.features if x.get("sign", 0) > 0]
        if not mats:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "No body to split",
                "extrude or loft a solid, then split_body",
            )
        origin, _u, _v, n = self._plane_frame(plane)
        boxes = [tuple(x["bbox3d"]) for x in mats if x.get("bbox3d")]
        if not boxes:
            raise fail("FEATURE_CREATE_FAILED", "Body has no bounding box; cannot split", "Create a volumetric extrude first")
        xs0, ys0, zs0 = min(b[0] for b in boxes), min(b[1] for b in boxes), min(b[2] for b in boxes)
        xs1, ys1, zs1 = max(b[3] for b in boxes), max(b[4] for b in boxes), max(b[5] for b in boxes)
        corners = [
            (x, y, z)
            for x in (xs0, xs1)
            for y in (ys0, ys1)
            for z in (zs0, zs1)
        ]
        signed = [_vdot((c[0] - origin[0], c[1] - origin[1], c[2] - origin[2]), n) for c in corners]
        if min(signed) >= -1e-9 or max(signed) <= 1e-9:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "Reference plane does not cut the body",
                "Use a plane through the body interior, e.g. Right Plane on a centered cube",
                requested=plane,
            )
        total = sum(float(x.get("vol") or 0.0) for x in mats)
        half = 0.5 * total
        old_faces = sum(int(x.get("faces") or 0) for x in mats)
        old_edges = sum(int(x.get("edges") or 0) for x in mats)
        old_surf = sum(float(x.get("surf") or 0.0) for x in mats)
        for x in mats:
            x["sign"] = 0
            x["faces"] = 0
            x["edges"] = 0
            x["vol"] = 0.0
            x["surf"] = 0.0
        nx, ny, nz = n

        def _clip(side: int) -> tuple[float, float, float, float, float, float]:
            lo = [xs0, ys0, zs0]
            hi = [xs1, ys1, zs1]
            for i, ni in enumerate((nx, ny, nz)):
                if abs(ni) < 0.5:
                    continue
                cut = origin[i]
                if ni * side > 0:
                    lo[i] = max(lo[i], cut)
                else:
                    hi[i] = min(hi[i], cut)
            return (lo[0], lo[1], lo[2], hi[0], hi[1], hi[2])

        cut = 0.0
        if abs(nx) >= 0.5:
            cut = abs(ys1 - ys0) * abs(zs1 - zs0)
        elif abs(ny) >= 0.5:
            cut = abs(xs1 - xs0) * abs(zs1 - zs0)
        else:
            cut = abs(xs1 - xs0) * abs(ys1 - ys0)
        nstock = sum(1 for x in doc.features if x["kind"] == "stock")
        for i, side in enumerate((-1, 1), start=1):
            bb = _clip(side)
            doc.features.append({
                "kind": "stock", "sign": 1, "name": f"Stock{nstock + i}",
                "vol": half, "surf": old_surf / 2.0 + cut,
                "faces": max(1, old_faces // 2 + 3), "edges": max(1, old_edges // 2 + 6),
                "bbox3d": bb,
                "com": ((bb[0] + bb[3]) / 2, (bb[1] + bb[4]) / 2, (bb[2] + bb[5]) / 2),
            })
        nd = sum(1 for x in doc.features if x["kind"] == "delete_body") + 1
        feat = {
            "kind": "split_body", "sign": 0, "name": f"DeleteBody{nd}",
            "vol": 0.0, "surf": 0.0, "faces": 0, "edges": 0,
            "plane": plane,
        }
        doc.features.append(feat)
        doc.modified = True
        return FeatureInfo(name=feat["name"], kind="split_body")

    def parting_line(
        self,
        pull_face: int,
        edges: Sequence[int] | None = None,
        *,
        flip: bool = False,
    ) -> FeatureInfo:
        self._enter("parting_line", pull_face=pull_face, edges=edges, flip=flip)
        doc = self._require_part("Use a part document for mold parting line")
        mats = [x for x in doc.features if x.get("sign", 0) > 0]
        if not mats:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "No body for parting",
                "Extrude a base body first, then parting_line",
            )
        faces = self.list_faces()
        if not faces:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "Solid has no usable faces",
                "Create a solid, then get pull_face from get_faces",
            )
        idx = int(pull_face)
        if idx < 0 or idx >= len(faces):
            raise fail(
                "INVALID_ARGUMENT",
                f"Face index out of range: {idx}",
                f"Use get_faces；Valid range 0..{len(faces) - 1}",
                index=idx,
            )
        edge_pool = self.list_edges()
        if not edge_pool:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "Solid has no usable edges",
                "Create a solid with edges first, then get index from get_edges",
            )
        if edges is None:
            edge_idxs = [e.index for e in edge_pool]
        else:
            if not edges:
                raise fail(
                    "INVALID_ARGUMENT",
                    "edges list cannot be empty",
                    "Omit edges for all edges, or pass get_edges indexes",
                )
            edge_idxs = []
            for raw in edges:
                ei = int(raw)
                if ei < 0 or ei >= len(edge_pool):
                    raise fail(
                        "INVALID_ARGUMENT",
                        f"Edge index out of range: {ei}",
                        f"Use get_edges；Valid range 0..{len(edge_pool) - 1}",
                        index=ei,
                    )
                edge_idxs.append(ei)
        n = sum(1 for x in doc.features if x["kind"] == "parting_line") + 1
        feat = {
            "kind": "parting_line",
            "sign": 0,
            "name": f"PartingLine{n}",
            "vol": 0.0,
            "surf": 0.0,
            "faces": 0,
            "edges": 0,
            "pull_face": idx,
            "edge_indexes": edge_idxs,
            "flip": bool(flip),
        }
        doc.features.append(feat)
        doc.modified = True
        return FeatureInfo(name=feat["name"], kind="parting_line")

    def parting_surface(
        self,
        parting_line: str | None = None,
        *,
        radiate: bool = False,
        offset_m: float = 0.0,
        knit: bool = False,
    ) -> FeatureInfo:
        self._enter(
            "parting_surface",
            parting_line=parting_line,
            radiate=radiate,
            offset=offset_m,
            knit=knit,
        )
        doc = self._require_part("Use a part document for mold parting surface")
        if radiate and offset_m < 0:
            raise fail(
                "INVALID_ARGUMENT",
                f"Radiate offset cannot be negative (meters internally): {offset_m}",
                "Pass offset >= 0, or radiate=false",
            )
        lines = [x for x in doc.features if x.get("kind") == "parting_line"]
        if parting_line is not None:
            src = next((x for x in lines if x["name"] == str(parting_line)), None)
            if src is None:
                raise fail(
                    "FEATURE_NOT_FOUND",
                    f"Parting line not found: {parting_line!r}",
                    "Call parting_line first, or verify name with list_features",
                    requested=parting_line,
                )
        else:
            src = lines[-1] if lines else None
        if src is None:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "No usable parting line",
                "Call parting_line, then parting_surface",
            )
        n = sum(1 for x in doc.features if x["kind"] == "parting_surface") + 1
        feat = {
            "kind": "parting_surface",
            "sign": 0,
            "name": f"PartingSurface{n}",
            "vol": 0.0,
            "surf": 0.0,
            "faces": 0,
            "edges": 0,
            "parting_line": src["name"],
            "radiate": bool(radiate),
            "offset": float(offset_m),
            "knit": bool(knit),
        }
        doc.features.append(feat)
        doc.modified = True
        return FeatureInfo(name=feat["name"], kind="parting_surface")

    def shut_off_surface(self, edges: Sequence[int] | None = None) -> FeatureInfo:
        self._enter("shut_off_surface", edges=edges)
        doc = self._require_part("Use a part document for mold shut-off surface")
        lines = [x for x in doc.features if x.get("kind") == "parting_line"]
        if not lines:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "No usable parting line",
                "Call parting_line, then shut_off_surface",
            )
        edge_pool = self.list_edges()
        if not edge_pool:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "Solid has no usable edges",
                "Create a solid with edges first, then get index from get_edges",
            )
        if edges is None:
            edge_idxs = [e.index for e in edge_pool]
        else:
            if not edges:
                raise fail(
                    "INVALID_ARGUMENT",
                    "edges list cannot be empty",
                    "Omit edges for all edges, or pass get_edges indexes",
                )
            edge_idxs = []
            for raw in edges:
                ei = int(raw)
                if ei < 0 or ei >= len(edge_pool):
                    raise fail(
                        "INVALID_ARGUMENT",
                        f"Edge index out of range: {ei}",
                        f"Use get_edges；Valid range 0..{len(edge_pool) - 1}",
                        index=ei,
                    )
                edge_idxs.append(ei)
        n = sum(1 for x in doc.features if x["kind"] == "shut_off_surface") + 1
        feat = {
            "kind": "shut_off_surface",
            "sign": 0,
            "name": f"ShutOff{n}",
            "vol": 0.0,
            "surf": 0.0,
            "faces": 0,
            "edges": 0,
            "edge_indexes": edge_idxs,
            "parting_line": lines[-1]["name"],
        }
        doc.features.append(feat)
        doc.modified = True
        return FeatureInfo(name=feat["name"], kind="shut_off_surface")

    # ---------- Hole wizard ----------

    def hole_wizard(
        self,
        face: int,
        diameter_m: float,
        end: str = "blind",
        depth_m: float | None = None,
        x_m: float | None = None,
        y_m: float | None = None,
    ) -> FeatureInfo:
        self._enter(
            "hole_wizard", face=face, diameter=diameter_m, end=end, depth=depth_m, x=x_m, y=y_m,
        )
        if end not in HOLE_WIZARD_ENDS:
            raise fail(
                "INVALID_ARGUMENT",
                f"Unknown hole end condition: {end!r}",
                f"end：{', '.join(HOLE_WIZARD_ENDS)}",
                requested=end,
            )
        if diameter_m <= 0:
            raise fail("INVALID_ARGUMENT", "Hole diameter must be positive", "Pass diameter > 0")
        if end == "blind" and (depth_m is None or depth_m <= 0):
            raise fail("INVALID_ARGUMENT", "Blind holes need positive depth", "Pass depth > 0 when end=blind")
        doc = self._require_doc()
        mats = [x for x in doc.features if x.get("sign", 0) > 0]
        if not mats:
            raise fail("FEATURE_CREATE_FAILED", "Hole wizard requires an existing solid", "Extrude a base solid, then pick a face")
        pool = self.list_faces()
        if not pool:
            raise fail("FEATURE_CREATE_FAILED", "No faces available for hole", "Extrude a base body first")
        self._checked_indexes([int(face)], len(pool), "face", "get_faces")
        ref = pool[int(face)]
        r = float(diameter_m) / 2.0
        if end == "through_all":
            n = ref.normal_m or (0.0, 0.0, 1.0)
            ax = max(range(3), key=lambda i: abs(n[i]))
            box = mats[0]["bbox3d"]
            span = float(box[ax + 3] - box[ax])
            cut_len = max(span, 1e-12)
        else:
            cut_len = float(depth_m or 0.0)
        vol = math.pi * r * r * cut_len
        if end == "through_all":
            surf = 2.0 * math.pi * r * r - 2.0 * math.pi * r * cut_len
            n_edges = 2
        else:
            surf = math.pi * r * r - 2.0 * math.pi * r * cut_len
            n_edges = 1
        n = sum(1 for x in doc.features if x["kind"] == "hole_wizard") + 1
        feat = {
            "kind": "hole_wizard", "sign": -1, "name": f"Hole-Wizard{n}",
            "vol": vol, "surf": surf, "faces": 1, "edges": n_edges,
            "diameter": float(diameter_m), "end": end, "face": int(face),
        }
        doc.features.append(feat)
        doc.modified = True
        return FeatureInfo(name=feat["name"], kind="hole_wizard")
        