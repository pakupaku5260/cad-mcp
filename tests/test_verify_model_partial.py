"""P5-1: verify_model partial_on_timeout + max_retries."""
from __future__ import annotations

from pathlib import Path

from cadmcp.backend.fake.backend import FakeBackend
from cadmcp.kernel import Kernel
from cadmcp.toolsets.core import core_registry


def _k(tmp: Path, **kw) -> tuple[Kernel, FakeBackend]:
    b = FakeBackend(**kw)
    return Kernel(core_registry(), b, workspace=tmp), b


def _box(k: Kernel) -> None:
    assert k.dispatch("new_part", {}).ok
    assert k.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert k.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 40, "y2": 40}).ok
    assert k.dispatch("end_sketch", {}).ok
    assert k.dispatch("extrude", {"depth": 20}).ok


def test_verify_model_all_pass_additive_fields(tmp_path: Path):
    k, _b = _k(tmp_path)
    _box(k)
    r = k.dispatch("verify_model", {"groups": ["geometry", "features"]})
    assert r.ok, r.error
    assert r.result["partial"] is False
    assert r.result["completed_groups"] == ["geometry", "features"]
    assert r.result["incomplete_groups"] == []
    assert r.result["retries"] == []
    assert r.result["verification"]["status"] == "verified"


def test_partial_on_timeout_continues_after_group_com_failure(tmp_path: Path):
    # Inject COM_CALL_FAILED on next force_rebuild (features group) after build.
    k, b = _k(tmp_path)
    _box(k)
    n = b._counts.get("force_rebuild", 0)
    b._fail_on.add(("force_rebuild", n + 1))
    r = k.dispatch(
        "verify_model",
        {
            "groups": ["features", "geometry"],
            "partial_on_timeout": True,
            "max_retries": 0,
        },
    )
    assert r.ok, r.error
    assert r.result["partial"] is True
    assert "geometry" in r.result["completed_groups"]
    assert any(g["group"] == "features" for g in r.result["incomplete_groups"])
    codes = [c.get("code") for c in r.result["verification"]["checks"] if not c["ok"]]
    assert "COM_CALL_FAILED" in codes
    # Partial conclusion is not a verified pass
    assert r.result["verification"]["status"] != "verified"


def test_default_partial_false_still_raises(tmp_path: Path):
    k, b = _k(tmp_path)
    _box(k)
    n = b._counts.get("force_rebuild", 0)
    b._fail_on.add(("force_rebuild", n + 1))
    r = k.dispatch("verify_model", {"groups": ["features"], "partial_on_timeout": False})
    assert not r.ok
    assert r.error is not None
    assert r.error.code == "COM_CALL_FAILED"


def test_retries_recover_then_pass(tmp_path: Path):
    # First force_rebuild fails; second succeeds (max_retries=1).
    k, b = _k(tmp_path)
    _box(k)
    n = b._counts.get("force_rebuild", 0)
    b._fail_on.add(("force_rebuild", n + 1))
    r = k.dispatch(
        "verify_model",
        {"groups": ["features"], "partial_on_timeout": True, "max_retries": 1},
    )
    assert r.ok, r.error
    assert r.result["partial"] is False
    assert r.result["completed_groups"] == ["features"]
    assert r.result["retries"]
    assert r.result["retries"][0]["count"] == 1
    assert r.result["verification"]["status"] == "verified"


def test_retries_not_used_for_verify_failure(tmp_path: Path):
    k, _b = _k(tmp_path, rebuild_errors=["Boss: bad"])
    _box(k)
    r = k.dispatch(
        "verify_model",
        {"groups": ["features"], "partial_on_timeout": True, "max_retries": 2},
    )
    assert r.ok, r.error
    assert r.result["retries"] == []
    codes = [c.get("code") for c in r.result["verification"]["checks"] if not c["ok"]]
    assert "VERIFY_FEATURE_ERROR" in codes


def test_max_retries_illegal_clamped(tmp_path: Path):
    k, _b = _k(tmp_path)
    _box(k)
    r = k.dispatch("verify_model", {"groups": ["geometry"], "max_retries": 99})
    assert r.ok, r.error
    assert r.result.get("warnings")
    assert "max_retries" in r.result["warnings"][0]


def test_retry_cap_exhausted_stays_incomplete(tmp_path: Path):
    k, b = _k(tmp_path)
    _box(k)
    n = b._counts.get("force_rebuild", 0)
    b._fail_on.update(
        {("force_rebuild", n + 1), ("force_rebuild", n + 2), ("force_rebuild", n + 3)}
    )
    r = k.dispatch(
        "verify_model",
        {"groups": ["features"], "partial_on_timeout": True, "max_retries": 2},
    )
    assert r.ok, r.error
    assert r.result["partial"] is True
    assert r.result["incomplete_groups"]
    assert r.result["retries"][0]["count"] == 2
