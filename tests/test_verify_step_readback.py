"""P5-3: verify_step_readback Fake contracts."""
from __future__ import annotations

from pathlib import Path

from cadmcp.backend.fake.backend import FakeBackend
from cadmcp.kernel import Kernel
from cadmcp.toolsets.core import core_registry


def _step(ws: Path, name: str = "demo.step") -> Path:
    p = ws / name
    p.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n", encoding="utf-8")
    return p


def test_step_readback_multi_match(tmp_path: Path):
    b = FakeBackend()
    src = _step(tmp_path)
    bbox = (-3.5, -1.14, -1.4, 3.5, 1.015, 2.3)  # metres
    b.seed_step_import(src, part_count=3, bbox_m=bbox)
    k = Kernel(core_registry(), b, workspace=tmp_path)
    r = k.dispatch(
        "verify_step_readback",
        {
            "path": str(src),
            "expected_components": 3,
            "expected_bbox": [c * 1000 for c in bbox],
            "tolerance_mm": 1.0,
        },
    )
    assert r.ok, r.error
    assert r.result["part_count"] == 3
    assert r.result["all_match"] is True
    assert r.result["matches"]["components"] is True
    assert r.result["matches"]["bbox"] is True


def test_step_readback_count_mismatch(tmp_path: Path):
    b = FakeBackend()
    src = _step(tmp_path)
    b.seed_step_import(src, part_count=2, bbox_m=(0, 0, 0, 0.1, 0.1, 0.1))
    k = Kernel(core_registry(), b, workspace=tmp_path)
    r = k.dispatch(
        "verify_step_readback",
        {"path": str(src), "expected_components": 22},
    )
    assert r.ok, r.error
    assert r.result["part_count"] == 2
    assert r.result["matches"]["components"] is False
    assert r.result["all_match"] is False
    assert any("expected_components" in n for n in r.result["notes"])


def test_step_readback_bbox_over_tol(tmp_path: Path):
    b = FakeBackend()
    src = _step(tmp_path)
    b.seed_step_import(src, part_count=1, bbox_m=(0, 0, 0, 0.1, 0.1, 0.1))
    k = Kernel(core_registry(), b, workspace=tmp_path)
    r = k.dispatch(
        "verify_step_readback",
        {
            "path": str(src),
            "expected_bbox": [0, 0, 0, 200, 100, 100],  # mm — 100mm over on xmax
            "tolerance_mm": 1.0,
        },
    )
    assert r.ok, r.error
    assert r.result["matches"]["bbox"] is False
    assert r.result["all_match"] is False


def test_step_readback_single_part_notes(tmp_path: Path):
    b = FakeBackend()
    src = _step(tmp_path)
    # No seed → Fake opens STEP as empty part
    k = Kernel(core_registry(), b, workspace=tmp_path)
    r = k.dispatch("verify_step_readback", {"path": str(src), "expected_components": 22})
    assert r.ok, r.error
    assert r.result["part_count"] == 1
    assert r.result["matches"]["components"] is False
    assert any("single part" in n.lower() or "part_count=1" in n for n in r.result["notes"])
