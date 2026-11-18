"""Structural fingerprints for cross-backend consistency comparison.

F7: optional ``numeric`` block (volume / bbox / key dimensions) via
``include_numeric=True``. Default path is byte-compatible with pre-F7 output.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from cadmcp.result import OpResult

# --- F7 numeric whitelist (locked in Phase 9 Step 0) ---

NUMERIC_RESULT_KEYS: frozenset[str] = frozenset({
    "volume",
    "surface_area",
    "mass_kg",
    "center_of_mass",
    "bbox",
    "depth",
    "radius",
    "thickness",
    "length",
    "width",
    "k_factor",
    "angle_deg",
})

NUMERIC_DELTA_AFTER_KEYS: frozenset[str] = frozenset({
    "volume_mm3",
    "surface_area_mm2",
    "mass_kg",
    "bbox_mm",
})

DEFAULT_RTOL = 1e-6
DEFAULT_ATOL = 1e-9


def structural_fingerprint(
    results: Sequence[tuple[str, OpResult]],
    *,
    include_numeric: bool = False,
) -> dict:
    """Structural fingerprint; optionally attach per-step numeric whitelist values."""
    return {
        "steps": [
            _step_fingerprint(name, r, include_numeric=include_numeric) for name, r in results
        ]
    }


def _step_fingerprint(name: str, r: OpResult, *, include_numeric: bool) -> dict:
    step = {
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
    if include_numeric:
        step["numeric"] = extract_numeric(r)
    return step


def extract_numeric(r: OpResult) -> dict[str, Any] | None:
    """Pull whitelisted numeric leaves from result and delta.after; None if empty."""
    result_block: dict[str, Any] = {}
    if isinstance(r.result, dict):
        for key in sorted(NUMERIC_RESULT_KEYS):
            if key not in r.result:
                continue
            coerced = _coerce_numeric_value(r.result[key])
            if coerced is not None:
                result_block[key] = coerced

    delta_block: dict[str, Any] = {}
    if r.delta is not None:
        after = r.delta.after.model_dump()
        for key in sorted(NUMERIC_DELTA_AFTER_KEYS):
            if key not in after or after[key] is None:
                continue
            coerced = _coerce_numeric_value(after[key])
            if coerced is not None:
                delta_block[key] = coerced

    out: dict[str, Any] = {}
    if result_block:
        out["result"] = result_block
    if delta_block:
        out["delta_after"] = delta_block
    return out or None


def _coerce_numeric_value(value: Any) -> float | list[float] | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, (list, tuple)) and value and all(
        isinstance(x, (int, float)) and not isinstance(x, bool) for x in value
    ):
        return [float(x) for x in value]
    return None


def values_close(
    a: Any,
    b: Any,
    *,
    rtol: float = DEFAULT_RTOL,
    atol: float = DEFAULT_ATOL,
) -> bool:
    """numpy.isclose-style comparison without numpy; lists compared element-wise."""
    if isinstance(a, (list, tuple)) or isinstance(b, (list, tuple)):
        if not isinstance(a, (list, tuple)) or not isinstance(b, (list, tuple)):
            return False
        if len(a) != len(b):
            return False
        return all(values_close(x, y, rtol=rtol, atol=atol) for x, y in zip(a, b, strict=True))
    try:
        fa = float(a)
        fb = float(b)
    except (TypeError, ValueError):
        return a == b
    return abs(fa - fb) <= atol + rtol * abs(fb)


def numeric_deviation(
    a: Any,
    b: Any,
) -> tuple[float, float]:
    """Return (max_abs_dev, max_rel_dev) over scalars / list leaves; (0,0) if equal shape fails."""
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)) and len(a) == len(b):
        abs_devs: list[float] = []
        rel_devs: list[float] = []
        for x, y in zip(a, b, strict=True):
            ad, rd = numeric_deviation(x, y)
            abs_devs.append(ad)
            rel_devs.append(rd)
        return (max(abs_devs) if abs_devs else 0.0, max(rel_devs) if rel_devs else 0.0)
    try:
        fa = float(a)
        fb = float(b)
    except (TypeError, ValueError):
        return (float("inf"), float("inf"))
    abs_dev = abs(fa - fb)
    rel_dev = abs_dev / abs(fb) if fb != 0 else (0.0 if fa == 0 else float("inf"))
    return abs_dev, rel_dev


def diff_fingerprints(
    expected: dict,
    actual: dict,
    *,
    rtol: float = DEFAULT_RTOL,
    atol: float = DEFAULT_ATOL,
) -> list[str]:
    """Field-wise diff; empty list means match.

    Structural keys use exact equality. ``numeric`` is compared with tolerance only when
    **both** sides present; absence on either side is ignored (old-fingerprint compat).
    """
    diffs: list[str] = []
    exp_steps = expected.get("steps", [])
    act_steps = actual.get("steps", [])
    if len(exp_steps) != len(act_steps):
        diffs.append(f"step count: golden {len(exp_steps)}, actual {len(act_steps)}")
    for i, (e, a) in enumerate(zip(exp_steps, act_steps, strict=False)):
        tool = e.get("tool", f"#{i}")
        keys = sorted((set(e) | set(a)) - {"numeric"})
        for key in keys:
            if e.get(key) != a.get(key):
                diffs.append(
                    f"step {i + 1} ({tool}) {key}: golden {e.get(key)!r}, actual {a.get(key)!r}"
                )
        if "numeric" in e and "numeric" in a:
            diffs.extend(
                _diff_numeric(
                    e.get("numeric"),
                    a.get("numeric"),
                    step_label=f"step {i + 1} ({tool})",
                    rtol=rtol,
                    atol=atol,
                )
            )
    return diffs


def _diff_numeric(
    expected: Any,
    actual: Any,
    *,
    step_label: str,
    rtol: float,
    atol: float,
) -> list[str]:
    if expected is None and actual is None:
        return []
    if expected is None or actual is None:
        return [f"{step_label} numeric: golden {expected!r}, actual {actual!r}"]
    if not isinstance(expected, Mapping) or not isinstance(actual, Mapping):
        return [f"{step_label} numeric: type mismatch golden={type(expected)} actual={type(actual)}"]
    diffs: list[str] = []
    for block in sorted(set(expected) | set(actual)):
        ev = expected.get(block)
        av = actual.get(block)
        if ev is None and av is None:
            continue
        if not isinstance(ev, Mapping) or not isinstance(av, Mapping):
            if ev != av:
                diffs.append(f"{step_label} numeric.{block}: golden {ev!r}, actual {av!r}")
            continue
        for key in sorted(set(ev) | set(av)):
            left, right = ev.get(key), av.get(key)
            if left is None and right is None:
                continue
            if left is None or right is None or not values_close(left, right, rtol=rtol, atol=atol):
                diffs.append(
                    f"{step_label} numeric.{block}.{key}: golden {left!r}, actual {right!r}"
                )
    return diffs


def iter_numeric_leaves(numeric: Mapping[str, Any] | None) -> list[tuple[str, Any]]:
    """Flatten numeric block to (path, value) leaves for precision stats."""
    if not numeric:
        return []
    out: list[tuple[str, Any]] = []
    for block, payload in numeric.items():
        if not isinstance(payload, Mapping):
            continue
        for key, value in payload.items():
            out.append((f"{block}.{key}", value))
    return out
