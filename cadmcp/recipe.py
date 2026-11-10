"""Design recipe replay (wave 7 RECIPE): ordered tool calls + per-step asserts, no branches/loops.

Recipes only allow registered tool names; args use the same jsonschema (Kernel.dispatch).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cadmcp.errors import fail
from cadmcp.kernel import Kernel
from cadmcp.result import OpResult


def load_recipe(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise fail("PATH_NOT_FOUND", f"Recipe not found: {path}", "Ensure path is in workspace and readable")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise fail(
            "INVALID_ARGUMENT",
            f"Invalid recipe JSON: {exc}",
            "Check JSON syntax",
        ) from exc
    if not isinstance(data, dict):
        raise fail("INVALID_ARGUMENT", "Recipe root must be an object", 'Use {"name", "steps":[...]}')
    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        raise fail("INVALID_ARGUMENT", "Recipe steps must be a non-empty array", "Add at least one tool call")
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            raise fail("INVALID_ARGUMENT", f"steps[{i}] must be an object", "Each step has tool / args")
        if not isinstance(step.get("tool"), str) or not step["tool"].strip():
            raise fail("INVALID_ARGUMENT", f"steps[{i}] missing tool", "tool must be a registered tool name")
        args = step.get("args", {})
        if args is None:
            step["args"] = {}
        elif not isinstance(args, dict):
            raise fail("INVALID_ARGUMENT", f"steps[{i}].args must be an object", "Use a JSON object")
        assertion = step.get("assert")
        if assertion is not None and not isinstance(assertion, dict):
            raise fail("INVALID_ARGUMENT", f"steps[{i}].assert must be an object", "Omit or pass an object")
    return data


def _check_assert(step_index: int, assertion: dict[str, Any], result: OpResult) -> str | None:
    """Return failure reason; None means pass."""
    if "ok" in assertion and bool(assertion["ok"]) != result.ok:
        return f"ok expected {assertion['ok']!r} got {result.ok!r}"
    if "error_code" in assertion:
        code = result.error.code if result.error else None
        if code != assertion["error_code"]:
            return f"error_code expected {assertion['error_code']!r} got {code!r}"
    if "result_keys" in assertion:
        expected = set(assertion["result_keys"])
        actual = set(result.result or {})
        missing = sorted(expected - actual)
        if missing:
            return f"result_keys missing {missing}"
    if "delta_changed" in assertion:
        expected = set(assertion["delta_changed"])
        actual = set(result.delta.changed) if result.delta else set()
        if expected != actual:
            return f"delta_changed expected {sorted(expected)} got {sorted(actual)}"
    return None


def replay_recipe(kernel: Kernel, recipe: dict[str, Any]) -> dict[str, Any]:
    """Run recipe in order; return step report. Unknown tools → INVALID_ARGUMENT from Kernel."""
    reports: list[dict[str, Any]] = []
    failed_step: int | None = None
    for i, step in enumerate(recipe["steps"]):
        tool = str(step["tool"])
        args = dict(step.get("args") or {})
        result = kernel.dispatch(tool, args)
        entry: dict[str, Any] = {
            "step": i,
            "tool": tool,
            "ok": result.ok,
            "error_code": result.error.code if result.error else None,
            "result_keys": sorted(result.result) if result.result else None,
            "delta_changed": sorted(result.delta.changed) if result.delta else None,
            "state_version": result.state_version,
        }
        assertion = step.get("assert")
        if isinstance(assertion, dict) and assertion:
            reason = _check_assert(i, assertion, result)
            entry["assert_ok"] = reason is None
            if reason is not None:
                entry["assert_detail"] = reason
                failed_step = i if failed_step is None else failed_step
        reports.append(entry)
        # Tool failure without assert expecting failure → mark failed step for debugging
        if not result.ok and failed_step is None:
            if not (isinstance(assertion, dict) and assertion.get("ok") is False):
                failed_step = i

    return {
        "name": recipe.get("name"),
        "steps": reports,
        "ok": failed_step is None,
        "failed_step": failed_step,
    }


def compare_replays(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    """Compare whether two replays have the same delta.changed trajectory."""
    diffs: list[str] = []
    sa, sb = a.get("steps") or [], b.get("steps") or []
    if len(sa) != len(sb):
        diffs.append(f"step count differs: {len(sa)} vs {len(sb)}")
    for i, (x, y) in enumerate(zip(sa, sb, strict=False)):
        if x.get("delta_changed") != y.get("delta_changed"):
            diffs.append(
                f"step {i} delta_changed: {x.get('delta_changed')} vs {y.get('delta_changed')}"
            )
        if x.get("ok") != y.get("ok") or x.get("error_code") != y.get("error_code"):
            diffs.append(f"step {i} ok/code mismatch")
    return diffs


__all__ = ["compare_replays", "load_recipe", "replay_recipe"]
