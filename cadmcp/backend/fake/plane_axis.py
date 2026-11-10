"""Fake backend · reference planes/axes（S8d round 2）。

S8d-2: 8 methods (list_planes / _plane_names / _resolve_plane_name / _plane_frame /
       _uv_xyz / create_plane / _angle_axis_dir / create_axis）。

Dependencies (self, MRO):
- `_enter` / `_require_doc` / `_require_part` / `list_edges`（FakeBackend）

Imports:
- `cadmcp.backend.protocol.constants`（DEFAULT_PLANES / DEFAULT_PLANE_FRAMES / REVOLVE_AXES）
- `cadmcp.backend.protocol.geometry_math`（apply_matrix3 / rotation_matrix_dir）
- `cadmcp.backend.protocol.models`（FeatureInfo）
- `cadmcp.backend.protocol.parsers`（canonical_plane）
- `cadmcp.backend.protocol.validators`（validate_create_plane）
- `cadmcp.errors`（fail）
- `._state`（_Doc / _PARALLEL_TOL / _vadd / _vmul / _vcross / _vnorm2 / _vunit）
"""
from __future__ import annotations

from collections.abc import Sequence

from cadmcp.backend.protocol.constants import (
    DEFAULT_PLANE_FRAMES,
    DEFAULT_PLANES,
    REVOLVE_AXES,
)
from cadmcp.backend.protocol.geometry_math import apply_matrix3, rotation_matrix_dir
from cadmcp.backend.protocol.models import FeatureInfo
from cadmcp.backend.protocol.parsers import canonical_plane
from cadmcp.backend.protocol.validators import validate_create_plane
from cadmcp.errors import fail

from ._state import (
    _PARALLEL_TOL,
    _Doc,
    _vadd,
    _vcross,
    _vmul,
    _vnorm2,
    _vunit,
)


class FakePlaneAxisMixin:
    """reference planes/axes (S8d-2: 8 methods)."""

    def _init_state(self) -> None:
        pass  # State owned by FakeBackend._init_state(_plane_uv_root, etc.)

    def list_planes(self) -> list[str]:
        self._enter("list_planes")
        return self._plane_names(self._require_doc())

    def _plane_names(self, doc: _Doc) -> list[str]:
        return list(DEFAULT_PLANES) + [str(p["name"]) for p in doc.planes]

    def _resolve_plane_name(self, doc: _Doc, name: str) -> str | None:
        canon = canonical_plane(name)
        if canon is not None:
            return canon
        for plane in doc.planes:
            if plane["name"] == name:
                return str(plane["name"])
        return None

    def _plane_frame(
        self, name: str
    ) -> tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ]:
        canon = canonical_plane(name) or name
        if canon in DEFAULT_PLANE_FRAMES:
            return DEFAULT_PLANE_FRAMES[canon]
        doc = self._require_doc()
        for plane in doc.planes:
            if plane["name"] == name:
                return plane["origin"], plane["u"], plane["v"], plane["n"]
        raise fail(
            "FEATURE_NOT_FOUND",
            f"Reference plane not found: {name!r}",
            f"Available reference planes: {', '.join(self._plane_names(doc))} (use list_planes)",
            requested=name,
        )

    def _uv_xyz(self, plane: str, u: float, v: float) -> tuple[float, float, float]:
        origin, uu, vv, _n = self._plane_frame(plane)
        return _vadd(origin, _vmul(uu, u), _vmul(vv, v))

    def create_plane(
        self,
        reference: str | None = None,
        offset_m: float = 0.0,
        flip: bool = False,
        *,
        mode: str = "offset",
        angle_rad: float | None = None,
        axis: str | None = None,
        points_m: Sequence[tuple[float, float, float]] | None = None,
    ) -> FeatureInfo:
        self._enter(
            "create_plane",
            reference=reference,
            offset=offset_m,
            flip=flip,
            mode=mode,
            angle=angle_rad,
            axis=axis,
            points=points_m,
        )
        doc = self._require_part("Use a part document to create a reference plane")
        validate_create_plane(mode, reference, True, angle_rad, axis, points_m)
        if mode == "offset":
            parent = self._resolve_plane_name(doc, str(reference))
            if parent is None:
                raise fail(
                    "FEATURE_NOT_FOUND",
                    f"Reference plane not found: {reference!r}",
                    f"Available reference planes: {', '.join(self._plane_names(doc))} (use list_planes)",
                    requested=reference,
                )
            origin, u, v, n = self._plane_frame(parent)
            signed = -float(offset_m) if flip else float(offset_m)
            rec = {
                "reference": parent,
                "offset": float(offset_m),
                "flip": bool(flip),
                "origin": _vadd(origin, _vmul(n, signed)),
                "u": u,
                "v": v,
                "n": n,
            }
        elif mode == "angle":
            parent = self._resolve_plane_name(doc, str(reference))
            if parent is None:
                raise fail(
                    "FEATURE_NOT_FOUND",
                    f"Reference plane not found: {reference!r}",
                    f"Available reference planes: {', '.join(self._plane_names(doc))} (use list_planes)",
                    requested=reference,
                )
            origin, u, v, n = self._plane_frame(parent)
            direction = self._angle_axis_dir(doc, str(axis))
            if abs(direction[0] * n[0] + direction[1] * n[1] + direction[2] * n[2]) > 1e-6:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Angle axis must lie in the reference plane",
                    "Use create_axis on the reference plane (e.g. axis from Front+Right)",
                )
            signed = -float(angle_rad or 0.0) if flip else float(angle_rad or 0.0)
            rot = rotation_matrix_dir(direction, signed)
            rec = {
                "reference": parent,
                "axis": str(axis),
                "angle": signed,
                "flip": bool(flip),
                "origin": origin,
                "u": apply_matrix3(rot, u),
                "v": apply_matrix3(rot, v),
                "n": apply_matrix3(rot, n),
            }
        else:
            p0, p1, p2 = (tuple(float(c) for c in p) for p in points_m)  # type: ignore[misc]
            e1 = (p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2])
            e2 = (p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2])
            nn = _vcross(e1, e2)
            if _vnorm2(nn) < _PARALLEL_TOL:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Three points are collinear; cannot define a reference plane",
                    "Provide three non-collinear points",
                )
            n = _vunit(nn)
            u = _vunit(e1)
            v = _vcross(n, u)
            rec = {"origin": p0, "u": u, "v": v, "n": n, "points": (p0, p1, p2)}
        name = f"Plane{len(doc.planes) + 1}"
        rec.update({"name": name, "kind": "plane", "mode": mode})
        doc.planes.append(rec)
        doc.modified = True
        return FeatureInfo(name=name, kind="plane")

    def _angle_axis_dir(self, doc: _Doc, axis: str) -> tuple[float, float, float]:
        if axis in REVOLVE_AXES:
            letter = axis[1]
            sign = 1.0 if axis[0] == "+" else -1.0
            if letter == "x":
                return (sign, 0.0, 0.0)
            if letter == "y":
                return (0.0, sign, 0.0)
            return (0.0, 0.0, sign)
        hit = next((a for a in doc.axes if a["name"] == axis), None)
        if hit is None:
            raise fail(
                "FEATURE_NOT_FOUND",
                f"Reference axis not found: {axis!r}",
                "Call create_axis first, or pass +x/+y/+z",
                requested=axis,
            )
        if "planes" not in hit:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "Angle mode needs an axis from two intersecting planes",
                "Use create_axis(planes=[p1,p2]); do not use an edge axis",
            )
        n1 = self._plane_frame(str(hit["planes"][0]))[3]
        n2 = self._plane_frame(str(hit["planes"][1]))[3]
        d = _vcross(n1, n2)
        if _vnorm2(d) < _PARALLEL_TOL:
            raise fail("FEATURE_CREATE_FAILED", "Invalid reference-axis direction", "Use another pair of intersecting planes for the axis")
        return _vunit(d)

    def create_axis(
        self, planes: tuple[str, str] | None = None, edge: int | None = None
    ) -> FeatureInfo:
        self._enter("create_axis", planes=planes, edge=edge)
        doc = self._require_part("Use a part document to create a reference axis")
        has_planes = planes is not None
        has_edge = edge is not None
        if has_planes == has_edge:
            raise fail(
                "INVALID_ARGUMENT",
                "create_axis requires either planes or edge",
                "Pass planes for plane intersection, or a straight edge index",
            )
        if planes is not None:
            a = self._resolve_plane_name(doc, planes[0])
            b = self._resolve_plane_name(doc, planes[1])
            if a is None or b is None:
                missing = planes[0] if a is None else planes[1]
                raise fail(
                    "FEATURE_NOT_FOUND",
                    f"Reference plane not found: {missing!r}",
                    f"Available reference planes: {', '.join(self._plane_names(doc))}",
                    requested=missing,
                )
            na, nb = self._plane_frame(a)[3], self._plane_frame(b)[3]
            if _vnorm2(_vcross(na, nb)) < _PARALLEL_TOL:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Planes are parallel; cannot define intersection axis",
                    "Pick two intersecting reference planes",
                )
            name = f"Axis{len(doc.axes) + 1}"
            doc.axes.append({"name": name, "kind": "axis", "planes": (a, b)})
            doc.modified = True
            return FeatureInfo(name=name, kind="axis")
        pool = self.list_edges()
        idx = int(edge)  # type: ignore[arg-type]
        if not pool:
            raise fail("REF_NOT_FOUND", "No selectable edges in the document", "Create a solid with extrude first")
        if idx < 0 or idx >= len(pool):
            raise fail(
                "INVALID_ARGUMENT",
                f"Edge index out of range: {idx}",
                f"Use get_edges；Valid range 0..{len(pool) - 1}",
                index=idx,
            )
        if pool[idx].kind != "line":
            raise fail(
                "INVALID_ARGUMENT",
                f"Reference-axis edge must be a line (got {pool[idx].kind!r}）",
                "Use get_edges to pick an index with kind=line",
            )
        name = f"Axis{len(doc.axes) + 1}"
        doc.axes.append({"name": name, "kind": "axis", "edge": idx})
        doc.modified = True
        return FeatureInfo(name=name, kind="axis")
        