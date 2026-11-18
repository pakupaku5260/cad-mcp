"""Protocol layer · geometry algorithms (cadmcp conventions; CAD-agnostic with possible SolidWorks semantics)."""
from __future__ import annotations

import math


def extrude_z_range_m(
    depth_m: float,
    direction: str = "blind",
    depth2_m: float | None = None,
    reverse: bool = False,
) -> tuple[float, float]:
    if direction == "midplane":
        h = depth_m / 2.0
        return (-h, h)
    if direction == "both":
        d2 = float(depth2_m or 0.0)
        if reverse:
            return (-depth_m, d2)
        return (-d2, depth_m)
    if reverse:
        return (-depth_m, 0.0)
    if direction == "through_all":
        return (0.0, depth_m)
    return (0.0, depth_m)


def regular_polygon_lines(
    sides: int,
    radius_m: float,
    polygon_type: str,
    cx: float = 0.0,
    cy: float = 0.0,
) -> list[tuple[float, float, float, float]]:
    if polygon_type == "circumscribed":
        r_c = radius_m / math.cos(math.pi / sides)
        start = -math.pi / sides
    else:
        r_c = radius_m
        start = 0.0
    verts = [
        (
            cx + r_c * math.cos(start + i * 2 * math.pi / sides),
            cy + r_c * math.sin(start + i * 2 * math.pi / sides),
        )
        for i in range(sides)
    ]
    return [
        (verts[i][0], verts[i][1], verts[(i + 1) % sides][0], verts[(i + 1) % sides][1])
        for i in range(sides)
    ]


def polygon_vertex_point_m(
    sides: int, radius_m: float, polygon_type: str
) -> tuple[float, float]:
    if polygon_type == "circumscribed":
        r_c = radius_m / math.cos(math.pi / sides)
        ang = -math.pi / sides
        return r_c * math.cos(ang), r_c * math.sin(ang)
    return radius_m, 0.0


AABB_INTERFERENCE_EPS_M = 1e-7


def aabb_pair_status(
    a: tuple[float, float, float, float, float, float],
    b: tuple[float, float, float, float, float, float],
    *,
    coincident_as_interference: bool,
    eps_m: float = AABB_INTERFERENCE_EPS_M,
) -> str:
    ox = min(a[3], b[3]) - max(a[0], b[0])
    oy = min(a[4], b[4]) - max(a[1], b[1])
    oz = min(a[5], b[5]) - max(a[2], b[2])
    if ox > eps_m and oy > eps_m and oz > eps_m:
        return "interfere"
    if ox >= -eps_m and oy >= -eps_m and oz >= -eps_m:
        return "interfere" if coincident_as_interference else "contact"
    return "clear"


def line_matches_ends(
    x0: float, y0: float, x1: float, y1: float,
    ax: float, ay: float, bx: float, by: float, *, tol_m: float = 1e-7,
) -> bool:
    def same(px: float, py: float, qx: float, qy: float) -> bool:
        return abs(px - qx) <= tol_m and abs(py - qy) <= tol_m
    return (
        (same(x0, y0, ax, ay) and same(x1, y1, bx, by))
        or (same(x0, y0, bx, by) and same(x1, y1, ax, ay))
    )


def circle_matches_center_rim(
    cx: float, cy: float, radius: float,
    ax: float, ay: float, bx: float, by: float, *, tol_m: float = 1e-7,
) -> bool:
    def at_center(px: float, py: float) -> bool:
        return abs(px - cx) <= tol_m and abs(py - cy) <= tol_m
    def on_rim(px: float, py: float) -> bool:
        return abs(math.hypot(px - cx, py - cy) - radius) <= max(tol_m, 1e-9 * max(radius, 1.0))
    return (at_center(ax, ay) and on_rim(bx, by)) or (at_center(bx, by) and on_rim(ax, ay))


def thin_wall_com_args(thin_type: str, thickness_m: float) -> tuple[float, float, int]:
    SW_THIN_ONE = 0
    SW_THIN_MID = 2
    if thin_type == "mid":
        return thickness_m, 0.0, SW_THIN_MID
    if thin_type == "both":
        return thickness_m, thickness_m, SW_THIN_ONE
    return thickness_m, 0.0, SW_THIN_ONE
    