"""Face/edge selector v1: index + coordinate dual-handle resolution (v4 §9, W7).

Handle = (index, coordinates) from query tools (get_entities), echoed back by caller;
**re-resolved every call** (stale after model edits; no cached refs).

Rules (§9):
1. Index exact match only if coordinate delta ≤ 0.5 mm (exact)—stale index won't fake exact;
2. Else nearest-neighbor within 2 mm (proximity); beyond → REF_NOT_FOUND with nearest distance;
3. Ties within epsilon → REF_AMBIGUOUS with candidate indexes—never guess;
4. Match quality returned (exact vs proximity).

Tolerances are calibration points (§9 table 0.5 mm / 2 mm). Conversion via UnitContext only.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, TypeVar

from cadmcp.backend.protocol.models import EdgeRef, FaceRef
from cadmcp.errors import fail
from cadmcp.units import UnitContext

FACE_FILTER_KINDS = frozenset({"plane", "cylinder", "cone"})
EDGE_FILTER_KINDS = frozenset({"line", "circle"})
FACE_QUERY_EXTREME: dict[str, tuple[int, bool]] = {
    "max_x": (0, True),
    "min_x": (0, False),
    "max_y": (1, True),
    "min_y": (1, False),
    "max_z": (2, True),
    "min_z": (2, False),
}
FACE_QUERY_AXIS: dict[str, int] = {"axis_x": 0, "axis_y": 1, "axis_z": 2}
FACE_QUERIES = frozenset(FACE_QUERY_EXTREME) | frozenset(FACE_QUERY_AXIS)
_AXIS_ALIGN = 0.9

_MM = UnitContext("mm")
TOL_EXACT_M = _MM.to_m(0.5)
TOL_NEAR_M = _MM.to_m(2.0)
COORD_EPS_M = _MM.to_m(1e-6)


@dataclass(frozen=True)
class Ref:
    """Dual handle: index + entity coordinates from query results."""

    index: int
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class Resolved:
    """Resolved pool entity (not the incoming handle) plus match quality."""

    entity: FaceRef | EdgeRef
    quality: Literal["exact", "proximity"]
    distance_m: float


def _coords(entity: FaceRef | EdgeRef) -> tuple[float, float, float]:
    """Face centroid or edge midpoint per protocol model."""
    if isinstance(entity, FaceRef):
        return entity.centroid_m
    return entity.midpoint_m


def resolve(ref: Ref, entities: Sequence[FaceRef | EdgeRef]) -> Resolved:
    """Resolve dual handle: index exact → nearest neighbor → explicit errors.

    Raises:
        REF_NOT_FOUND: no hit (empty pool includes nearest distance);
        REF_AMBIGUOUS: tied nearest within tolerance band.
    """
    if not entities:
        raise fail(
            "REF_NOT_FOUND",
            "Candidate entity list is empty (no faces/edges to reference)",
            "Call get_entities first; create features on an empty model",
            requested=ref.index,
        )
    dists = [(math.dist((ref.x, ref.y, ref.z), _coords(e)), e) for e in entities]

    for d, e in dists:
        if e.index == ref.index and d <= TOL_EXACT_M:
            return Resolved(entity=e, quality="exact", distance_m=d)

    d_min, best = min(dists, key=lambda t: t[0])
    if d_min > TOL_NEAR_M:
        raise fail(
            "REF_NOT_FOUND",
            f"Reference unresolved: nearest entity {_MM.from_m(d_min):.3g} mm away"
            f" (over {_MM.from_m(TOL_NEAR_M):.3g} mm tolerance)",
            "Re-fetch handles via get_entities; stale handles fail after model edits",
            requested=ref.index,
            distance_mm=_MM.from_m(d_min),
        )
    tied = [e for d, e in dists if abs(d - d_min) <= COORD_EPS_M]
    if len(tied) > 1:
        raise fail(
            "REF_AMBIGUOUS",
            f"Ambiguous reference: {len(tied)} entities equally near"
            f" (closest {_MM.from_m(d_min):.3g} mm)",
            "Disambiguate with tighter coordinates or index from get_entities",
            requested=ref.index,
            candidates=sorted(e.index for e in tied),
        )
    return Resolved(entity=best, quality="proximity", distance_m=d_min)


def resolve_mate_index(
    index: int,
    coord_m: tuple[float, float, float] | None,
    pool: Sequence[FaceRef | EdgeRef],
    *,
    component: str,
    kind: Literal["face", "edge"],
    filter_kind: str | None = None,
) -> int:
    """Mate face/edge: index-only when no coords; dual-handle resolve when coords present.

    With filter_kind, index is per-kind (#cylinder:0); returns global face/edge index.
    """
    label = "face" if kind == "face" else "edge"
    query = "get_component_faces" if kind == "face" else "get_component_edges"
    work: Sequence[FaceRef | EdgeRef] = (
        [e for e in pool if e.kind == filter_kind] if filter_kind else list(pool)
    )
    if filter_kind and coord_m is None:
        if index < 0 or index >= len(work):
            raise fail(
                "INVALID_ARGUMENT",
                f"Component {component!r} has no {filter_kind} {label} at index {index}",
                f"Use {query} with kind={filter_kind!r}",
                component=component,
                index=index,
                kind=filter_kind,
            )
        return work[index].index
    if coord_m is None:
        if index < 0 or index >= len(work):
            raise fail(
                "INVALID_ARGUMENT",
                f"Component {component!r} has no {label} at index {index}",
                f"Use {query}; valid range 0..{max(len(work) - 1, 0)}",
                component=component,
                index=index,
            )
        return index
    hit = resolve(Ref(index, *coord_m), work)
    return hit.entity.index


_GeomT = TypeVar("_GeomT", FaceRef, EdgeRef)


def filter_by_kind(
    items: Sequence[_GeomT],
    kind: str | None,
    *,
    allowed: frozenset[str],
    what: str,
) -> list[_GeomT]:
    """Kind filter for list_component_*; global index preserved. Bad kind → INVALID_ARGUMENT."""
    if not kind:
        return list(items)
    if kind not in allowed:
        raise fail(
            "INVALID_ARGUMENT",
            f"Unsupported {what} kind {kind!r}",
            f"Choose: {', '.join(sorted(allowed))}",
            kind=kind,
        )
    return [e for e in items if e.kind == kind]


def query_faces(
    items: Sequence[FaceRef],
    kind: str | None = None,
    query: str | None = None,
) -> list[FaceRef]:
    """Part get_faces kind + semantic query; global index preserved."""
    if query is not None and query not in FACE_QUERIES:
        raise fail(
            "INVALID_ARGUMENT",
            f"Unsupported face query {query!r}",
            f"Choose: {', '.join(sorted(FACE_QUERIES))}",
            query=query,
        )
    if query in FACE_QUERY_AXIS:
        if kind is not None and kind != "cylinder":
            raise fail(
                "INVALID_ARGUMENT",
                f"{query} applies only to cylindrical faces",
                "Omit kind or pass kind=cylinder",
                kind=kind,
            )
        kind = "cylinder"
    pool = filter_by_kind(items, kind, allowed=FACE_FILTER_KINDS, what="face")
    if query is None:
        return pool
    if query in FACE_QUERY_AXIS:
        ax = FACE_QUERY_AXIS[query]
        out: list[FaceRef] = []
        for f in pool:
            a = f.axis_m
            if a is None:
                continue
            if abs(a[ax]) >= _AXIS_ALIGN:
                out.append(f)
        return out
    axis, maximize = FACE_QUERY_EXTREME[query]
    if not pool:
        return []
    target = max(f.centroid_m[axis] for f in pool) if maximize else min(f.centroid_m[axis] for f in pool)
    return [f for f in pool if abs(f.centroid_m[axis] - target) <= 1e-9]
