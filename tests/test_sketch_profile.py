"""Sketch profile conflict precheck (P4-1)."""

from __future__ import annotations

import pytest

from cadmcp.backend.protocol.models import SketchEntityRef
from cadmcp.backend.protocol.sketch_profile import (
    find_profile_conflicts,
    profiles_from_entities,
    raise_if_profile_conflicts,
)
from cadmcp.errors import CadMcpError


def _rect(i: int, x0: float, y0: float, x1: float, y1: float) -> SketchEntityRef:
    return SketchEntityRef(index=i, kind="rect", points_m=((x0, y0), (x1, y1)))


def _circ(i: int, cx: float, cy: float, r: float) -> SketchEntityRef:
    return SketchEntityRef(index=i, kind="circle", points_m=((cx, cy),), radius_m=r)


def test_disjoint_rects_ok():
    ents = [_rect(0, 0, 0, 0.01, 0.01), _rect(1, 0.02, 0.02, 0.03, 0.03)]
    assert find_profile_conflicts(profiles_from_entities(ents)) == []


def test_nested_rects_ok():
    ents = [_rect(0, 0, 0, 0.04, 0.04), _rect(1, 0.01, 0.01, 0.02, 0.02)]
    assert find_profile_conflicts(profiles_from_entities(ents)) == []


def test_overlapping_rects_conflict():
    ents = [_rect(0, 0, 0, 0.02, 0.02), _rect(1, 0.01, 0.01, 0.03, 0.03)]
    conflicts = find_profile_conflicts(profiles_from_entities(ents))
    assert len(conflicts) == 1


def test_shared_edge_rects_conflict():
    ents = [_rect(0, 0, 0, 0.01, 0.01), _rect(1, 0.01, 0, 0.02, 0.01)]
    assert find_profile_conflicts(profiles_from_entities(ents))


def test_rect_circle_intersect_conflict():
    ents = [_rect(0, 0, 0, 0.02, 0.02), _circ(1, 0.02, 0.01, 0.005)]
    assert find_profile_conflicts(profiles_from_entities(ents))


def test_concentric_circles_ok():
    ents = [_circ(0, 0, 0, 0.02), _circ(1, 0, 0, 0.01)]
    assert find_profile_conflicts(profiles_from_entities(ents)) == []


def test_intersecting_circles_conflict():
    ents = [_circ(0, 0, 0, 0.01), _circ(1, 0.015, 0, 0.01)]
    assert find_profile_conflicts(profiles_from_entities(ents))


def test_nested_nonintersect_circles_ok():
    ents = [_circ(0, 0, 0, 0.03), _circ(1, 0.005, 0, 0.005)]
    assert find_profile_conflicts(profiles_from_entities(ents)) == []


def test_raise_includes_context(kernel):
    assert kernel.dispatch("new_part", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch(
        "sketch_rectangle", {"x1": 0, "y1": 0, "x2": 20, "y2": 20}
    ).ok
    assert kernel.dispatch(
        "sketch_rectangle", {"x1": 10, "y1": 10, "x2": 30, "y2": 30}
    ).ok
    before = kernel.state_version
    r = kernel.dispatch("end_sketch", {})
    assert not r.ok and r.error.code == "SKETCH_PROFILE_CONFLICT"
    assert r.error.context.get("conflicts")
    assert "multiple" in r.error.hint.lower() or "Split" in r.error.hint or "拆" in r.error.hint
    assert kernel.state_version == before


def test_legal_nested_circle_end_sketch(kernel):
    assert kernel.dispatch("new_part", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 30}).ok
    assert kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 10}).ok
    r = kernel.dispatch("end_sketch", {})
    assert r.ok, r.error
    # No feature yet — extrude would still be fine for ring profile.
    assert kernel.state_version >= 1


def test_raise_if_profile_conflicts_side_effect_none():
    ents = [_rect(0, 0, 0, 1, 1), _rect(1, 0.5, 0.5, 1.5, 1.5)]
    with pytest.raises(CadMcpError) as ei:
        raise_if_profile_conflicts(ents)
    assert ei.value.code == "SKETCH_PROFILE_CONFLICT"
    assert ei.value.side_effect.value == "none"
