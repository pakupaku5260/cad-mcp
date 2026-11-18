"""F2: verify_model tool — groups, thresholds, three counterexamples."""
from __future__ import annotations

from pathlib import Path

from cadmcp.backend.fake.backend import FakeBackend
from cadmcp.kernel import Kernel
from cadmcp.toolsets.core import core_registry


def _k(tmp_path: Path, **fake_kw) -> Kernel:
    return Kernel(core_registry(), FakeBackend(**fake_kw), workspace=tmp_path)


def _ok(k: Kernel, name: str, args: dict | None = None):
    r = k.dispatch(name, args or {})
    assert r.ok, f"{name}: {r.error}"
    return r


def _build_box(k: Kernel, size: float = 40.0, depth: float = 20.0) -> None:
    _ok(k, "new_part")
    _ok(k, "start_sketch", {"plane": "Front Plane"})
    _ok(k, "sketch_rectangle", {"x1": 0, "y1": 0, "x2": size, "y2": size})
    _ok(k, "end_sketch")
    _ok(k, "extrude", {"depth": depth})


def test_verify_model_registered_in_verification_toolset():
    reg = core_registry()
    spec = reg.get("verify_model")
    assert spec is not None
    assert spec.toolset == "verification"
    assert spec.mutating is False


def test_empty_body_counterexample(tmp_path: Path):
    k = _k(tmp_path)
    _ok(k, "new_part")
    r = _ok(k, "verify_model", {"groups": ["geometry"]})
    v = r.result["verification"]
    assert v["status"] == "failed"
    codes = [c.get("code") for c in v["checks"] if not c["ok"]]
    assert "VERIFY_EMPTY_BODY" in codes


def test_feature_error_counterexample(tmp_path: Path):
    k = _k(tmp_path, rebuild_errors=["Boss-Extrude1: simulated"])
    _build_box(k)
    r = _ok(k, "verify_model", {"groups": ["features"]})
    v = r.result["verification"]
    assert v["status"] == "failed"
    codes = [c.get("code") for c in v["checks"] if not c["ok"]]
    assert "VERIFY_FEATURE_ERROR" in codes


def test_hole_position_counterexample(tmp_path: Path):
    k = _k(tmp_path)
    _ok(k, "new_part")
    _ok(k, "start_sketch", {"plane": "Front Plane"})
    _ok(k, "sketch_circle", {"cx": 0, "cy": 0, "r": 5})
    _ok(k, "end_sketch")
    _ok(k, "extrude", {"depth": 10})
    # Expect hole far from real cylinder centroid → VERIFY_HOLE_POSITION
    r = _ok(
        k,
        "verify_model",
        {
            "groups": ["mass_bbox"],
            "thresholds": {"holes": [{"x": 200, "y": 200, "z": 200, "tol_mm": 0.1}]},
        },
    )
    v = r.result["verification"]
    assert v["status"] == "failed"
    codes = [c.get("code") for c in v["checks"] if not c["ok"]]
    assert "VERIFY_HOLE_POSITION" in codes


def test_healthy_part_verified(tmp_path: Path):
    k = _k(tmp_path)
    _build_box(k)
    r = _ok(k, "verify_model")
    assert r.result["doc_type"] == "part"
    assert r.result["verification"]["status"] == "verified"
    assert "assembly" in {s["group"] for s in r.result["skipped_groups"]}
    assert "drawing" in {s["group"] for s in r.result["skipped_groups"]}


def test_explicit_inapplicable_group_is_unverified_not_verified(tmp_path: Path):
    k = _k(tmp_path)
    _build_box(k)
    r = _ok(k, "verify_model", {"groups": ["drawing"]})
    assert r.result["groups_run"] == []
    assert r.result["skipped_groups"]
    assert r.result["verification"]["status"] == "unverified"


def test_groups_filter_features_only(tmp_path: Path):
    k = _k(tmp_path)
    _build_box(k)
    r = _ok(k, "verify_model", {"groups": ["features"]})
    names = [c["name"] for c in r.result["verification"]["checks"]]
    assert names == ["features.tree"]
    assert r.result["verification"]["status"] == "verified"
