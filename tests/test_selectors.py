"""
Selector v1 (W7): Four behavioral rules for two-handle parsing (§9) – index precision, nearest neighbor degeneration,
0 hit the nearest distance, side by side is ambiguous. Pure logic, independent of kernel/fake.
"""

from __future__ import annotations

import pytest

from cadmcp.backend.protocol.models import EdgeRef, FaceRef
from cadmcp.errors import CadMcpError
from cadmcp.selectors import (
    COORD_EPS_M,
    FACE_FILTER_KINDS,
    TOL_EXACT_M,
    TOL_NEAR_M,
    Ref,
    filter_by_kind,
    resolve,
    resolve_mate_index,
)
from cadmcp.units import UnitContext

_MM = UnitContext("mm")

# Two faces 50mm apart + one edge (at y = 50)
FACES = [
    FaceRef(index=0, kind="plane", centroid_m=(0.0, 0.0, 0.0)),
    FaceRef(index=1, kind="plane", centroid_m=(_MM.to_m(50.0), 0.0, 0.0)),
]
EDGES = [EdgeRef(index=0, kind="line", midpoint_m=(0.0, _MM.to_m(50.0), 0.0))]


# ---------- Tolerance semantics (true machine calibration point, value via UnitContext) ----------


def test_tolerances_from_unit_context():
    assert TOL_EXACT_M == pytest.approx(_MM.to_m(0.5))
    assert TOL_NEAR_M == pytest.approx(_MM.to_m(2.0))
    assert COORD_EPS_M < TOL_EXACT_M < TOL_NEAR_M


# ---------- Rule 1: Exact index matching (coordinates must be ipsilateral tolerance) ----------


def test_exact_hit_within_half_mm():
    ref = Ref(index=0, x=0.0, y=_MM.to_m(0.4), z=0.0)  # offset 0.4mm ≤ 0.5mm
    r = resolve(ref, FACES)
    assert r.quality == "exact" and r.entity.index == 0
    assert r.distance_m == pytest.approx(_MM.to_m(0.4))


def test_exact_requires_coords_not_just_index():
    ref = Ref(index=0, x=_MM.to_m(1.0), y=0.0, z=0.0)  # index matches but coords off by 1mm
    r = resolve(ref, FACES)
    assert r.quality == "proximity"  # nearest-neighbor fallback, not false "exact"
    assert r.entity.index == 0


# ---------- Rule 2: index expired → nearest neighbor degradation (return current handle) ------------


def test_stale_index_falls_back_to_nearest():
    ref = Ref(index=99, x=_MM.to_m(50.0), y=0.0, z=0.0)  # handle index no longer exists
    r = resolve(ref, FACES)
    assert r.quality == "proximity"
    assert r.entity.index == 1 and r.entity is FACES[1]  # return entity from candidate pool


def test_zero_hit_reports_nearest_distance():
    ref = Ref(index=0, x=_MM.to_m(100.0), y=0.0, z=0.0)  # nearest face is 50mm away
    with pytest.raises(CadMcpError) as e:
        resolve(ref, FACES)
    err = e.value
    assert err.code == "REF_NOT_FOUND"
    assert err.context["requested"] == 0
    assert err.context["distance_mm"] == pytest.approx(50.0)  # report nearest distance (§9)
    assert "mm" in err.message  # zero hits report nearest distance (§9)


def test_empty_pool_is_not_found():
    with pytest.raises(CadMcpError) as e:
        resolve(Ref(index=0, x=0.0, y=0.0, z=0.0), [])
    assert e.value.code == "REF_NOT_FOUND"


# ---------- Rule 3: Parallel → ambiguity error in the tolerance band, list candidates, never guess ----------


def test_tied_nearest_is_ambiguous_with_candidates():
    # Handle is in the middle on both sides: 0.5mm each, distance indistinguishable (≤ parallel threshold)→ ambiguity
    pool = (
        FACES[0],
        FaceRef(index=1, kind="plane", centroid_m=(_MM.to_m(1.0), 0.0, 0.0)),
    )
    ref = Ref(index=42, x=_MM.to_m(0.5), y=0.0, z=0.0)
    with pytest.raises(CadMcpError) as e:
        resolve(ref, pool)
    err = e.value
    assert err.code == "REF_AMBIGUOUS"
    assert err.context["candidates"] == [0, 1]
    assert "equally" in err.message.lower() and "disambiguate" in err.hint.lower()


def test_strict_nearest_wins_over_ambiguous_band():
    # Strictly sequential (0.2mm vs 0.8mm, all in 2mm band→) closest, no ambiguity
    pool = (
        FaceRef(index=0, kind="plane", centroid_m=(0.0, 0.0, 0.0)),
        FaceRef(index=1, kind="plane", centroid_m=(_MM.to_m(1.0), 0.0, 0.0)),
    )
    ref = Ref(index=77, x=_MM.to_m(0.2), y=0.0, z=0.0)
    r = resolve(ref, pool)
    assert r.quality == "proximity" and r.entity.index == 0
    assert r.distance_m == pytest.approx(_MM.to_m(0.2))


# ---------- Rule 4: The side pool is also parsed ----------


def test_edge_pool_resolves_by_midpoint():
    ref = Ref(index=0, x=0.0, y=_MM.to_m(50.0), z=0.0)
    r = resolve(ref, EDGES)
    assert r.quality == "exact"
    assert isinstance(r.entity, EdgeRef) and r.entity.kind == "line"


def test_filter_by_kind_keeps_global_index():
    pool = [
        FaceRef(index=0, kind="cylinder", centroid_m=(0.0, 0.0, 0.0)),
        FaceRef(index=1, kind="plane", centroid_m=(0.0, 0.0, 0.01)),
    ]
    only = filter_by_kind(pool, "plane", allowed=FACE_FILTER_KINDS, what="face")
    assert [f.index for f in only] == [1]
    idx = resolve_mate_index(0, None, pool, component="p-1", kind="face", filter_kind="cylinder")
    assert idx == 0
