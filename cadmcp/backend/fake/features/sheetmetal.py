"""Fake backend · feature domain · sheet metal（S8e-9）。

S8e-9：base_flange / _sheet_base / edge_flange / sheet_metal_unfold。

Dependencies (self, MRO):
- `_enter` / `_require_doc` / `_doc`（FakeBackend）
- `_pending_sketch` / `_consume_sketch`（FakeSketchMixin，S8d）
- `_profile_of` / `_apply_extrude_geom`（FakeExtrudeMixin，S8e-1）
- `list_edges`（FakeSelectionMixin，S8e-4）
- `_checked_indexes`（FakeModifyMixin，S8e-5）

Imports:
- `cadmcp.backend.protocol.models`（FeatureInfo / SheetMetalFlatSI）
- `cadmcp.errors`（fail）
"""
from __future__ import annotations

import math

from cadmcp.backend.protocol.models import FeatureInfo, SheetMetalFlatSI
from cadmcp.errors import fail


class FakeSheetMetalMixin:
    """sheet metal (S8e-9: 4 methods)."""

    def _init_state(self) -> None:
        pass  # State owned by FakeBackend._init_state

    # ---------- Base flange ----------

    def base_flange(
        self,
        thickness_m: float,
        radius_m: float | None = None,
        sketch: str | None = None,
    ) -> FeatureInfo:
        self._enter("base_flange", thickness=thickness_m, radius=radius_m, sketch=sketch)
        if thickness_m <= 0:
            raise fail("INVALID_ARGUMENT", "Sheet metal thickness must be positive", "Pass thickness > 0")
        doc, pending = self._pending_sketch(sketch)
        prof = self._profile_of(pending)
        radius = 0.5 * float(thickness_m) if radius_m is None else float(radius_m)
        if radius < 0:
            raise fail("INVALID_ARGUMENT", "Bend radius cannot be negative", "Omit radius to use 0.5×thickness")
        n = sum(1 for x in doc.features if x["kind"] == "base_flange") + 1
        z0, z1 = 0.0, float(thickness_m)
        prof.update(
            kind="base_flange", sign=1, name=f"Base-Flange{n}",
            thickness=float(thickness_m), radius=radius, k_factor=0.5,
            plane=pending.plane, flanges=[], flattened=False,
            faces=6, edges=12,
        )
        self._apply_extrude_geom(prof, z0, z1)
        prof["source_sketch"] = pending
        doc.features.append(prof)
        n_sm = sum(1 for x in doc.features if x["kind"] == "sheet_metal") + 1
        doc.features.append({
            "kind": "sheet_metal", "sign": 0, "name": f"SheetMetal{n_sm}",
            "vol": 0.0, "surf": 0.0, "faces": 0, "edges": 0,
        })
        n_fp = sum(1 for x in doc.features if x["kind"] == "flat_pattern") + 1
        doc.features.append({
            "kind": "flat_pattern", "sign": 0, "name": f"Flat-Pattern{n_fp}",
            "vol": 0.0, "surf": 0.0, "faces": 0, "edges": 0, "suppressed": True,
        })
        self._consume_sketch(doc, pending)
        doc.modified = True
        return FeatureInfo(name=prof["name"], kind="base_flange")

    # ---------- Base lookup ----------

    def _sheet_base(self, doc) -> dict:
        bases = [x for x in doc.features if x.get("kind") == "base_flange" and x.get("sign", 0) > 0]
        if not bases:
            raise fail("FEATURE_CREATE_FAILED", "Edge flange requires base flange", "Draw closed sketch then base_flange")
        return bases[-1]

    # ---------- Edge flange ----------

    def edge_flange(
        self,
        edge: int,
        length_m: float,
        angle_rad: float = math.pi / 2,
        radius_m: float | None = None,
    ) -> FeatureInfo:
        self._enter("edge_flange", edge=edge, length=length_m, angle=angle_rad, radius=radius_m)
        if length_m <= 0:
            raise fail("INVALID_ARGUMENT", "Edge flange length must be positive", "Pass length > 0")
        if angle_rad <= 0 or angle_rad >= math.pi:
            raise fail("INVALID_ARGUMENT", "Edge flange angle must be in (0, 180) degrees", "Pass angle_deg, e.g. 90")
        doc = self._require_doc()
        base = self._sheet_base(doc)
        pool = self.list_edges()
        if not pool:
            raise fail("FEATURE_CREATE_FAILED", "No edge available for flange", "Call base_flange first")
        self._checked_indexes([int(edge)], len(pool), "edge", "get_edges")
        ref = pool[int(edge)]
        thickness = float(base.get("thickness") or 0.0)
        radius = float(base.get("radius") or 0.5 * thickness) if radius_m is None else float(radius_m)
        x0, y0, z0, x1, y1, z1 = (float(v) for v in base["bbox3d"])
        mx, my, mz = ref.midpoint_m
        atol = max(1e-9, 1e-6 * max(abs(x1 - x0), abs(y1 - y0), abs(z1 - z0), 1e-6))
        hits: list[tuple[int, float]] = []
        for axis, lo, hi, mid in (
            (0, x0, x1, mx), (1, y0, y1, my), (2, z0, z1, mz),
        ):
            if abs(mid - hi) <= atol:
                hits.append((axis, 1.0))
            elif abs(mid - lo) <= atol:
                hits.append((axis, -1.0))
        extents = (x1 - x0, y1 - y0, z1 - z0)
        thick_axis = min(range(3), key=lambda i: extents[i])
        length_hit = next((h for h in hits if h[0] == thick_axis), None)
        other_hit = next((h for h in hits if h[0] != thick_axis), None)
        if length_hit is None or other_hit is None:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "This edge cannot be used for edge flange",
                "Pick a long edge on the sheet-metal profile (get_edges midpoint on the broad face)",
            )
        bb = [x0, y0, z0, x1, y1, z1]
        la, lsign = length_hit
        oa, osign = other_hit
        if lsign > 0:
            bb[la + 3] += float(length_m)
        else:
            bb[la] -= float(length_m)
        if osign > 0:
            bb[oa + 3] += thickness
        else:
            bb[oa] -= thickness
        edge_len = extents[{0, 1, 2}.difference({la, oa}).pop()]
        base["bbox3d"] = tuple(bb)
        base["vol"] = float(base.get("vol") or 0.0) + float(length_m) * thickness * edge_len
        base["surf"] = float(base.get("surf") or 0.0) + 2.0 * float(length_m) * (thickness + edge_len)
        base["faces"] = 14
        base["edges"] = 28
        base.setdefault("flanges", []).append(
            {"length": float(length_m), "angle": float(angle_rad), "radius": radius}
        )
        n = sum(1 for x in doc.features if x["kind"] == "edge_flange") + 1
        feat = {
            "kind": "edge_flange", "sign": 0, "name": f"Edge-Flange{n}",
            "vol": 0.0, "surf": 0.0, "faces": 0, "edges": 0,
            "length": float(length_m), "angle": float(angle_rad),
        }
        doc.features.append(feat)
        doc.modified = True
        return FeatureInfo(name=feat["name"], kind="edge_flange")

    # ---------- Unfold ----------

    def sheet_metal_unfold(self) -> SheetMetalFlatSI:
        self._enter("sheet_metal_unfold")
        doc = self._require_doc()
        base = self._sheet_base(doc)
        thickness = float(base.get("thickness") or 0.0)
        radius = float(base.get("radius") or 0.5 * thickness)
        k = float(base.get("k_factor") or 0.5)
        ba = 0.0
        extra = 0.0
        for fl in base.get("flanges") or []:
            extra += float(fl.get("length") or 0.0)
            ba += float(fl.get("angle") or 0.0) * (radius + k * thickness)
        x0, y0, x1, y1 = (float(v) for v in base.get("bbox2d", (0.0, 0.0, 1.0, 1.0)))
        a, b = abs(x1 - x0), abs(y1 - y0)
        w, h = max(a, b), min(a, b) + extra + ba
        length, width = (w, h) if w >= h else (h, w)
        base["flattened"] = True
        for fp in doc.features:
            if fp.get("kind") == "flat_pattern":
                fp["suppressed"] = False
        t = thickness
        base["bbox3d"] = (0.0, 0.0, 0.0, length, width, t)
        # Real flat-pattern unsuppress changes face/edge counts; canned resets to thin plate 6/12 for delta keys.
        base["faces"] = 6
        base["edges"] = 12
        doc.modified = True
        return SheetMetalFlatSI(
            length_m=length, width_m=width, thickness_m=t, k_factor=k,
        )

    def miter_flange(
        self,
        edges: list[int],
        length_m: float,
        angle_rad: float = math.pi / 2,
        radius_m: float | None = None,
    ) -> FeatureInfo:
        self._enter("miter_flange", edges=edges, length=length_m, angle=angle_rad)
        if length_m <= 0:
            raise fail("INVALID_ARGUMENT", "Miter flange length must be positive", "Pass length > 0")
        if not edges:
            raise fail("INVALID_ARGUMENT", "Miter flange needs at least one edge", "Pass edges=[...]")
        doc = self._require_doc()
        base = self._sheet_base(doc)
        pool = self.list_edges()
        self._checked_indexes([int(e) for e in edges], len(pool), "edge", "get_edges")
        n = sum(1 for x in doc.features if x["kind"] == "miter_flange") + 1
        feat = {
            "kind": "miter_flange",
            "sign": 0,
            "name": f"Miter-Flange{n}",
            "vol": 0.0,
            "surf": 0.0,
            "faces": 0,
            "edges": 0,
            "length": float(length_m),
            "angle": float(angle_rad),
            "edges_idx": [int(e) for e in edges],
        }
        base.setdefault("flanges", []).append(
            {"length": float(length_m), "angle": float(angle_rad), "miter": True}
        )
        doc.features.append(feat)
        doc.modified = True
        return FeatureInfo(name=feat["name"], kind="miter_flange")

    def hem_flange(
        self,
        edge: int,
        length_m: float,
        radius_m: float | None = None,
    ) -> FeatureInfo:
        self._enter("hem_flange", edge=edge, length=length_m, radius=radius_m)
        if length_m <= 0:
            raise fail("INVALID_ARGUMENT", "Hem length must be positive", "Pass length > 0")
        doc = self._require_doc()
        self._sheet_base(doc)
        pool = self.list_edges()
        self._checked_indexes([int(edge)], len(pool), "edge", "get_edges")
        n = sum(1 for x in doc.features if x["kind"] == "hem") + 1
        feat = {
            "kind": "hem",
            "sign": 0,
            "name": f"Hem{n}",
            "vol": 0.0,
            "surf": 0.0,
            "faces": 0,
            "edges": 0,
            "length": float(length_m),
            "edge": int(edge),
        }
        doc.features.append(feat)
        doc.modified = True
        return FeatureInfo(name=feat["name"], kind="hem")

    def export_flat_dxf(self, path) -> None:
        self._enter("export_flat_dxf", path=path)
        doc = self._require_doc()
        self._sheet_base(doc)
        from pathlib import Path as _Path

        p = _Path(path)
        try:
            p.write_text(f"FAKE-EXPORT:dxf-flat:{doc.title}", encoding="utf-8")
        except OSError as exc:
            raise fail("SAVE_FAILED", f"Write failed: {exc}", "Check directory and permissions") from exc

    def sheet_metal_bend_table(self) -> list[dict]:
        self._enter("sheet_metal_bend_table")
        doc = self._require_doc()
        base = self._sheet_base(doc)
        rows: list[dict] = []
        for i, fl in enumerate(base.get("flanges") or []):
            rows.append(
                {
                    "index": i,
                    "angle_deg": float(fl.get("angle") or 0.0) * 180.0 / math.pi,
                    "radius_m": float(fl.get("radius") or base.get("radius") or 0.0),
                    "k_factor": float(base.get("k_factor") or 0.5),
                }
            )
        return rows
