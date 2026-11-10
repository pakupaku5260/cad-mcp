"""Fake backend · feature domain · loft（S8e-6）。

S8e-6：loft / loft_cut / _loft / _loft_sketches / _ended_sketch /
       _guide_is_closed / _loft_guides / _sketch_bbox3d。

Dependencies (self, MRO):
- `_enter` / `_require_doc` / `_doc`（FakeBackend）
- `_require_part`（FakeQueryMixin，S8e-3）
- `_profile_of`（FakeExtrudeMixin，S8e-1）
- `_plane_frame` / `_uv_xyz`（FakePlaneAxisMixin，S8d-2）
- `_consume_sketch`（FakeSketchMixin，S8d）

Imports:
- `cadmcp.backend.protocol.models`（FeatureInfo）
- `cadmcp.backend.protocol.parsers`（is_3d_sketch_plane）
- `cadmcp.errors`（fail）
- `.._state`（_Sketch / _union_boxes / _vadd / _vmul）
"""
from __future__ import annotations

import math
from collections.abc import Sequence

from cadmcp.backend.protocol.models import FeatureInfo
from cadmcp.backend.protocol.parsers import is_3d_sketch_plane
from cadmcp.errors import fail

from .._state import _Sketch, _union_boxes, _vadd, _vmul


class FakeLoftMixin:
    """loft (S8e-6: 8 methods)."""

    def _init_state(self) -> None:
        pass  # State owned by FakeBackend._init_state

    # ---------- Entry ----------

    def loft(
        self,
        profiles: Sequence[str] | None = None,
        *,
        guides: Sequence[str] | None = None,
        centerline: str | None = None,
    ) -> FeatureInfo:
        return self._loft("loft", profiles, guides, centerline)

    def loft_cut(
        self,
        profiles: Sequence[str] | None = None,
        *,
        guides: Sequence[str] | None = None,
        centerline: str | None = None,
    ) -> FeatureInfo:
        return self._loft("loft_cut", profiles, guides, centerline)

    # ---------- Sketch resolve ----------

    def _loft_sketches(self, doc, profiles: Sequence[str] | None) -> list[_Sketch]:
        if doc.open_sketch is not None:
            raise fail(
                "SKETCH_OP_FAILED",
                f"Sketch {doc.open_sketch.name or ''} is still open; cannot create a feature",
                "Call end_sketch to close the sketch, then loft",
            )
        ended = list(doc.ended_sketches)
        if profiles:
            sketches: list[_Sketch] = []
            for raw in profiles:
                sk = self._ended_sketch(ended, str(raw))
                if sk is None:
                    raise fail(
                        "SKETCH_NOT_FOUND",
                        f"Loft profile sketch not found: {raw!r}",
                        "Use ended sketch names like Sketch1; or omit profiles for latest two",
                        requested=raw,
                    )
                sketches.append(sk)
        else:
            sketches = ended[-2:]
        if len(sketches) < 2:
            raise fail(
                "INVALID_ARGUMENT",
                "loft needs at least two profile sketches",
                "Closed profiles on two parallel planes, end_sketch each, then loft",
            )
        return sketches

    @staticmethod
    def _ended_sketch(ended: Sequence[_Sketch], name: str) -> _Sketch | None:
        wanted = {name}
        # Localized SW UI alias: \\u8349\\u56fe pairs with Sketch{N}
        _sk = "\u8349\u56fe"
        if name.startswith("Sketch") and name[6:].isdigit():
            wanted.add(f"{_sk}{name[6:]}")
        elif name.startswith(_sk) and name[2:].isdigit():
            wanted.add(f"Sketch{name[2:]}")
        return next((sk for sk in ended if sk.name in wanted), None)

    def _guide_is_closed(self, sk: _Sketch) -> bool:
        if any(e.get("kind") in ("circle", "rect", "polygon") for e in sk.entities):
            return True
        lines = [e for e in sk.entities if e.get("kind") == "line"]
        if lines and len(lines) == len(sk.entities) and len(lines) < 3:
            return False
        try:
            self._profile_of(sk)
        except Exception:
            return False
        return True

    def _loft_guides(
        self, doc, names: Sequence[str] | None, profiles: Sequence[_Sketch]
    ) -> list[_Sketch]:
        if not names:
            return []
        ended = list(doc.ended_sketches)
        prof = {id(sk) for sk in profiles}
        out: list[_Sketch] = []
        for raw in names:
            sk = self._ended_sketch(ended, str(raw))
            if sk is None:
                raise fail(
                    "SKETCH_NOT_FOUND",
                    f"Loft guide sketch not found: {raw!r}",
                    "Ended open-curve sketch name, e.g. lateral Sketch3",
                    requested=raw,
                )
            if id(sk) in prof:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    f"Guide {raw!r} cannot also be a profile",
                    "guides use separate open-curve sketches, not profile names",
                    requested=raw,
                )
            if not sk.entities:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    f"Guide sketch {raw!r} is empty",
                    "Draw a line or arc connecting sections on the guide sketch, then end_sketch",
                    requested=raw,
                )
            if self._guide_is_closed(sk):
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    f"Guide {raw!r} must be an open curve",
                    "sketch_line for lateral guide; no closed circle/rectangle as guide",
                    requested=raw,
                )
            out.append(sk)
        return out

    def _loft_centerline(self, doc, name: str | None, profiles: Sequence[_Sketch]) -> _Sketch | None:
        if not name:
            return None
        ended = list(doc.ended_sketches)
        sk = self._ended_sketch(ended, str(name))
        if sk is None:
            raise fail(
                "SKETCH_NOT_FOUND",
                f"Loft centerline sketch not found: {name!r}",
                "Ended open-curve sketch name, e.g. 3D arc Sketch3",
                requested=name,
            )
        if id(sk) in {id(p) for p in profiles}:
            raise fail(
                "FEATURE_CREATE_FAILED",
                f"Centerline {name!r} cannot also be a profile",
                "centerline uses separate open-curve sketch",
                requested=name,
            )
        if not sk.entities:
            raise fail(
                "FEATURE_CREATE_FAILED",
                f"Centerline sketch {name!r} is empty",
                "Draw line/arc/spline through sections on centerline sketch, then end_sketch",
                requested=name,
            )
        if self._guide_is_closed(sk):
            raise fail(
                "FEATURE_CREATE_FAILED",
                f"Centerline {name!r} must be an open curve",
                "Use 3D line, arc, or spline; not closed circle/rectangle",
                requested=name,
            )
        return sk

    # ---------- Loft body ----------

    def _loft(
        self,
        kind: str,
        profiles: Sequence[str] | None,
        guides: Sequence[str] | None = None,
        centerline: str | None = None,
    ) -> FeatureInfo:
        self._enter(kind, profiles=profiles, guides=guides, centerline=centerline)
        doc = self._require_part("Use a part document for loft")
        if guides and centerline:
            raise fail(
                "INVALID_ARGUMENT",
                "loft cannot use both guides and centerline",
                "guides or centerline, not both",
            )
        sketches = self._loft_sketches(doc, profiles)
        guide_sk = self._loft_guides(doc, guides, sketches)
        center_sk = self._loft_centerline(doc, centerline, sketches)
        if kind == "loft_cut" and not any(x.get("sign", 0) > 0 for x in doc.features):
            raise fail(
                "FEATURE_CREATE_FAILED",
                "No material to cut (no solid features yet)",
                "extrude base solid first, then loft_cut",
            )
        p0 = self._profile_of(sketches[0])
        p1 = self._profile_of(sketches[-1])
        o0, u0, v0, n0 = self._plane_frame(str(sketches[0].plane or "Front Plane"))
        o1, _u1, _v1, _n1 = self._plane_frame(str(sketches[-1].plane or "Front Plane"))
        delta = (o1[0] - o0[0], o1[1] - o0[1], o1[2] - o0[2])
        signed = delta[0] * n0[0] + delta[1] * n0[1] + delta[2] * n0[2]
        h = abs(signed)
        if h < 1e-12:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "Loft profiles coplanar; cannot build solid",
                "Sketch the second profile on an offset plane (create_plane)",
            )
        r0 = math.sqrt(p0["area"] / math.pi)
        r1 = math.sqrt(p1["area"] / math.pi)
        vol = math.pi * h / 3.0 * (r0 * r0 + r0 * r1 + r1 * r1)
        slant = math.hypot(h, r0 - r1)
        surf = math.pi * (r0 + r1) * slant + math.pi * (r0 * r0 + r1 * r1)
        circles = p0.get("profile") == "circle" and p1.get("profile") == "circle"
        t = h * (r0 * r0 + 2.0 * r0 * r1 + 3.0 * r1 * r1) / (4.0 * (r0 * r0 + r0 * r1 + r1 * r1))
        if signed < 0:
            t = -t
        uc = (p0["bbox2d"][0] + p0["bbox2d"][2]) / 2.0
        vc = (p0["bbox2d"][1] + p0["bbox2d"][3]) / 2.0
        com = _vadd(o0, _vmul(u0, uc), _vmul(v0, vc), _vmul(n0, t))
        boxes = [b for sk in (sketches[0], sketches[-1]) if (b := self._sketch_bbox3d(sk)) is not None]
        bbox = _union_boxes(boxes)
        # Real loft GetPartBox expands ~0.0001 mm beyond sketch union
        pad = 1e-7
        bbox = (bbox[0] - pad, bbox[1] - pad, bbox[2] - pad, bbox[3] + pad, bbox[4] + pad, bbox[5] + pad)
        n = sum(1 for x in doc.features if x["kind"] == kind) + 1
        if kind == "loft":
            name, sign, faces, edges = f"Loft{n}", 1, (3 if circles else 6), (2 if circles else 12)
            feat_surf = surf
        else:
            name, sign = f"Cut-Loft{n}", -1
            faces, edges = 1, 2
            feat_surf = math.pi * (r0 + r1) * slant - math.pi * (r0 * r0 + r1 * r1)
        f = {
            "kind": kind, "sign": sign, "name": name,
            "vol": vol, "surf": feat_surf, "com": com, "bbox3d": bbox,
            "faces": faces, "edges": edges,
            "guides": [sk.name for sk in guide_sk],
            "centerline": None if center_sk is None else center_sk.name,
        }
        doc.features.append(f)
        for sk in sketches:
            self._consume_sketch(doc, sk)
        doc.modified = True
        return FeatureInfo(name=name, kind=kind)

    # ---------- Sketch 3D bbox (query._geom) ----------

    def _sketch_bbox3d(self, sk: _Sketch) -> tuple[float, ...] | None:
        """3D bbox of sketch entities (canned: map local u/v to world via reference plane).

        Real GetPartBox counts sketch entities in part box; fake uses same rule,
        avoid fake bbox change in fingerprint when sketch is absorbed by feature.
        """
        if not sk.entities:
            return None
        if is_3d_sketch_plane(sk.plane):
            xs: list[float] = []
            ys: list[float] = []
            zs: list[float] = []
            for e in sk.entities:
                if e.get("kind") == "line":
                    xs.extend((float(e["x0"]), float(e["x1"])))
                    ys.extend((float(e["y0"]), float(e["y1"])))
                    zs.extend((float(e.get("z0", 0.0)), float(e.get("z1", 0.0))))
            if not xs:
                return None
            return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))
        us: list[float] = []
        vs: list[float] = []
        for e in sk.entities:
            if e["kind"] == "circle":
                us.extend((e["cx"] - e["r"], e["cx"] + e["r"]))
                vs.extend((e["cy"] - e["r"], e["cy"] + e["r"]))
            elif e["kind"] == "arc":
                us.extend((e["x0"], e["x1"]))
                vs.extend((e["y0"], e["y1"]))
                for t in (0.25, 0.5, 0.75):
                    ang = math.atan2(e["y0"] - e["cy"], e["x0"] - e["cx"]) + t * e["sweep"]
                    us.append(e["cx"] + e["r"] * math.cos(ang))
                    vs.append(e["cy"] + e["r"] * math.sin(ang))
            elif e["kind"] == "polygon":
                us.extend((-e["r"], e["r"]))
                vs.extend((-e["r"], e["r"]))
            elif e["kind"] == "spline":
                for p in e.get("points") or ():
                    us.append(float(p[0]))
                    vs.append(float(p[1]))
            else:  # line / rect
                us.extend((e["x0"], e["x1"]))
                vs.extend((e["y0"], e["y1"]))
        corners = [self._uv_xyz(sk.plane, u, v) for u in (min(us), max(us)) for v in (min(vs), max(vs))]
        xs, ys, zs = zip(*corners, strict=True)
        return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))
        