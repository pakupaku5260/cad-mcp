"""Interpret an existing ``cadmcp doctor`` JSON report (F20).

Pure logic — no COM / Executor / backend / dispatch. Does **not** run doctor or
live probes; missing fields are skipped (not failed).
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from cadmcp.result import VerificationCheck
from cadmcp.verification import build_task_verification

Severity = Literal["blocker", "warning", "info"]
MatrixStatus = Literal["ok", "fail", "skip"]

ASSUMPTIONS: tuple[str, ...] = (
    "interprets an existing cadmcp doctor JSON report; does not run doctor, "
    "Executor, backend, or live probes",
    "missing source_path fields are skipped (not failed)",
    "severity is metadata only and does not change Verification status",
    "not a live /health or status(executor) check",
)


@dataclass(frozen=True)
class DoctorCheckDef:
    id: str
    category: str
    source_path: str
    pass_condition: str
    severity: Severity
    remediation: str
    predicate: Callable[[Any], bool]


def _get_path(report: Mapping[str, Any], path: str) -> tuple[bool, Any]:
    """Return (found, value) for a dotted path; found=False if any segment missing."""
    cur: Any = report
    for part in path.split("."):
        if not isinstance(cur, Mapping) or part not in cur:
            return False, None
        cur = cur[part]
    return True, cur


def _nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) >= 1
    return True


def _is_true(value: Any) -> bool:
    return value is True


def _error_empty(value: Any) -> bool:
    return value is None or value == ""


def _not_stuck(value: Any) -> bool:
    return value != "STUCK"


def _blocker_none(value: Any) -> bool:
    return value is None


def _count_ge_1(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return value >= 1
    if isinstance(value, Mapping):
        return len(value) >= 1
    if isinstance(value, (list, tuple, set)):
        return len(value) >= 1
    return False


def _exists(_value: Any) -> bool:
    return True


DOCTOR_CHECKS: tuple[DoctorCheckDef, ...] = (
    DoctorCheckDef(
        id="env.python",
        category="env",
        source_path="python",
        pass_condition="nonempty",
        severity="blocker",
        remediation="Run doctor on a supported Python 3.11+ interpreter",
        predicate=_nonempty,
    ),
    DoctorCheckDef(
        id="env.platform",
        category="env",
        source_path="platform",
        pass_condition="nonempty",
        severity="info",
        remediation="Re-run doctor; platform string should be system-machine",
        predicate=_nonempty,
    ),
    DoctorCheckDef(
        id="env.workspace",
        category="env",
        source_path="workspace",
        pass_condition="nonempty",
        severity="warning",
        remediation="Pass --workspace or rely on the default output root",
        predicate=_nonempty,
    ),
    DoctorCheckDef(
        id="version.cadmcp_version",
        category="version",
        source_path="cadmcp_version",
        pass_condition="nonempty",
        severity="info",
        remediation="Reinstall cadmcp so __version__ is present",
        predicate=_nonempty,
    ),
    DoctorCheckDef(
        id="backend.available",
        category="backend",
        source_path="backend.available",
        pass_condition="eq:True",
        severity="blocker",
        remediation="Start SolidWorks or use --backend fake; fix backend.error",
        predicate=_is_true,
    ),
    DoctorCheckDef(
        id="backend.revision",
        category="backend",
        source_path="backend.revision",
        pass_condition="nonempty",
        severity="warning",
        remediation="Ensure the backend reports a revision string",
        predicate=_nonempty,
    ),
    DoctorCheckDef(
        id="backend.mbd_step242",
        category="backend",
        source_path="backend.mbd_step242",
        pass_condition="eq:True",
        severity="info",
        remediation="MBD STEP242 unavailable on this backend; expected on SW builds",
        predicate=_is_true,
    ),
    DoctorCheckDef(
        id="backend.error",
        category="backend",
        source_path="backend.error",
        pass_condition="empty",
        severity="blocker",
        remediation="Clear backend.error (attach/start failure) and re-run doctor",
        predicate=_error_empty,
    ),
    DoctorCheckDef(
        id="executor.backend_ready",
        category="executor",
        source_path="executor.backend_ready",
        pass_condition="eq:True",
        severity="blocker",
        remediation="Executor backend not ready; check doctor executor section",
        predicate=_is_true,
    ),
    DoctorCheckDef(
        id="executor.not_stuck",
        category="executor",
        source_path="executor.state",
        pass_condition="ne:STUCK",
        severity="blocker",
        remediation="Clear STUCK state (modal dialog / hung tool) then re-run doctor",
        predicate=_not_stuck,
    ),
    DoctorCheckDef(
        id="executor.no_blocker",
        category="executor",
        source_path="executor.blocker",
        pass_condition="is_none",
        severity="warning",
        remediation="Dismiss modal dialogs so doctor reports blocker=null",
        predicate=_blocker_none,
    ),
    DoctorCheckDef(
        id="registry.tools",
        category="registry",
        source_path="registry.tools",
        pass_condition="gte:1",
        severity="blocker",
        remediation="Registry empty — check install and toolset registration",
        predicate=_count_ge_1,
    ),
    DoctorCheckDef(
        id="registry.toolsets",
        category="registry",
        source_path="registry.toolsets",
        pass_condition="gte:1",
        severity="blocker",
        remediation="No toolsets registered — check core_registry()",
        predicate=_count_ge_1,
    ),
    DoctorCheckDef(
        id="notes",
        category="notes",
        source_path="notes",
        pass_condition="exists",
        severity="info",
        remediation="Doctor report should include a notes array",
        predicate=_exists,
    ),
)


def evaluate_matrix(
    report: Mapping[str, Any],
) -> tuple[list[VerificationCheck], list[dict[str, str]], list[dict[str, Any]]]:
    """Run the 14-row matrix; return (checks, skipped, matrix rows)."""
    checks: list[VerificationCheck] = []
    skipped: list[dict[str, str]] = []
    matrix: list[dict[str, Any]] = []

    for item in DOCTOR_CHECKS:
        found, value = _get_path(report, item.source_path)
        if not found:
            reason = f"missing field {item.source_path}"
            skipped.append({"name": item.id, "reason": reason})
            matrix.append(
                {
                    "id": item.id,
                    "category": item.category,
                    "severity": item.severity,
                    "status": "skip",
                    "detail": reason,
                }
            )
            continue

        ok = bool(item.predicate(value))
        detail = f"{item.source_path}={value!r}"
        checks.append(VerificationCheck(name=item.id, ok=ok, detail=detail))
        matrix.append(
            {
                "id": item.id,
                "category": item.category,
                "severity": item.severity,
                "status": "ok" if ok else "fail",
                "detail": detail,
            }
        )

    return checks, skipped, matrix


def assess(report: Mapping[str, Any]) -> dict[str, Any]:
    """Full payload for check_doctor_matrix."""
    checks, skipped, matrix = evaluate_matrix(report)
    verification = build_task_verification(checks)
    return {
        "status": verification.status,
        "verification": verification.model_dump(),
        "checks_run": [c.id for c in DOCTOR_CHECKS],
        "skipped": skipped,
        "matrix": matrix,
        "assumptions": list(ASSUMPTIONS),
        "risk": "unverified",
    }


__all__ = [
    "ASSUMPTIONS",
    "DOCTOR_CHECKS",
    "DoctorCheckDef",
    "assess",
    "evaluate_matrix",
]
