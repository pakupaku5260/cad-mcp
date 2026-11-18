"""Single-job batch executor (F13): serial tool calls with step/duration limits.

Pure orchestration — no COM, no executor changes, no nested batch, no write queue.
Outer OpResult.ok stays true when steps fail (same pattern as replay_recipe / design_run).
"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Protocol

from cadmcp.errors import fail
from cadmcp.registry import ToolRegistry
from cadmcp.result import OpResult

DispatchFn = Callable[[str, dict | None], OpResult]


class _BatchEnv(Protocol):
    dispatch: DispatchFn
    registry: ToolRegistry | None


def precheck_steps(
    steps: list[Any],
    registry: ToolRegistry,
    *,
    max_steps: int,
) -> list[dict[str, Any]]:
    """Validate steps without dispatch. Raises CadMcpError on any precheck failure."""
    if not isinstance(steps, list) or not steps:
        raise fail(
            "INVALID_ARGUMENT",
            "batch.steps must be a non-empty array",
            'Pass [{"tool": "new_part", "args": {}}, ...]',
        )
    if len(steps) > max_steps:
        raise fail(
            "BATCH_LIMIT_EXCEEDED",
            f"batch.steps has {len(steps)} entries; max_steps={max_steps}",
            "Split the job or raise max_steps (hard cap 50)",
        )
    known = set(registry.names())
    prepared: list[dict[str, Any]] = []
    for i, raw in enumerate(steps):
        prefix = f"batch.steps[{i}]"
        if not isinstance(raw, dict):
            raise fail(
                "INVALID_ARGUMENT",
                f"{prefix} must be an object",
                'Use {"tool": "...", "args": {...}}',
            )
        tool = raw.get("tool")
        if not isinstance(tool, str) or not tool.strip():
            raise fail(
                "INVALID_ARGUMENT",
                f"{prefix}.tool must be a non-empty string",
                "Call tools/list for available tools",
            )
        tool = tool.strip()
        if tool == "batch":
            raise fail(
                "INVALID_ARGUMENT",
                f"{prefix}: nested batch is not allowed",
                "Flatten steps into a single batch call",
            )
        if tool not in known:
            raise fail(
                "INVALID_ARGUMENT",
                f"{prefix}: unknown tool {tool!r}",
                "Call tools/list for available tools",
                tool=tool,
            )
        args = raw.get("args", {})
        if args is None:
            args = {}
        if not isinstance(args, dict):
            raise fail(
                "INVALID_ARGUMENT",
                f"{prefix}.args must be an object",
                'Pass args as a JSON object, e.g. {"depth": 10}',
            )
        prepared.append({"tool": tool, "args": dict(args)})
    return prepared


def run_batch(
    env: _BatchEnv,
    steps: list[Any],
    *,
    stop_on_error: bool = True,
    max_steps: int = 50,
    max_duration_s: float = 600,
) -> dict[str, Any]:
    """Precheck → serial dispatch with inter-step duration checks."""
    if env.registry is None:
        raise fail(
            "INTERNAL_ERROR",
            "batch requires ctx.registry",
            "Server defect; Kernel must bind registry on OpContext",
        )
    if env.dispatch is None:
        raise fail(
            "INTERNAL_ERROR",
            "batch requires ctx.dispatch",
            "Server defect; Kernel must bind dispatch on OpContext",
        )

    cap_steps = int(max_steps)
    if cap_steps < 1:
        raise fail(
            "INVALID_ARGUMENT",
            "max_steps must be >= 1",
            "Use max_steps between 1 and 50",
        )
    # Schema hard-caps at 50; clamp defensive callers.
    if cap_steps > 50:
        cap_steps = 50
    duration_cap = float(max_duration_s)
    if duration_cap <= 0:
        raise fail(
            "INVALID_ARGUMENT",
            "max_duration_s must be > 0",
            "Pass a positive duration in seconds",
        )

    prepared = precheck_steps(steps, env.registry, max_steps=cap_steps)
    started = time.monotonic()
    recorded: list[dict[str, Any]] = []
    failed: dict[str, Any] | None = None
    payload_error: str | None = None
    aborted = False

    for i, step in enumerate(prepared):
        if aborted:
            break
        elapsed = time.monotonic() - started
        if elapsed > duration_cap:
            failed = {
                "index": i,
                "tool": step["tool"],
                "error_code": "BATCH_LIMIT_EXCEEDED",
            }
            payload_error = "BATCH_LIMIT_EXCEEDED"
            aborted = True
            break

        result = env.dispatch(step["tool"], dict(step["args"]))
        entry: dict[str, Any] = {
            "index": i,
            "tool": step["tool"],
            "ok": result.ok,
            "error_code": result.error.code if result.error else None,
            "result_keys": sorted(result.result) if result.result else None,
            "delta_changed": sorted(result.delta.changed) if result.delta else None,
            "state_version": result.state_version,
        }
        recorded.append(entry)
        if not result.ok and failed is None:
            failed = {
                "index": i,
                "tool": step["tool"],
                "error_code": entry["error_code"],
            }
            if i == 0:
                payload_error = entry["error_code"]
            else:
                payload_error = "BATCH_PARTIAL_FAILURE"
            if stop_on_error:
                aborted = True

    elapsed_s = round(time.monotonic() - started, 3)
    return {
        "ok": failed is None,
        "count": len(recorded),
        "steps": recorded,
        "failed_step": failed,
        "error_code": payload_error,
        "elapsed_s": elapsed_s,
        "limits": {"max_steps": cap_steps, "max_duration_s": duration_cap},
    }


__all__ = [
    "precheck_steps",
    "run_batch",
]
