"""Read-only sketch profile conflict detection (rectangles + circles).

Shared by Fake and SolidWorks backends. Does not modify geometry.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from cadmcp.backend.protocol.models import SketchEntityRef
from cadmcp.errors import SideEffect, fail

_EPS = 1e-9
_COINCIDENT = 1e-7  # metres — shared edge / touching counts as conflict


@dataclass(frozen=True, slots=True)
class ProfileShape:
    """One closed profile candidate in sketch UV (metres)."""

    kind: str  # rect | circle
    index: int
    # rect: (xmin, ymin, xmax, ymax); circle: (cx, cy, r, _)
    data: tuple[float, ...]

    def as_context(self) -> dict[str, Any]:
        if self.kind == "rect":
            x0, y0, x1, y1 = self.data
            return {
                "kind": "rect",
                "index": self.index,
                "corners_m": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
            }
        cx, cy, r, _ = self.data
        return {
            "kind": "circle",
            "index": self.index,
            "center_m": [cx, cy],
            "radius_m": r,
        }


def _norm_rect(x0: float, y0: float, x1: float, y1: float) -> tuple[float, float, float, float]:
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def profiles_from_entities(entities: Sequence[SketchEntityRef]) -> list[ProfileShape]:
    """Extract rectangles and circles from list_sketch_entities-style refs.

    - ``kind=rect`` / ``kind=circle`` used as-is.
    - Axis-aligned closed loops of four ``line`` segments are reconstructed as rects.
    - Construction geometry is ignored.
    """
    out: list[ProfileShape] = []
    lines: list[tuple[int, tuple[float, float], tuple[float, float]]] = []
    for ent in entities:
        if ent.construction:
            continue
        if ent.kind == "rect" and len(ent.points_m) >= 2:
            (x0, y0), (x1, y1) = ent.points_m[0], ent.points_m[1]
            out.append(ProfileShape("rect", ent.index, _norm_rect(x0, y0, x1, y1)))
        elif ent.kind == "circle" and ent.radius_m is not None and ent.points_m:
            cx, cy = ent.points_m[0]
            out.append(ProfileShape("circle", ent.index, (cx, cy, float(ent.radius_m), 0.0)))
        elif ent.kind == "line" and len(ent.points_m) >= 2:
            lines.append((ent.index, ent.points_m[0], ent.points_m[1]))

    out.extend(_rects_from_lines(lines))
    return out


def _rects_from_lines(
    lines: list[tuple[int, tuple[float, float], tuple[float, float]]],
) -> list[ProfileShape]:
    """Greedy: find disjoint groups of 4 axis-aligned lines forming a rectangle."""
    unused = list(lines)
    found: list[ProfileShape] = []
    while len(unused) >= 4:
        group = _pick_rect_group(unused)
        if group is None:
            break
        idxs, box = group
        for i in sorted(idxs, reverse=True):
            unused.pop(i)
        found.append(ProfileShape("rect", idxs[0], box))
    return found


def _pick_rect_group(
    lines: list[tuple[int, tuple[float, float], tuple[float, float]]],
) -> tuple[list[int], tuple[float, float, float, float]] | None:
    n = len(lines)
    for a in range(n):
        for b in range(a + 1, n):
            for c in range(b + 1, n):
                for d in range(c + 1, n):
                    subset = [lines[a], lines[b], lines[c], lines[d]]
                    box = _rect_box_from_four(subset)
                    if box is not None:
                        return [a, b, c, d], box
    return None


def _rect_box_from_four(
    segs: list[tuple[int, tuple[float, float], tuple[float, float]]],
) -> tuple[float, float, float, float] | None:
    hs: list[tuple[float, float, float]] = []  # y, x0, x1
    vs: list[tuple[float, float, float]] = []  # x, y0, y1
    for _, p0, p1 in segs:
        x0, y0 = p0
        x1, y1 = p1
        if abs(y0 - y1) <= _EPS and abs(x0 - x1) > _EPS:
            hs.append((y0, min(x0, x1), max(x0, x1)))
        elif abs(x0 - x1) <= _EPS and abs(y0 - y1) > _EPS:
            vs.append((x0, min(y0, y1), max(y0, y1)))
        else:
            return None
    if len(hs) != 2 or len(vs) != 2:
        return None
    hs.sort(key=lambda t: t[0])
    vs.sort(key=lambda t: t[0])
    y_lo, x0a, x1a = hs[0]
    y_hi, x0b, x1b = hs[1]
    x_lo, y0a, y1a = vs[0]
    x_hi, y0b, y1b = vs[1]
    if abs(y_hi - y_lo) <= _EPS or abs(x_hi - x_lo) <= _EPS:
        return None
    # Horizontal spans must match vertical x-range; vertical spans match y-range.
    for x0, x1 in ((x0a, x1a), (x0b, x1b)):
        if abs(x0 - x_lo) > _COINCIDENT or abs(x1 - x_hi) > _COINCIDENT:
            return None
    for y0, y1 in ((y0a, y1a), (y0b, y1b)):
        if abs(y0 - y_lo) > _COINCIDENT or abs(y1 - y_hi) > _COINCIDENT:
            return None
    return (x_lo, y_lo, x_hi, y_hi)


def _rects_conflict(a: ProfileShape, b: ProfileShape) -> bool:
    ax0, ay0, ax1, ay1 = a.data
    bx0, by0, bx1, by1 = b.data
    # Separated (strict gap) → ok
    if ax1 < bx0 - _COINCIDENT or bx1 < ax0 - _COINCIDENT:
        return False
    if ay1 < by0 - _COINCIDENT or by1 < ay0 - _COINCIDENT:
        return False
    # Nested (strictly inside without shared boundary) → ok
    a_in_b = ax0 > bx0 + _COINCIDENT and ay0 > by0 + _COINCIDENT and ax1 < bx1 - _COINCIDENT and ay1 < by1 - _COINCIDENT
    b_in_a = bx0 > ax0 + _COINCIDENT and by0 > ay0 + _COINCIDENT and bx1 < ax1 - _COINCIDENT and by1 < ay1 - _COINCIDENT
    if a_in_b or b_in_a:
        return False
    # Overlap area or shared edge → conflict
    return True


def _circles_conflict(a: ProfileShape, b: ProfileShape) -> bool:
    ax, ay, ar, _ = a.data
    bx, by, br, _ = b.data
    d = math.hypot(ax - bx, ay - by)
    # Concentric or nested (no boundary intersection): |r1-r2| > d (strict) or d≈0 with unequal r
    if d + min(ar, br) < max(ar, br) - _COINCIDENT:
        return False  # one strictly inside the other
    if d <= _COINCIDENT and abs(ar - br) > _COINCIDENT:
        return False  # concentric unequal → ring
    if d <= _COINCIDENT and abs(ar - br) <= _COINCIDENT:
        return True  # identical → conflict
    # Separate
    if d > ar + br + _COINCIDENT:
        return False
    # Boundary intersection or touch → conflict
    return True


def _rect_circle_conflict(rect: ProfileShape, circ: ProfileShape) -> bool:
    x0, y0, x1, y1 = rect.data
    cx, cy, r, _ = circ.data
    # Closest point on rect to center
    qx = min(max(cx, x0), x1)
    qy = min(max(cy, y0), y1)
    d = math.hypot(cx - qx, cy - qy)
    if d > r + _COINCIDENT:
        return False  # circle outside, no touch
    # Circle fully inside rect without touching boundary
    if (
        cx - r > x0 + _COINCIDENT
        and cy - r > y0 + _COINCIDENT
        and cx + r < x1 - _COINCIDENT
        and cy + r < y1 - _COINCIDENT
    ):
        return False
    # Rect fully inside circle without touching
    corners = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    if all(math.hypot(px - cx, py - cy) < r - _COINCIDENT for px, py in corners):
        return False
    return True  # intersect / touch / overlap


def find_profile_conflicts(profiles: Sequence[ProfileShape]) -> list[dict[str, Any]]:
    """Return conflict records for pairwise profile clashes."""
    conflicts: list[dict[str, Any]] = []
    for i in range(len(profiles)):
        for j in range(i + 1, len(profiles)):
            a, b = profiles[i], profiles[j]
            hit = False
            if a.kind == "rect" and b.kind == "rect":
                hit = _rects_conflict(a, b)
            elif a.kind == "circle" and b.kind == "circle":
                hit = _circles_conflict(a, b)
            elif a.kind == "rect" and b.kind == "circle":
                hit = _rect_circle_conflict(a, b)
            elif a.kind == "circle" and b.kind == "rect":
                hit = _rect_circle_conflict(b, a)
            if hit:
                conflicts.append({"a": a.as_context(), "b": b.as_context()})
    return conflicts


def raise_if_profile_conflicts(entities: Iterable[SketchEntityRef] | Sequence[SketchEntityRef]) -> None:
    """Raise SKETCH_PROFILE_CONFLICT when closed rect/circle profiles clash."""
    profiles = profiles_from_entities(list(entities))
    conflicts = find_profile_conflicts(profiles)
    if not conflicts:
        return
    raise fail(
        "SKETCH_PROFILE_CONFLICT",
        f"Sketch has {len(conflicts)} conflicting closed profile(s)",
        "Split into multiple sketches/features; do not merge overlapping contours in one sketch",
        side_effect=SideEffect.NONE,
        conflicts=conflicts,
    )
