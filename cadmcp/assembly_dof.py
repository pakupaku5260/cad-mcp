"""Heuristic assembly DOF estimate (F17). Pure logic — no COM/dispatch/backend.

This is a lower-bound / heuristic estimate, **not** a SolidWorks DOF solver.
Overconstraint, redundancy, and constraint coupling are not modeled.
"""
from __future__ import annotations

from typing import Any

from cadmcp.result import VerificationCheck
from cadmcp.verification import build_task_verification

# Heuristic constrained-DOF weights per mate type (not a true constraint solver).
MATE_DOF: dict[str, int] = {
    "coincident": 3,  # face coincident: 1 translation + 2 rotation
    "concentric": 4,  # axis concentric: 2 translation + 2 rotation
    "distance": 1,  # 1 translation
    "angle": 1,  # 1 rotation
    "tangent": 1,  # 1 translation
    "screw": 2,  # translation/rotation coupling (heuristic)
}

ASSUMPTIONS: tuple[str, ...] = (
    "heuristic, not a true SolidWorks DOF solver",
    "mate weights are independent lower-bound contributions; "
    "overconstraint, redundancy, and coupling are not modeled",
    "assembly_order uses component_enumeration_order "
    "(GetComponents / insert proxy), not a mate-graph topological order",
    "unmated_components is a coarse spanning-tree deficit "
    "(max(0, n_components - 1 - n_mates)); list_mates does not expose "
    "mate↔component links",
)

def estimate_dof(components: list[str], mates: list[dict]) -> dict[str, Any]:
    """Estimate remaining DOF from component count and mate-type heuristics."""
    n = len(components)
    total_dof = 6 * n
    constrained = 0
    unknown: list[str] = []
    annotated: list[dict[str, Any]] = []
    seen_unknown: set[str] = set()

    for raw in mates:
        name = str(raw.get("name") or "")
        mate_type = str(raw.get("mate_type") or "")
        weight = MATE_DOF.get(mate_type)
        if weight is None:
            if mate_type not in seen_unknown:
                seen_unknown.add(mate_type)
                unknown.append(mate_type)
            annotated.append(
                {"name": name, "mate_type": mate_type, "constrained_dof": None}
            )
        else:
            constrained += weight
            annotated.append(
                {"name": name, "mate_type": mate_type, "constrained_dof": weight}
            )

    remaining = max(0, total_dof - constrained)
    # Coarse proxy only: spanning-tree deficit when mate↔component edges are unavailable.
    unmated_components = max(0, n - 1 - len(mates)) if n else 0

    return {
        "total_dof": total_dof,
        "constrained": constrained,
        "remaining": remaining,
        "unmated_components": unmated_components,
        "basis": "mate_type_heuristic",
        "mates": annotated,
        "unknown_mate_types": unknown,
    }


def assembly_order(components: list[str]) -> dict[str, Any]:
    """Report component enumeration order (insertion / GetComponents proxy)."""
    return {
        "order": list(components),
        "basis": "component_enumeration_order",
    }


def _checks(
    components: list[str],
    mates: list[dict],
    unknown_mate_types: list[str],
) -> list[VerificationCheck]:
    n_comp = len(components)
    n_mates = len(mates)
    return [
        VerificationCheck(
            name="components_present",
            ok=n_comp >= 1,
            detail=f"component_count={n_comp}",
        ),
        VerificationCheck(
            name="mates_present",
            ok=n_mates >= 1,
            detail=f"mate_count={n_mates}",
        ),
        VerificationCheck(
            name="all_mate_types_known",
            ok=not unknown_mate_types,
            detail=(
                "all mate types known"
                if not unknown_mate_types
                else f"unknown: {unknown_mate_types}"
            ),
        ),
    ]


def assess(components: list[str], mates: list[dict]) -> dict[str, Any]:
    """Aggregate DOF estimate, order, verification checks, and assumptions."""
    dof = estimate_dof(components, mates)
    order = assembly_order(components)
    checks = _checks(components, mates, dof["unknown_mate_types"])
    verification = build_task_verification(checks)
    return {
        "status": "ok",
        "verification": verification.model_dump(),
        "dof_estimate": {
            "total_dof": dof["total_dof"],
            "constrained": dof["constrained"],
            "remaining": dof["remaining"],
            "unmated_components": dof["unmated_components"],
            "basis": dof["basis"],
        },
        "assembly_order": order,
        "mates": dof["mates"],
        "unknown_mate_types": dof["unknown_mate_types"],
        "assumptions": list(ASSUMPTIONS),
        "risk": "unverified",
    }


def not_applicable_payload(*, reason: str) -> dict[str, Any]:
    """Fixed-shape payload when the active document is not an assessable assembly."""
    verification = build_task_verification([])
    return {
        "status": "not_applicable",
        "verification": verification.model_dump(),
        "dof_estimate": {
            "total_dof": 0,
            "constrained": 0,
            "remaining": 0,
            "unmated_components": 0,
            "basis": "mate_type_heuristic",
        },
        "assembly_order": {"order": [], "basis": "component_enumeration_order"},
        "mates": [],
        "unknown_mate_types": [],
        "assumptions": list(ASSUMPTIONS) + [reason],
        "risk": "unverified",
    }


__all__ = [
    "ASSUMPTIONS",
    "MATE_DOF",
    "assembly_order",
    "assess",
    "estimate_dof",
    "not_applicable_payload",
]
