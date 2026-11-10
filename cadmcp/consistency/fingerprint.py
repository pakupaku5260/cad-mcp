"""Structural fingerprints for cross-backend consistency comparison."""

from __future__ import annotations

from collections.abc import Sequence

from cadmcp.result import OpResult


def structural_fingerprint(results: Sequence[tuple[str, OpResult]]) -> dict:
    """Structural fingerprint: fields that should match across backends, no numeric values."""
    return {"steps": [_step_fingerprint(name, r) for name, r in results]}


def _step_fingerprint(name: str, r: OpResult) -> dict:
    return {
        "tool": name,
        "ok": r.ok,
        "error_code": r.error.code if r.error else None,
        "error_side_effect": r.error.side_effect.value if r.error else None,
        "result_keys": sorted(r.result) if r.result is not None else None,
        "delta_changed": sorted(r.delta.changed) if r.delta else None,
        "rebuild_ok": r.rebuild.ok if r.rebuild else None,
        "state_version": r.state_version,
        "warning_count": len(r.warnings),
    }


def diff_fingerprints(expected: dict, actual: dict) -> list[str]:
    """Field-wise diff; empty list means structural match."""
    diffs: list[str] = []
    exp_steps = expected.get("steps", [])
    act_steps = actual.get("steps", [])
    if len(exp_steps) != len(act_steps):
        diffs.append(f"step count: golden {len(exp_steps)}, actual {len(act_steps)}")
    for i, (e, a) in enumerate(zip(exp_steps, act_steps, strict=False)):
        tool = e.get("tool", f"#{i}")
        for key in sorted(set(e) | set(a)):
            if e.get(key) != a.get(key):
                diffs.append(
                    f"step {i + 1} ({tool}) {key}: golden {e.get(key)!r}, actual {a.get(key)!r}"
                )
    return diffs
