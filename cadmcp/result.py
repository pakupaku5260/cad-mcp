"""Return envelope: unified structure for tools, batch, and execution (v4 §10 W1-1).

Shape (final):
    {ok, result, error, delta, rebuild, verification, state_version, warnings}

Invariants (contract tests):
- ok=True  ⇔ error=None ⇔ result is not None
- ok=False ⇔ error is not None (partial progress in error.context, not result)
- delta is before/after geometry fingerprint—verification layer 2 and external change detection.
- verification failure does not change ok; never default unrun checks to verified.
"""
from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

from cadmcp.errors import CadMcpError, ErrorInfo


class GeometrySnapshot(BaseModel):
    """Geometry fingerprint snapshot (v4 §10); external units fixed to mm."""

    model_config = ConfigDict(extra="forbid")

    volume_mm3: float | None = None
    surface_area_mm2: float | None = None
    mass_kg: float | None = None
    face_count: int | None = None
    edge_count: int | None = None
    bbox_mm: tuple[float, float, float, float, float, float] | None = None  # xmin..zmax


def _same(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is b
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-6)


class Delta(BaseModel):
    """Before/after fingerprint diff: changed lists field names; empty = geometry unchanged."""

    model_config = ConfigDict(extra="forbid")

    before: GeometrySnapshot
    after: GeometrySnapshot
    changed: list[str]

    @classmethod
    def between(cls, before: GeometrySnapshot, after: GeometrySnapshot) -> Delta:
        changed: list[str] = []
        for name in GeometrySnapshot.model_fields:
            old = getattr(before, name)
            new = getattr(after, name)
            if isinstance(old, tuple) or isinstance(new, tuple):
                same = old is None and new is None or (
                    old is not None and new is not None and len(old) == len(new)
                    and all(_same(x, y) for x, y in zip(old, new, strict=True))
                )
            else:
                same = _same(old, new)
            if not same:
                changed.append(name)
        return cls(before=before, after=after, changed=changed)

    @property
    def identical(self) -> bool:
        return not self.changed


class RebuildReport(BaseModel):
    """Rebuild verification (layer 1); feature_errors are feature error descriptions."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    feature_errors: list[str] = []


class VerificationCheck(BaseModel):
    """Single task-level check."""

    model_config = ConfigDict(extra="forbid")

    name: str
    ok: bool
    detail: str = ""


class VerificationEvidence(BaseModel):
    """On-disk evidence (path + content hash) for export etc."""

    model_config = ConfigDict(extra="forbid")

    path: str
    sha256: str


class Verification(BaseModel):
    """Task-level verification envelope (wave 7 VERIFY). status=failed does not change OpResult.ok."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["verified", "unverified", "failed"]
    checks: list[VerificationCheck] = []
    evidence: list[VerificationEvidence] = []

    @model_validator(mode="after")
    def _verified_needs_passing_checks(self) -> Verification:
        if self.status == "verified":
            if not self.checks:
                raise ValueError("status=verified requires non-empty checks")
            if not all(c.ok for c in self.checks):
                raise ValueError("status=verified requires all checks ok")
        return self


class OpResult(BaseModel):
    """Unified return envelope."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    result: dict[str, Any] | None = None
    error: ErrorInfo | None = None
    delta: Delta | None = None
    rebuild: RebuildReport | None = None
    verification: Verification | None = None
    state_version: int | None = None
    warnings: list[str] = []

    @model_validator(mode="after")
    def _invariants(self) -> OpResult:
        if self.ok:
            if self.error is not None:
                raise ValueError("ok=True requires error=None")
            if self.result is None:
                raise ValueError("ok=True requires result non-None")
        else:
            if self.error is None:
                raise ValueError("ok=False requires error non-None")
            if self.result is not None:
                raise ValueError("ok=False requires result=None (partial progress in error.context)")
        return self


def ok_result(
    payload: dict[str, Any],
    *,
    delta: Delta | None = None,
    rebuild: RebuildReport | None = None,
    verification: Verification | None = None,
    state_version: int | None = None,
    warnings: list[str] | None = None,
) -> OpResult:
    return OpResult(
        ok=True,
        result=payload,
        delta=delta,
        rebuild=rebuild,
        verification=verification,
        state_version=state_version,
        warnings=warnings or [],
    )


def fail_result(
    err: CadMcpError | ErrorInfo,
    *,
    state_version: int | None = None,
    warnings: list[str] | None = None,
    verification: Verification | None = None,
) -> OpResult:
    info = err if isinstance(err, ErrorInfo) else err.to_info()
    return OpResult(
        ok=False,
        error=info,
        state_version=state_version,
        warnings=warnings or [],
        verification=verification,
    )
