"""Fake backend · feature domain · revolve (S8e-1).

S8e-1：revolve_blind。

Dependencies (self, MRO):
- `_enter` / `_require_doc` / `_put_angle_dim` / `list_edges`（FakeBackend）
- `_pending_sketch` / `_consume_sketch`（FakeSketchMixin）
- `_profile_of`（FakeExtrudeMixin）

Imports:
- `cadmcp.backend.protocol.constants`（REVOLVE_AXES）
- `cadmcp.backend.protocol.models`（FeatureInfo）
- `cadmcp.errors`（fail）
- `.._state`（_Doc / _Sketch）
"""
from __future__ import annotations

import math

from cadmcp.backend.protocol.constants import REVOLVE_AXES
from cadmcp.backend.protocol.models import FeatureInfo
from cadmcp.errors import fail


class FakeRevolveMixin:
    """Revolve (S8e-1: 1 method)."""

    def _init_state(self) -> None:
        pass

    def revolve_blind(
        self,
        angle_rad: float,
        axis: str,
        sketch: str | None = None,
        edge_index: int | None = None,
    ) -> FeatureInfo:
        self._enter("revolve_blind", angle=angle_rad, axis=axis, sketch=sketch, edge=edge_index)
        doc, pending = self._pending_sketch(sketch)
        if edge_index is None and axis not in REVOLVE_AXES:
            raise fail(
                "INVALID_ARGUMENT",
                f"Unknown revolve axis: {axis!r}",
                f"Available axes: {', '.join(REVOLVE_AXES)}",
                requested=axis,
            )
        if not 0.0 < angle_rad <= math.tau + 1e-9:
            raise fail(
                "INVALID_ARGUMENT",
                f"Revolve angle must be in (0, 360] degrees (radians internally): {angle_rad}",
                "Pass 0 < angle_deg <= 360",
            )
        f = self._profile_of(pending)
        u0, v0, u1, v1 = f["bbox2d"]
        uc, vc = (u0 + u1) / 2, (v0 + v1) / 2
        if edge_index is not None:
            edges = self.list_edges()
            if edge_index < 0 or edge_index >= len(edges):
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Edge index out of range: {edge_index}",
                    f"Use get_edges；Valid range 0..{len(edges) - 1}" if edges else "Create a solid first",
                    index=edge_index,
                )
            edge = edges[edge_index]
            if edge.kind != "line":
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Revolve-axis edge must be a line (got {edge.kind!r})",
                    "Use a get_edges index with kind=line",
                )
            mx, my, mz = edge.midpoint_m
            r_c = math.hypot(uc - mx, vc - my)
            r_lo, r_hi = r_c, r_c
            if r_c <= 1e-12:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Selected edge passes through profile centroid; cannot revolve",
                    "Pick a straight edge away from the profile",
                )
            r_max = r_c + max(u1 - u0, v1 - v0)
            bbox3d = (mx - r_max, my - r_max, mz - r_max, mx + r_max, my + r_max, mz + r_max)
            com = (mx, my, mz)
        else:
            # canned: axis family x → axis is v=0 line (u is axial);
            # families y/z → axis is u=0 (v axial; z family axial is z height)
            fam = axis[1]
            if fam == "x":
                r_lo, r_hi, r_c, a0, a1 = min(v0, v1), max(v0, v1), abs(vc), u0, u1
            else:  # "y" / "z": u is radial
                r_lo, r_hi, r_c, a0, a1 = min(u0, u1), max(u0, u1), abs(uc), v0, v1
            if r_lo < 0.0 < r_hi:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    f"Profile crosses revolve axis {axis!r} (radial range [{r_lo}, {r_hi}] m straddles 0)",
                    "Move profile to one side of the axis, or pick another axis (profile must not cross axis to revolve)",
                )
            if r_c == 0.0:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    f"Revolve axis {axis!r} passes through profile centroid; cannot revolve",
                    "Offset the whole profile off the axis, then revolve",
                )
            r_max = max(abs(r_lo), abs(r_hi))
            if fam == "x":
                bbox3d, com = (a0, -r_max, -r_max, a1, r_max, r_max), (uc, 0.0, 0.0)
            elif fam == "y":
                bbox3d, com = (-r_max, a0, -r_max, r_max, a1, r_max), (0.0, vc, 0.0)
            else:
                bbox3d, com = (-r_max, -r_max, a0, r_max, r_max, a1), (0.0, 0.0, (v0 + v1) / 2)
        full = angle_rad >= math.tau - 1e-9
        vol = f["area"] * angle_rad * r_c  # Pappus: profile area × centroid travel
        surf = f["perimeter"] * angle_rad * r_c + (0.0 if full else 2 * f["area"])
        n = sum(1 for x in doc.features if x["kind"] == "revolve") + 1
        has_cone = any(
            e.get("kind") == "line"
            and abs(float(e["x1"]) - float(e["x0"])) > 1e-12
            and abs(float(e["y1"]) - float(e["y0"])) > 1e-12
            for e in pending.entities
        )
        f.update(
            kind="revolve", sign=1, name=f"Revolve{n}",
            vol=vol, surf=surf, com=com, bbox3d=bbox3d,
            faces=3 if full else 6, edges=2 if full else 8,  # canned: full cylinder vs partial wedge
            has_cone=has_cone,
            angle=angle_rad, r_c=r_c, source_sketch=pending,
        )
        doc.features.append(f)
        self._put_angle_dim(doc, f"D1@{f['name']}", angle_rad, f, "angle")
        self._consume_sketch(doc, pending)
        doc.modified = True
        return FeatureInfo(name=f["name"], kind="revolve")
        