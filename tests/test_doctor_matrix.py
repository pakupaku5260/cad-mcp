"""F20: doctor JSON matrix interpretation (no live doctor / health)."""
from __future__ import annotations

from pathlib import Path

from cadmcp.backend.fake import FakeBackend
from cadmcp.doctor_matrix import ASSUMPTIONS, DOCTOR_CHECKS, assess, evaluate_matrix
from cadmcp.kernel import Kernel
from cadmcp.toolsets.core import core_registry
from cadmcp.units import UnitContext


def _kernel(tmp_path: Path) -> Kernel:
    return Kernel(
        backend=FakeBackend(),
        units=UnitContext("mm"),
        workspace=tmp_path,
        registry=core_registry(),
    )


def _healthy(**overrides) -> dict:
    report = {
        "ok": True,
        "cadmcp_version": "0.3.0",
        "python": "3.12.0",
        "platform": "Windows-AMD64",
        "workspace": "C:/workspace",
        "backend": {
            "kind": "fake",
            "available": True,
            "revision": "33.0",
            "error": None,
            "mbd_step242": True,
        },
        "executor": {
            "state": "IDLE",
            "backend_ready": True,
            "blocker": None,
            "queue_depth": 0,
            "pending_mutating": 0,
            "thread_alive": True,
        },
        "registry": {"tools": 10, "toolsets": {"core": 1}},
        "notes": ["n1"],
    }
    report.update(overrides)
    return report


def test_doctor_checks_count_and_ids():
    assert len(DOCTOR_CHECKS) == 14
    assert [c.id for c in DOCTOR_CHECKS] == [
        "env.python",
        "env.platform",
        "env.workspace",
        "version.cadmcp_version",
        "backend.available",
        "backend.revision",
        "backend.mbd_step242",
        "backend.error",
        "executor.backend_ready",
        "executor.not_stuck",
        "executor.no_blocker",
        "registry.tools",
        "registry.toolsets",
        "notes",
    ]
    assert {c.severity for c in DOCTOR_CHECKS} <= {"blocker", "warning", "info"}


def test_healthy_report_verified():
    checks, skipped, matrix = evaluate_matrix(_healthy())
    assert skipped == []
    assert all(c.ok for c in checks)
    assert len(checks) == 14
    assert all(row["status"] == "ok" for row in matrix)
    payload = assess(_healthy())
    assert set(payload) == {
        "status",
        "verification",
        "checks_run",
        "skipped",
        "matrix",
        "assumptions",
        "risk",
    }
    assert payload["status"] == "verified"
    assert payload["risk"] == "unverified"
    assert payload["assumptions"] == list(ASSUMPTIONS)
    assert payload["checks_run"] == [c.id for c in DOCTOR_CHECKS]


def test_fail_backend_available_and_stuck():
    report = _healthy()
    report["backend"]["available"] = False
    report["executor"]["state"] = "STUCK"
    checks, skipped, matrix = evaluate_matrix(report)
    assert skipped == []
    by_name = {c.name: c for c in checks}
    assert by_name["backend.available"].ok is False
    assert by_name["executor.not_stuck"].ok is False
    assert assess(report)["status"] == "failed"
    fail_ids = {row["id"] for row in matrix if row["status"] == "fail"}
    assert "backend.available" in fail_ids
    assert "executor.not_stuck" in fail_ids


def test_fail_backend_error_nonempty():
    report = _healthy()
    report["backend"]["error"] = "COM_LOST: gone"
    checks, _, _ = evaluate_matrix(report)
    assert next(c for c in checks if c.name == "backend.error").ok is False


def test_fail_registry_empty_and_blocker_false():
    report = _healthy()
    report["registry"] = {"tools": 0, "toolsets": {}}
    report["executor"]["blocker"] = False
    checks, _, _ = evaluate_matrix(report)
    by_name = {c.name: c for c in checks}
    assert by_name["registry.tools"].ok is False
    assert by_name["registry.toolsets"].ok is False
    assert by_name["executor.no_blocker"].ok is False  # must be None, not False


def test_skip_missing_fields():
    report = {
        "python": "3.12.0",
        "platform": "Windows-AMD64",
        "workspace": "C:/ws",
        "cadmcp_version": "0.3.0",
        "backend": {"available": True, "revision": "33.0", "error": None},
        # no mbd_step242, no executor, no registry, no notes
    }
    checks, skipped, matrix = evaluate_matrix(report)
    skip_names = {s["name"] for s in skipped}
    assert "backend.mbd_step242" in skip_names
    assert "executor.backend_ready" in skip_names
    assert "executor.not_stuck" in skip_names
    assert "executor.no_blocker" in skip_names
    assert "registry.tools" in skip_names
    assert "registry.toolsets" in skip_names
    assert "notes" in skip_names
    assert all(s["reason"].startswith("missing field") for s in skipped)
    assert {row["id"] for row in matrix if row["status"] == "skip"} == skip_names
    # Skipped rows are not failed Verification checks.
    assert all(c.name not in skip_names for c in checks)


def test_severity_does_not_change_verification():
    """A failed info-severity row still flips Verification to failed (severity unused)."""
    report = _healthy()
    report["backend"]["mbd_step242"] = False  # severity=info
    payload = assess(report)
    assert payload["status"] == "failed"
    row = next(r for r in payload["matrix"] if r["id"] == "backend.mbd_step242")
    assert row["severity"] == "info"
    assert row["status"] == "fail"


def test_dotted_path_lookup():
    report = _healthy()
    checks, _, _ = evaluate_matrix(report)
    rev = next(c for c in checks if c.name == "backend.revision")
    assert rev.ok and "33.0" in rev.detail


def test_tool_readonly_payload_and_no_overlap(tmp_path: Path):
    k = _kernel(tmp_path)
    before = k.state_version
    result = k.dispatch("check_doctor_matrix", {"report": _healthy()})
    assert result.ok
    assert k.state_version == before
    assert set(result.result) == {
        "status",
        "verification",
        "checks_run",
        "skipped",
        "matrix",
        "assumptions",
        "risk",
    }
    assert result.result["status"] == "verified"
    assert "report" not in result.result
    # Does not invoke health/status or doctor CLI — pure interpret.
    assert any("does not run doctor" in a for a in result.result["assumptions"])
    assert any("not a live /health" in a for a in result.result["assumptions"])


def test_failed_matrix_keeps_outer_ok(tmp_path: Path):
    k = _kernel(tmp_path)
    bad = _healthy()
    bad["backend"]["available"] = False
    result = k.dispatch("check_doctor_matrix", {"report": bad})
    assert result.ok
    assert result.result["status"] == "failed"


def test_invalid_report_type(tmp_path: Path):
    k = _kernel(tmp_path)
    result = k.dispatch("check_doctor_matrix", {"report": "not-an-object"})
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "INVALID_ARGUMENT"
