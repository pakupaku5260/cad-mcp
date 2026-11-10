"""Returns the envelope contract: ok/error invariant, geometric fingerprint Delta (W1-1)."""

import pytest
from pydantic import ValidationError

from cadmcp.errors import SideEffect, fail
from cadmcp.result import (
    Delta,
    GeometrySnapshot,
    OpResult,
    RebuildReport,
    fail_result,
    ok_result,
)

# ---- Success Path ----


def test_ok_result_shape():
    r = ok_result({"volume_mm3": 125000.0}, state_version=7)
    assert r.ok and r.error is None and r.state_version == 7
    assert r.delta is None and r.warnings == []
    assert r.result == {"volume_mm3": 125000.0}


def test_ok_result_requires_payload():
    with pytest.raises(ValidationError, match="result"):
        OpResult(ok=True)


# ----Failure Path----


def test_fail_result_shape_preserves_side_effect():
    err = fail(
        "REBUILD_FAILED", "重建后特征报错",
        "读取 rebuild.feature_errors 并修正尺寸",
        side_effect=SideEffect.APPLIED,
        feature_errors=["草图未闭合"],
    )
    r = fail_result(err, state_version=3)
    assert not r.ok and r.result is None
    assert r.error.code == "REBUILD_FAILED"
    assert r.error.side_effect is SideEffect.APPLIED
    assert r.error.context == {"feature_errors": ["草图未闭合"]}
    assert r.state_version == 3


def test_fail_result_requires_error():
    with pytest.raises(ValidationError, match="error"):
        OpResult(ok=False)


def test_fail_result_cannot_carry_payload():
    with pytest.raises(ValidationError, match="result"):
        OpResult(
            ok=False,
            result={"x": 1},
            error=fail("INTERNAL_ERROR", "m", "h").to_info(),
        )


# ---- Geometric Fingerprint Delta ----


def _snap(**kw) -> GeometrySnapshot:
    base = dict(volume_mm3=125000.0, surface_area_mm2=15000.0, mass_kg=0.125,
                face_count=6, edge_count=12)
    base.update(kw)
    return GeometrySnapshot(**base)


def test_identical_snapshots_yield_empty_delta():
    d = Delta.between(_snap(), _snap())
    assert d.changed == [] and d.identical


def test_volume_change_detected():
    d = Delta.between(_snap(), _snap(volume_mm3=130000.0))
    assert d.changed == ["volume_mm3"] and not d.identical


def test_topology_and_bbox_change_detected():
    d = Delta.between(
        _snap(bbox_mm=(-25.0, -25.0, 0.0, 25.0, 25.0, 50.0)),
        _snap(face_count=7, bbox_mm=(-25.0, -25.0, 0.0, 25.0, 25.0, 60.0)),
    )
    assert set(d.changed) == {"face_count", "bbox_mm"}


def test_none_to_value_counts_as_change():
    d = Delta.between(_snap(face_count=None), _snap(face_count=6))
    assert "face_count" in d.changed


def test_snapshot_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        GeometrySnapshot(volume_mm3=1.0, wat=2)


# ----Reconstruction Report----


def test_rebuild_report_defaults():
    rb = RebuildReport(ok=True)
    assert rb.feature_errors == []
