"""Task-level verification: fills Verification envelope from Delta / RebuildReport / export files.

Semantics (wave 7 VERIFY):
- No runnable checks → unverified (never default to verified)
- Any check fails → failed (does not change OpResult.ok)
- All pass with at least one check → verified
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from cadmcp.result import (
    Delta,
    RebuildReport,
    Verification,
    VerificationCheck,
    VerificationEvidence,
)


def build_mutation_verification(
    *,
    delta: Delta | None,
    rebuild: RebuildReport | None,
) -> Verification:
    checks: list[VerificationCheck] = []
    if rebuild is not None:
        detail = "rebuild ok" if rebuild.ok else "; ".join(rebuild.feature_errors) or "rebuild failed"
        checks.append(VerificationCheck(name="rebuild", ok=rebuild.ok, detail=detail))
    if delta is not None:
        checks.append(
            VerificationCheck(
                name="delta",
                ok=True,
                detail=f"changed={list(delta.changed)}",
            )
        )
    return _finalize(checks, [])


def attach_file_evidence(
    verification: Verification | None,
    path: Path | str,
    *,
    check_name: str = "export_file",
) -> Verification:
    """Attach sha256 evidence for export paths; missing file fails that check."""
    p = Path(path)
    checks = list(verification.checks) if verification else []
    evidence = list(verification.evidence) if verification else []
    if p.is_file():
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        evidence.append(VerificationEvidence(path=str(p), sha256=digest))
        checks.append(
            VerificationCheck(name=check_name, ok=True, detail=f"sha256={digest[:12]}…")
        )
    else:
        checks.append(
            VerificationCheck(name=check_name, ok=False, detail=f"missing file: {p}")
        )
    return _finalize(checks, evidence)


def build_task_verification(checks: list[VerificationCheck],
                            evidence: list[VerificationEvidence] | None = None) -> Verification:
    return _finalize(list(checks), list(evidence or []))


def _finalize(
    checks: list[VerificationCheck],
    evidence: list[VerificationEvidence],
) -> Verification:
    if not checks:
        return Verification(status="unverified", checks=[], evidence=evidence)
    if all(c.ok for c in checks):
        return Verification(status="verified", checks=checks, evidence=evidence)
    return Verification(status="failed", checks=checks, evidence=evidence)


__all__ = [
    "attach_file_evidence",
    "build_mutation_verification",
    "build_task_verification",
]
