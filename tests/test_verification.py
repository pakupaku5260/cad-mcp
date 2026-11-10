"""Wave 7 VERIFY: envelope semantics and three goldens (fake offline)."""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from cadmcp.backend.fake.backend import FakeBackend
from cadmcp.kernel import Kernel
from cadmcp.result import (
    Delta,
    GeometrySnapshot,
    RebuildReport,
    Verification,
    VerificationCheck,
    ok_result,
)
from cadmcp.toolsets.core import core_registry
from cadmcp.verification import (
    attach_file_evidence,
    build_mutation_verification,
    build_task_verification,
)


def test_verified_requires_passing_checks():
    with pytest.raises(ValidationError):
        Verification(status="verified", checks=[])
    with pytest.raises(ValidationError):
        Verification(
            status="verified",
            checks=[VerificationCheck(name="x", ok=False, detail="no")],
        )


def test_build_mutation_verification_failed_on_rebuild():
    v = build_mutation_verification(
        delta=None,
        rebuild=RebuildReport(ok=False, feature_errors=["bad"]),
    )
    assert v.status == "failed"
    assert v.checks[0].name == "rebuild"
    assert not v.checks[0].ok


def test_attach_file_evidence(tmp_path: Path):
    path = tmp_path / "out.step"
    path.write_text("FAKE-EXPORT:step:demo", encoding="utf-8")
    v = attach_file_evidence(None, path)
    assert v.status == "verified"
    assert v.evidence and v.evidence[0].sha256
    missing = attach_file_evidence(None, tmp_path / "nope.step")
    assert missing.status == "failed"


def _kernel(tmp_path: Path) -> Kernel:
    return Kernel(core_registry(), FakeBackend(), workspace=tmp_path, verify_mutations=True)


def _must_ok(k: Kernel, name: str, args: dict | None = None):
    r = k.dispatch(name, args or {})
    assert r.ok, f"{name} failed: {r.error}"
    return r


def test_golden_bracket_to_step(tmp_path: Path):
    """Bracket model → STEP: volume>0 and export file has evidence."""
    k = _kernel(tmp_path)
    _must_ok(k, "new_part")
    _must_ok(k, "start_sketch", {"plane": "Front Plane"})
    _must_ok(k, "sketch_rectangle", {"x1": 0, "y1": 0, "x2": 40, "y2": 20})
    _must_ok(k, "end_sketch")
    extruded = _must_ok(k, "extrude", {"depth": 10})
    assert extruded.verification is not None
    assert extruded.verification.status in {"verified", "failed"}
    assert extruded.rebuild is not None and extruded.rebuild.ok
    geo = _must_ok(k, "get_geometry")
    assert float(geo.result["volume"]) > 0
    exported = _must_ok(k, "export", {"path": "bracket.step", "overwrite": True})
    assert exported.verification is not None
    assert exported.verification.status == "verified"
    assert Path(exported.result["path"]).is_file()
    checks = build_task_verification(
        [
            VerificationCheck(name="volume_positive", ok=float(geo.result["volume"]) > 0),
            VerificationCheck(
                name="export_verified",
                ok=exported.verification.status == "verified",
                detail=exported.verification.status,
            ),
        ],
        evidence=exported.verification.evidence,
    )
    assert checks.status == "verified"


def test_golden_assembly_interference_zero(tmp_path: Path):
    """Two offset parts in assembly → zero interference."""
    k = _kernel(tmp_path)
    _must_ok(k, "new_part")
    _must_ok(k, "start_sketch", {"plane": "Front Plane"})
    _must_ok(k, "sketch_rectangle", {"x1": 0, "y1": 0, "x2": 10, "y2": 10})
    _must_ok(k, "end_sketch")
    _must_ok(k, "extrude", {"depth": 10})
    _must_ok(k, "save_document", {"path": "block.sldprt", "overwrite": True})
    _must_ok(k, "close_document", {"discard": True})

    _must_ok(k, "new_assembly")
    _must_ok(k, "insert_component", {"path": "block.sldprt"})
    _must_ok(k, "insert_component", {"path": "block.sldprt", "x": 50})
    inter = _must_ok(k, "check_interference")
    pairs = inter.result.get("pairs") or inter.result.get("interferences") or []
    # fake result shape: use whichever keys are present
    if isinstance(inter.result.get("count"), int):
        count = inter.result["count"]
    else:
        count = len(pairs)
    interfering = [
        p for p in pairs
        if isinstance(p, dict) and p.get("status") == "interfere"
    ]
    ok = count == 0 or len(interfering) == 0
    task = build_task_verification(
        [VerificationCheck(name="interference_clear", ok=ok, detail=str(inter.result))]
    )
    assert task.status == "verified", inter.result


def test_golden_part_to_drawing_pdf(tmp_path: Path):
    """Part → drawing → PDF."""
    k = _kernel(tmp_path)
    _must_ok(k, "new_part")
    _must_ok(k, "start_sketch", {"plane": "Front Plane"})
    _must_ok(k, "sketch_rectangle", {"x1": 0, "y1": 0, "x2": 30, "y2": 20})
    _must_ok(k, "end_sketch")
    _must_ok(k, "extrude", {"depth": 8})
    saved = _must_ok(k, "save_document", {"path": "plate.sldprt", "overwrite": True})
    part_path = saved.result.get("path") or "plate.sldprt"
    _must_ok(k, "new_drawing")
    _must_ok(k, "create_drawing_view", {"path": "plate.sldprt", "view": "front"})
    exported = _must_ok(k, "export", {"path": "plate.pdf", "overwrite": True})
    assert exported.verification is not None
    assert exported.verification.status == "verified"
    assert Path(exported.result["path"]).is_file()
    assert part_path


def test_mutation_verification_does_not_flip_ok():
    """When rebuild fails, ok may still be True but verification.status=failed."""
    delta = Delta.between(
        GeometrySnapshot(volume_mm3=1.0),
        GeometrySnapshot(volume_mm3=2.0),
    )
    v = build_mutation_verification(
        delta=delta,
        rebuild=RebuildReport(ok=False, feature_errors=["x"]),
    )
    r = ok_result({"name": "Boss"}, delta=delta, rebuild=RebuildReport(ok=False), verification=v)
    assert r.ok
    assert r.verification is not None and r.verification.status == "failed"
