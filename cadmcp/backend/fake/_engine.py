"""Fake backend · pure geometry engine (S8b).

- `_reflect_xy`: reflect point about sketch line (mirror)
- `_ray_hit_t`: face ray hit (up-to-face / up-to-next extrude)
- `_reflect_point` / `_reflected_bbox`: reflect point/bbox about reference plane
- `_rotate_point` / `_rotated_bbox`: rotate point/bbox about model axis
- `_vec_len` / `_vec_unit` / `_vec_dot` / `_vec_cross`: vector helpers
- `_rodrigues` / `_rotation_aligning`: Rodrigues rotation + align two directions

Prefer pure functions, no `self` (section 4.6). `_geom` stays in `fake_backend.py` (post-S8i)
because it depends on `_doc` / `_part_library` / `_assembly_library`.
"""
from __future__ import annotations

import math

from cadmcp.backend.protocol.constants import MAT_IDENTITY
from cadmcp.backend.protocol.models import FaceRef

from ._state import _vdot

# ---------- Sketch mirror ----------


def _reflect_xy(
    x: float, y: float, x0: float, y0: float, x1: float, y1: float
) -> tuple[float, float]:
    dx, dy = x1 - x0, y1 - y0
    ln2 = dx * dx + dy * dy
    if ln2 <= 1e-24:
        return x, y
    t = ((x - x0) * dx + (y - y0) * dy) / ln2
    px, py = x0 + t * dx, y0 + t * dy
    return 2.0 * px - x, 2.0 * py - y


# ---------- Face ray intersection ----------


def _ray_hit_t(
    p0: tuple[float, float, float],
    n_dir: tuple[float, float, float],
    face: FaceRef,
) -> float | None:
    nf = face.normal_m
    if face.kind != "plane" or nf is None:
        return None
    den = _vdot(n_dir, nf)
    if abs(den) < 1e-12:
        return None
    pf = face.centroid_m
    t = _vdot((pf[0] - p0[0], pf[1] - p0[1], pf[2] - p0[2]), nf) / den
    if t <= 1e-9:
        return None
    return t


# ---------- Reference-plane reflection ----------


def _reflect_point(
    p: tuple[float, float, float],
    origin: tuple[float, float, float],
    n: tuple[float, float, float],
) -> tuple[float, float, float]:
    d = (p[0] - origin[0]) * n[0] + (p[1] - origin[1]) * n[1] + (p[2] - origin[2]) * n[2]
    return (p[0] - 2 * d * n[0], p[1] - 2 * d * n[1], p[2] - 2 * d * n[2])


def _reflected_bbox(
    box: tuple[float, ...],
    origin: tuple[float, float, float],
    n: tuple[float, float, float],
) -> tuple[float, ...]:
    x0, y0, z0, x1, y1, z1 = box
    pts = [
        _reflect_point((x, y, z), origin, n)
        for x in (x0, x1)
        for y in (y0, y1)
        for z in (z0, z1)
    ]
    xs, ys, zs = zip(*pts, strict=True)
    return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


# ---------- Axis rotation ----------


def _rotate_point(
    p: tuple[float, float, float], axis: str, ang: float
) -> tuple[float, float, float]:
    x, y, z = p
    c, s = math.cos(ang), math.sin(ang)
    if axis[1] == "z":
        return (x * c - y * s, x * s + y * c, z)
    if axis[1] == "x":
        return (x, y * c - z * s, y * s + z * c)
    return (x * c + z * s, y, -x * s + z * c)


def _rotated_bbox(
    box: tuple[float, ...], axis: str, ang: float
) -> tuple[float, ...]:
    x0, y0, z0, x1, y1, z1 = box
    pts = [
        _rotate_point((x, y, z), axis, ang)
        for x in (x0, x1)
        for y in (y0, y1)
        for z in (z0, z1)
    ]
    xs, ys, zs = zip(*pts, strict=True)
    return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


# ---------- Vector helpers ----------


def _vec_len(v: tuple[float, float, float]) -> float:
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def _vec_unit(v: tuple[float, float, float]) -> tuple[float, float, float] | None:
    n = _vec_len(v)
    if n < 1e-15:
        return None
    return (v[0] / n, v[1] / n, v[2] / n)


def _vec_dot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _vec_cross(
    a: tuple[float, float, float], b: tuple[float, float, float]
) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


# ---------- Rodrigues rotation ----------


def _rodrigues(
    axis: tuple[float, float, float], ang: float
) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
    kx, ky, kz = axis
    c, s = math.cos(ang), math.sin(ang)
    t = 1.0 - c
    return (
        (t * kx * kx + c, t * kx * ky - s * kz, t * kx * kz + s * ky),
        (t * ky * kx + s * kz, t * ky * ky + c, t * ky * kz - s * kx),
        (t * kz * kx - s * ky, t * kz * ky + s * kx, t * kz * kz + c),
    )


def _rotation_aligning(
    src: tuple[float, float, float], dst: tuple[float, float, float]
) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
    a, b = _vec_unit(src), _vec_unit(dst)
    if a is None or b is None:
        return MAT_IDENTITY
    c = max(-1.0, min(1.0, _vec_dot(a, b)))
    if c > 1.0 - 1e-12:
        return MAT_IDENTITY
    if c < -1.0 + 1e-12:
        helper = (1.0, 0.0, 0.0) if abs(a[0]) < 0.9 else (0.0, 1.0, 0.0)
        axis = _vec_unit(_vec_cross(a, helper))
        if axis is None:
            return MAT_IDENTITY
        return _rodrigues(axis, math.pi)
    axis = _vec_unit(_vec_cross(a, b))
    if axis is None:
        return MAT_IDENTITY
    return _rodrigues(axis, math.acos(c))
    