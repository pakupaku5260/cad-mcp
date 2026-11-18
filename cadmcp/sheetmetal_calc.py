"""Pure bend-allowance estimate from explicit K-factor parameters (F19).

No COM / dispatch / backend / executor. Values are SI meters; unit conversion
belongs in the tool layer. This is **not** a SolidWorks flat-pattern.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from cadmcp.result import VerificationCheck
from cadmcp.verification import build_task_verification

ASSUMPTIONS: tuple[str, ...] = (
    "formula estimate only; not a live SolidWorks unfold / flat-pattern",
    "K-factor commonly 0.3–0.5 for mild steel; caller supplies the value",
    "radius is the inside bend radius",
    "flat length ≈ sum of straight segments + total_bend_allowance "
    "(straight segments are not summed by this tool)",
)


@dataclass(frozen=True)
class BendCheck:
    name: str
    description: str


BEND_CHECKS: tuple[BendCheck, ...] = (
    BendCheck(
        name="thickness_positive",
        description="Sheet thickness must be > 0",
    ),
    BendCheck(
        name="k_factor_in_range",
        description="K-factor must satisfy 0 < k < 1",
    ),
    BendCheck(
        name="bends_nonempty",
        description="At least one bend must be supplied",
    ),
    BendCheck(
        name="angles_in_range",
        description="Each bend angle_deg must satisfy 0 < angle_deg ≤ 180",
    ),
    BendCheck(
        name="radii_nonnegative",
        description="Each bend radius must be ≥ 0",
    ),
    BendCheck(
        name="values_finite",
        description="thickness, k_factor, and every bend angle/radius must be finite",
    ),
)


def bend_allowance_m(angle_deg: float, radius_m: float, thickness_m: float, k_factor: float) -> float:
    """Neutral-axis bend allowance in meters: θ_rad × (R + K×T)."""
    return math.radians(angle_deg) * (radius_m + k_factor * thickness_m)


def _finite(value: float) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _as_bend_list(bends: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    if bends is None:
        return []
    out: list[dict[str, Any]] = []
    for item in bends:
        if isinstance(item, Mapping):
            out.append(dict(item))
    return out


def _run_checks(
    thickness: float,
    k_factor: float,
    bends: list[dict[str, Any]],
) -> list[VerificationCheck]:
    angles = [float(b.get("angle_deg", float("nan"))) for b in bends]
    radii = [float(b.get("radius", float("nan"))) for b in bends]

    finite_ok = (
        _finite(thickness)
        and _finite(k_factor)
        and all(_finite(a) for a in angles)
        and all(_finite(r) for r in radii)
    )
    # Empty bends: angles/radii vacuously true; bends_nonempty carries that failure.
    angles_ok = all(0.0 < a <= 180.0 for a in angles) if finite_ok else False
    radii_ok = all(r >= 0.0 for r in radii) if finite_ok else False

    return [
        VerificationCheck(
            name="thickness_positive",
            ok=_finite(thickness) and thickness > 0.0,
            detail=f"thickness={thickness}",
        ),
        VerificationCheck(
            name="k_factor_in_range",
            ok=_finite(k_factor) and 0.0 < k_factor < 1.0,
            detail=f"k_factor={k_factor}",
        ),
        VerificationCheck(
            name="bends_nonempty",
            ok=len(bends) >= 1,
            detail=f"bend_count={len(bends)}",
        ),
        VerificationCheck(
            name="angles_in_range",
            ok=angles_ok,
            detail=(
                "all angles in (0, 180]"
                if angles_ok
                else f"angles_deg={angles}"
            ),
        ),
        VerificationCheck(
            name="radii_nonnegative",
            ok=radii_ok,
            detail="all radii ≥ 0" if radii_ok else f"radii={radii}",
        ),
        VerificationCheck(
            name="values_finite",
            ok=finite_ok,
            detail="all numeric inputs finite" if finite_ok else "non-finite value present",
        ),
    ]


def evaluate(
    thickness: float,
    k_factor: float,
    bends: Sequence[Mapping[str, Any]] | None,
) -> tuple[list[VerificationCheck], list[dict[str, Any]]]:
    """Run six checks; compute BA rows only when every check passes (SI meters)."""
    bend_list = _as_bend_list(bends)
    checks = _run_checks(thickness, k_factor, bend_list)
    if not checks or not all(c.ok for c in checks):
        return checks, []

    allowances: list[dict[str, Any]] = []
    for i, bend in enumerate(bend_list):
        angle = float(bend["angle_deg"])
        radius = float(bend["radius"])
        ba = bend_allowance_m(angle, radius, thickness, k_factor)
        allowances.append(
            {
                "index": i,
                "angle_deg": angle,
                "radius": radius,
                "bend_allowance": ba,
            }
        )
    return checks, allowances


def assess(
    thickness: float,
    k_factor: float,
    bends: Sequence[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """Full SI payload for calc_bend_allowance (unit conversion is tool-layer)."""
    checks, allowances = evaluate(thickness, k_factor, bends)
    verification = build_task_verification(checks)
    total = sum(float(row["bend_allowance"]) for row in allowances) if allowances else 0.0
    return {
        "status": verification.status,
        "verification": verification.model_dump(),
        "bend_allowances": allowances,
        "total_bend_allowance": total,
        "unit": "m",
        "assumptions": list(ASSUMPTIONS),
        "risk": "unverified",
    }


__all__ = [
    "ASSUMPTIONS",
    "BEND_CHECKS",
    "BendCheck",
    "assess",
    "bend_allowance_m",
    "evaluate",
]
