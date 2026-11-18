"""Fake backend · feature domain · helix/sweep/cosmetic thread（S8e-7）。

S8e-7：create_helix / sweep / sweep_cut / _sweep / _sweep_pair /
       _sweep_profile / _triangle_profile / _path_segments /
       _segment_length / _chain_path_length / _sweep_path / insert_cosmetic_thread。

Dependencies (self, MRO):
- `_enter` / `_require_doc` / `_doc` / `_consume_sketch`（FakeSketchMixin）
- `_pending_sketch`（FakeSketchMixin，S8d）
- `_ended_sketch` / `_sketch_bbox3d`（FakeLoftMixin，S8e-6）
- `begin_sketch` / `draw_circle` / `end_sketch` / `sketch_line`（FakeSketchMixin）
- `list_edges`（FakeQueryMixin）

Imports:
- `cadmcp.backend.protocol.constants`（THREAD_PROP_*）
- `cadmcp.backend.protocol.models`（FeatureInfo / HelixInfo）
- `cadmcp.errors`（fail）
- `.._state`（_CHAIN_TOL / _Sketch）
"""
from __future__ import annotations

import math

from cadmcp.backend.protocol.constants import (
    THREAD_METHODS,
    THREAD_PROFILE_EXTERNAL,
    THREAD_PROFILE_INTERNAL,
    THREAD_PROP_SIDE,
    THREAD_PROP_SIZE,
    THREAD_PROP_SPEC,
)
from cadmcp.backend.protocol.models import FeatureInfo, HelixInfo
from cadmcp.errors import fail

from .._state import _CHAIN_TOL, _Sketch


class FakeHelixMixin:
    """helix/sweep/thread (S8e-7: 12 methods)."""

    def _init_state(self) -> None:
        pass  # State owned by FakeBackend._init_state

    # ---------- Helix ----------

    def create_helix(
        self,
        pitch_m: float,
        revolutions: float = 1.0,
        height_m: float | None = None,
        start_angle_rad: float = 0.0,
        clockwise: bool = False,
    ) -> HelixInfo:
        self._enter(
            "create_helix",
            pitch=pitch_m,
            revolutions=revolutions,
            height=height_m,
            start_angle=start_angle_rad,
            clockwise=clockwise,
        )
        self._require_doc()
        if pitch_m <= 0:
            raise fail("INVALID_ARGUMENT", "Pitch must be positive", "Pass pitch > 0")
        if height_m is None:
            if revolutions <= 0:
                raise fail("INVALID_ARGUMENT", "Revolution count must be positive", "Pass revolutions > 0, or pass height instead")
        elif height_m <= 0:
            raise fail("INVALID_ARGUMENT", "Helix height must be positive", "Pass height > 0")
        doc, pending = self._pending_sketch(None)
        circle = next((e for e in pending.entities if e.get("kind") == "circle"), None)
        if circle is None:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "Failed to create helix",
                "Ended sketch must have a circle; rectangles cannot form a helix",
            )
        n = sum(1 for x in doc.features if x.get("kind") == "helix") + 1
        name = f"Helix{n}"
        r = float(circle["r"])
        axis_h = float(height_m) if height_m is not None else float(pitch_m) * float(revolutions)
        z0, z1 = (0.0, axis_h) if axis_h >= 0 else (axis_h, 0.0)
        # No vol: no volume/faces/edges; bbox3d: real helix changes bbox (consistency delta)
        doc.features.append({
            "kind": "helix",
            "name": name,
            "sign": 0,
            "pitch": pitch_m,
            "revolutions": revolutions,
            "height": height_m,
            "start_angle": start_angle_rad,
            "clockwise": clockwise,
            "radius": r,
            "bbox3d": (circle["cx"] - r, circle["cy"] - r, z0, circle["cx"] + r, circle["cy"] + r, z1),
        })
        self._consume_sketch(doc, pending)
        doc.modified = True
        return HelixInfo(name=name)

    # ---------- Sweep ----------

    def sweep(self, profile_sketch: str | None = None, path_sketch: str | None = None) -> FeatureInfo:
        return self._sweep("sweep", profile_sketch, path_sketch)

    def sweep_cut(self, profile_sketch: str | None = None, path_sketch: str | None = None) -> FeatureInfo:
        return self._sweep("sweep_cut", profile_sketch, path_sketch)

    def _sweep_pair(
        self, doc, profile_sketch: str | None, path_sketch: str | None
    ) -> tuple[_Sketch, tuple[str, _Sketch | dict]]:
        """Resolve profile/path: explicit names first; else profile=latest ended sketch, path=previous (or helix)."""
        if doc.open_sketch is not None:
            raise fail(
                "SKETCH_OP_FAILED",
                f"Sketch {doc.open_sketch.name or ''} is still open; cannot create a feature",
                "Call end_sketch to close the sketch, then run the feature",
            )
        ended = list(doc.ended_sketches)
        helixes = [f for f in doc.features if f.get("kind") == "helix"]

        def _sketch(name: str | None) -> _Sketch | None:
            if not name:
                return None
            return self._ended_sketch(ended, name)

        profile = _sketch(profile_sketch) if profile_sketch is not None else (ended[-1] if ended else None)
        if profile is None:
            raise fail(
                "SKETCH_NOT_FOUND",
                f"Profile sketch not found: {profile_sketch!r}",
                "start_sketch → draw closed profile → end_sketch; or omit name for latest ended sketch",
                requested=profile_sketch,
            )

        path: tuple[str, _Sketch | dict] | None = None
        if path_sketch is not None:
            sk = _sketch(path_sketch)
            if sk is not None:
                path = ("sketch", sk)
            else:
                helix = next((f for f in helixes if f["name"] == path_sketch), None)
                if helix is not None:
                    path = ("helix", helix)
        else:
            others = [sk for sk in ended if sk is not profile]
            if others:
                path = ("sketch", others[-1])
            elif helixes:
                path = ("helix", helixes[-1])
        if path is None:
            raise fail(
                "SKETCH_NOT_FOUND",
                f"Path sketch not found: {path_sketch!r} (available: {', '.join(sk.name or '?' for sk in ended) or 'none'})",
                "Sweep needs two sketches: path then profile, each end_sketch; or pass path_sketch explicitly",
                requested=path_sketch,
            )
        if path[0] == "sketch" and path[1] is profile:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "Profile sketch cannot also be the path",
                "Create separate path and profile sketches, then sweep",
            )
        return profile, path

    @staticmethod
    def _sweep_profile(sk: _Sketch) -> dict:
        if not sk.entities:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "Profile sketch is empty",
                "sketch_circle or sketch_rectangle for closed profile, then end_sketch",
            )
        tri = FakeHelixMixin._triangle_profile(sk)
        if tri is not None:
            return tri
        if len(sk.entities) != 1:
            raise fail(
                "FEATURE_CREATE_FAILED",
                f"Unsupported sweep profile: sketch has {len(sk.entities)} entities",
                "Sweep profile must be closed circle, rectangle, or triangle (three lines)",
            )
        e = sk.entities[0]
        if e["kind"] == "circle":
            r = float(e["r"])
            return {
                "area": math.pi * r * r, "perimeter": 2 * math.pi * r,
                "rx": r, "ry": r, "faces": 3, "edges": 2,
            }
        if e["kind"] == "rect":
            w, h = abs(e["x1"] - e["x0"]), abs(e["y1"] - e["y0"])
            return {
                "area": w * h, "perimeter": 2 * (w + h),
                "rx": w / 2, "ry": h / 2, "faces": 6, "edges": 12,
            }
        raise fail(
            "FEATURE_CREATE_FAILED",
            f"Unsupported sweep profile: {e['kind']}",
            "Sweep profile must be closed circle, rectangle, or triangle (three lines)",
        )

    @staticmethod
    def _triangle_profile(sk: _Sketch) -> dict | None:
        lines = [e for e in sk.entities if e.get("kind") == "line"]
        if len(sk.entities) != 3 or len(lines) != 3:
            return None
        pts = [(lines[0]["x0"], lines[0]["y0"]), (lines[0]["x1"], lines[0]["y1"])]
        rest = lines[1:]
        while rest:
            x, y = pts[-1]
            hit = None
            for i, ln in enumerate(rest):
                a, b = (ln["x0"], ln["y0"]), (ln["x1"], ln["y1"])
                if math.hypot(a[0] - x, a[1] - y) < 1e-12:
                    pts.append(b)
                    hit = i
                    break
                if math.hypot(b[0] - x, b[1] - y) < 1e-12:
                    pts.append(a)
                    hit = i
                    break
            if hit is None:
                return None
            rest.pop(hit)
        if len(pts) != 4 or math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) > 1e-9:
            return None
        xs, ys = [p[0] for p in pts[:-1]], [p[1] for p in pts[:-1]]
        area = abs(sum(xs[i] * ys[(i + 1) % 3] - xs[(i + 1) % 3] * ys[i] for i in range(3))) / 2.0
        if area <= 0.0:
            return None
        peri = sum(math.hypot(pts[i][0] - pts[i + 1][0], pts[i][1] - pts[i + 1][1]) for i in range(3))
        rx = (max(xs) - min(xs)) / 2.0
        ry = (max(ys) - min(ys)) / 2.0
        return {"area": area, "perimeter": peri, "rx": rx, "ry": ry, "faces": 3, "edges": 3}

    @staticmethod
    def _path_segments(sk: _Sketch) -> list[dict] | None:
        """Path entities: lines, arcs; rectangle expands to four edges. Closed circles return None."""
        segs: list[dict] = []
        for e in sk.entities:
            kind = e.get("kind")
            if kind in {"line", "arc"}:
                segs.append(e)
            elif kind == "rect":
                x0, y0, x1, y1 = float(e["x0"]), float(e["y0"]), float(e["x1"]), float(e["y1"])
                segs.extend(
                    [
                        {"kind": "line", "x0": x0, "y0": y0, "x1": x1, "y1": y0},
                        {"kind": "line", "x0": x1, "y0": y0, "x1": x1, "y1": y1},
                        {"kind": "line", "x0": x1, "y0": y1, "x1": x0, "y1": y1},
                        {"kind": "line", "x0": x0, "y0": y1, "x1": x0, "y1": y0},
                    ]
                )
            else:
                return None
        return segs

    @staticmethod
    def _segment_length(e: dict) -> float:
        if e.get("kind") == "arc":
            return abs(float(e["r"]) * float(e["sweep"]))
        return math.hypot(
            float(e["x1"]) - float(e["x0"]),
            float(e["y1"]) - float(e["y0"]),
            float(e.get("z1", 0.0)) - float(e.get("z0", 0.0)),
        )

    @staticmethod
    def _chain_path_length(segs: list[dict]) -> float | None:
        """Length of open/closed chain with head/tail connected; None if forked or broken."""
        if not segs:
            return None
        unused = list(segs)

        def _ends(e: dict) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
            return (
                (float(e["x0"]), float(e["y0"]), float(e.get("z0", 0.0))),
                (float(e["x1"]), float(e["y1"]), float(e.get("z1", 0.0))),
            )

        def _near(
            a: tuple[float, float, float], b: tuple[float, float, float]
        ) -> bool:
            return math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]) <= _CHAIN_TOL

        first = unused.pop(0)
        a0, b0 = _ends(first)
        length = FakeHelixMixin._segment_length(first)

        def _grow(curr: tuple[float, float, float]) -> float | None:
            extra = 0.0
            while unused:
                hits: list[tuple[int, tuple[float, float, float]]] = []
                for i, e in enumerate(unused):
                    a, b = _ends(e)
                    if _near(a, curr):
                        hits.append((i, b))
                    elif _near(b, curr):
                        hits.append((i, a))
                if not hits:
                    return extra
                if len(hits) != 1:
                    return None
                i, nxt = hits[0]
                extra += FakeHelixMixin._segment_length(unused.pop(i))
                curr = nxt
            return extra

        right = _grow(b0)
        if right is None:
            return None
        length += right
        left = _grow(a0)
        if left is None or unused:
            return None
        length += left
        if length <= 0.0:
            return None
        return length

    @staticmethod
    def _sweep_path(path: tuple[str, _Sketch | dict]) -> tuple[float, tuple[float, ...], tuple[float, float, float]]:
        kind, obj = path
        if kind == "helix":
            h = obj
            r = float(h.get("radius", 0.0))
            pitch = float(h["pitch"])
            height = h.get("height")
            revs = float(height) / pitch if height is not None else float(h["revolutions"])
            length = revs * math.hypot(math.tau * r, pitch)
            b = h["bbox3d"]
            com = ((b[0] + b[3]) / 2, (b[1] + b[4]) / 2, (b[2] + b[5]) / 2)
            return length, b, com
        sk = obj
        segs = FakeHelixMixin._path_segments(sk)
        length = FakeHelixMixin._chain_path_length(segs) if segs is not None else None
        if length is None:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "Unsupported path sketch: need connected line/arc chain",
                "On one ended sketch draw connected lines/arcs (may close); no full circles or broken chains",
            )
        xs: list[float] = []
        ys: list[float] = []
        zs: list[float] = []
        for e in segs:
            xs.extend((float(e["x0"]), float(e["x1"])))
            ys.extend((float(e["y0"]), float(e["y1"])))
            zs.extend((float(e.get("z0", 0.0)), float(e.get("z1", 0.0))))
            if e.get("kind") == "arc":
                for t in (0.25, 0.5, 0.75):
                    ang = math.atan2(e["y0"] - e["cy"], e["x0"] - e["cx"]) + t * e["sweep"]
                    xs.append(e["cx"] + e["r"] * math.cos(ang))
                    ys.append(e["cy"] + e["r"] * math.sin(ang))
                    zs.append(float(e.get("z0", 0.0)))
        bbox = (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))
        com = ((bbox[0] + bbox[3]) / 2, (bbox[1] + bbox[4]) / 2, (bbox[2] + bbox[5]) / 2)
        return length, bbox, com

    def _sweep(
        self, kind: str, profile_sketch: str | None, path_sketch: str | None
    ) -> FeatureInfo:
        self._enter(kind, profile_sketch=profile_sketch, path_sketch=path_sketch)
        doc = self._require_doc()
        profile, path = self._sweep_pair(doc, profile_sketch, path_sketch)
        if kind == "sweep_cut" and not any(x["sign"] > 0 for x in doc.features):
            raise fail(
                "FEATURE_CREATE_FAILED",
                "No material to cut (no solid features yet)",
                "Create base solid with extrude or revolve before sweep cut",
            )
        p = self._sweep_profile(profile)
        length, pb, pc = self._sweep_path(path)
        # Line/polyline path: sweep bbox = path sketch ∪ profile sketch (real GetPartBox is that union before sweep).
        # Helix path: tube around cylinder; envelope = helix bbox expanded in XY by profile radius
        # (Real sweep_helix: post-sweep bbox larger than helix+profile sketch union).
        if path[0] == "helix":
            rmax = max(float(p["rx"]), float(p["ry"]))
            bbox3d = (pb[0] - rmax, pb[1] - rmax, pb[2], pb[3] + rmax, pb[4] + rmax, pb[5])
        else:
            path_bbox = self._sketch_bbox3d(path[1])  # type: ignore[arg-type]
            parts = [b for b in (self._sketch_bbox3d(profile), path_bbox) if b is not None]
            bbox3d = (
                min(b[0] for b in parts), min(b[1] for b in parts), min(b[2] for b in parts),
                max(b[3] for b in parts), max(b[4] for b in parts), max(b[5] for b in parts),
            )
            # Polyline/arc: real tube expands by profile radius at corners; GetPartBox larger than sketch union.
            # 3D line path: tube normal to path, bbox larger than sketch union.
            segs = self._path_segments(path[1])  # type: ignore[arg-type]
            rmax = max(float(p["rx"]), float(p["ry"]))
            is_3d_path = bool(
                segs
                and any(
                    float(e.get("z0", 0.0)) != 0.0 or float(e.get("z1", 0.0)) != 0.0
                    for e in segs
                )
            )
            if segs is not None and is_3d_path:
                bbox3d = (
                    bbox3d[0] - rmax, bbox3d[1] - rmax, bbox3d[2] - rmax,
                    bbox3d[3] + rmax, bbox3d[4] + rmax, bbox3d[5] + rmax,
                )
            elif segs is not None and len(segs) > 1:
                bbox3d = (
                    bbox3d[0], bbox3d[1] - rmax, bbox3d[2] - rmax,
                    bbox3d[3] + rmax, bbox3d[4] + rmax, bbox3d[5] + rmax,
                )
        sign = 1 if kind == "sweep" else -1
        surf = p["perimeter"] * length + (2 * p["area"] if sign > 0 else 0.0)
        n = sum(1 for x in doc.features if x["kind"] == kind) + 1
        prefix = "Sweep" if kind == "sweep" else "Cut-Sweep"
        f = {
            "kind": kind, "sign": sign, "name": f"{prefix}{n}",
            "vol": p["area"] * length, "surf": surf,
            "com": pc, "bbox3d": bbox3d,
            "faces": p["faces"] if sign > 0 else 2,
            "edges": p["edges"] if sign > 0 else 4,
        }
        doc.features.append(f)
        self._consume_sketch(doc, profile)
        if path[0] == "sketch":
            self._consume_sketch(doc, path[1])  # type: ignore[arg-type]
        doc.pending_sketch = None
        doc.modified = True
        return FeatureInfo(name=f["name"], kind=kind)

    # ---------- Cosmetic thread (annotation; no cut) ----------

    def insert_cosmetic_thread(
        self,
        size: str,
        diameter_m: float,
        length_m: float | None = None,
        edge: int | None = None,
        internal: bool = False,
        spec: str | None = None,
    ) -> FeatureInfo:
        self._enter(
            "insert_cosmetic_thread",
            size=size,
            diameter=diameter_m,
            length=length_m,
            edge=edge,
            internal=internal,
            spec=spec,
        )
        doc = self._require_doc()
        if doc.open_sketch is not None:
            raise fail(
                "SKETCH_OP_FAILED",
                f"Sketch {doc.open_sketch.name or ''} is still open; cannot create a feature",
                "Call end_sketch to close the sketch, then insert_cosmetic_thread",
            )
        size_s = str(size).strip()
        if not size_s:
            raise fail("INVALID_ARGUMENT", "Thread size must be non-empty", "Pass size e.g. M10x1.5")
        if diameter_m <= 0:
            raise fail("INVALID_ARGUMENT", "Thread diameter must be positive", "Pass diameter > 0")
        depth = float(length_m) if length_m is not None else 1.5 * float(diameter_m)
        if depth <= 0:
            raise fail("INVALID_ARGUMENT", "Thread length must be positive", "Pass length > 0")
        if not any(x.get("sign", 0) > 0 for x in doc.features):
            raise fail(
                "FEATURE_CREATE_FAILED",
                "No solid for cosmetic thread",
                "Extrude a cylinder (external) or tube (internal), then insert_cosmetic_thread",
            )
        edges = self.list_edges()
        if not edges:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "No edge to attach cosmetic thread",
                "Pass edge from get_edges (prefer a circular rim)",
            )
        if edge is not None:
            ei = int(edge)
            if ei < 0 or ei >= len(edges):
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Edge index out of range: {ei}",
                    f"Valid range 0..{len(edges) - 1}",
                    index=ei,
                )
        side = "internal" if internal else "external"
        spec_s = str(spec).strip() if spec else size_s
        n = sum(1 for x in doc.features if x.get("kind") == "cosmetic_thread") + 1
        name = f"CosmeticThread{n}"
        # Annotation only: no volume/face change; store THREAD_* on the feature record.
        props = {
            THREAD_PROP_SPEC: spec_s,
            THREAD_PROP_SIDE: side,
            THREAD_PROP_SIZE: size_s,
        }
        doc.features.append({
            "kind": "cosmetic_thread",
            "name": name,
            "sign": 0,
            "size": size_s,
            "diameter": float(diameter_m),
            "length": float(depth),
            "internal": bool(internal),
            "edge": None if edge is None else int(edge),
            "props": props,
        })
        doc.custom_props.update(props)
        doc.modified = True
        return FeatureInfo(name=name, kind="cosmetic_thread")

    def create_thread(
        self,
        size: str,
        depth_m: float,
        edge: int | None = None,
        method: str = "cut",
        internal: bool = False,
        thread_type: str | None = None,
        right_handed: bool = True,
        diameter_m: float | None = None,
        pitch_m: float | None = None,
    ) -> FeatureInfo:
        self._enter(
            "create_thread",
            size=size,
            depth=depth_m,
            edge=edge,
            method=method,
            internal=internal,
            thread_type=thread_type,
            right_handed=right_handed,
            diameter=diameter_m,
            pitch=pitch_m,
        )
        doc = self._require_doc()
        if doc.open_sketch is not None:
            raise fail(
                "SKETCH_OP_FAILED",
                f"Sketch {doc.open_sketch.name or ''} is still open; cannot create a feature",
                "Call end_sketch to close the sketch, then create_thread",
            )
        size_s = str(size).strip()
        if not size_s:
            raise fail("INVALID_ARGUMENT", "Thread size must be non-empty", "Pass size e.g. M10x1.5")
        if depth_m <= 0:
            raise fail("INVALID_ARGUMENT", "Thread depth must be positive", "Pass depth > 0")
        method_s = str(method).strip().lower()
        if method_s not in THREAD_METHODS:
            raise fail(
                "INVALID_ARGUMENT",
                f"Unknown thread method: {method!r}",
                f"method: {', '.join(THREAD_METHODS)}",
            )
        if diameter_m is not None and diameter_m <= 0:
            raise fail("INVALID_ARGUMENT", "Thread diameter must be positive", "Pass diameter > 0")
        if pitch_m is not None and pitch_m <= 0:
            raise fail("INVALID_ARGUMENT", "Thread pitch must be positive", "Pass pitch > 0")
        if not any(x.get("sign", 0) > 0 for x in doc.features):
            raise fail(
                "FEATURE_CREATE_FAILED",
                "No solid for thread feature",
                "Extrude a cylinder (external) or tube (internal), then create_thread",
            )
        edges = self.list_edges()
        if not edges:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "No edge to attach thread feature",
                "Pass edge from get_edges (prefer a circular rim)",
            )
        if edge is not None:
            ei = int(edge)
            if ei < 0 or ei >= len(edges):
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Edge index out of range: {ei}",
                    f"Valid range 0..{len(edges) - 1}",
                    index=ei,
                )
        type_s = (
            str(thread_type).strip()
            if thread_type
            else (THREAD_PROFILE_INTERNAL if internal else THREAD_PROFILE_EXTERNAL)
        )
        if not type_s:
            raise fail(
                "INVALID_ARGUMENT",
                "Thread type must be non-empty",
                "Pass thread_type e.g. Metric Die / Metric Tap",
            )
        n = sum(1 for x in doc.features if x.get("kind") == "thread") + 1
        name = f"Thread{n}"
        # Approximate helical tooth volume for fingerprint deltas (not ISO zone accurate).
        major = float(diameter_m) if diameter_m is not None else 0.01
        pitch = float(pitch_m) if pitch_m is not None else max(major * 0.15, 1e-4)
        tooth_h = 0.54 * pitch
        vol = abs(math.pi * major * tooth_h * 0.5 * float(depth_m))
        surf = abs(math.pi * major * float(depth_m) * 0.25)
        sign = -1 if method_s == "cut" else 1
        r = major * 0.5
        bbox3d = (-r, -r, 0.0, r, r, float(depth_m))
        doc.features.append(
            {
                "kind": "thread",
                "name": name,
                "sign": sign,
                "vol": float(vol),
                "surf": float(surf),
                "com": (0.0, 0.0, float(depth_m) * 0.5),
                "bbox3d": bbox3d,
                "faces": 2 if sign > 0 else 4,
                "edges": 2 if sign > 0 else 4,
                "size": size_s,
                "depth": float(depth_m),
                "method": method_s,
                "internal": bool(internal),
                "thread_type": type_s,
                "right_handed": bool(right_handed),
                "edge": None if edge is None else int(edge),
            }
        )
        doc.modified = True
        return FeatureInfo(name=name, kind="thread")
