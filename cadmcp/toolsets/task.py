"""Task toolset: batch execution + in-process job queries (F13/F14)."""
from __future__ import annotations

from cadmcp import task_ledger as ledger
from cadmcp.batch import run_batch
from cadmcp.errors import fail
from cadmcp.kernel import OpContext
from cadmcp.registry import ToolSpec, make_schema

_BATCH_DESCRIPTION = (
    "Run a serial batch of ordinary tool calls in one request (task layer; "
    "synchronous — no cancel/priority/lock/async). "
    "steps is a non-empty array of {tool, args} (same shape as recipes); "
    "nested batch is rejected. "
    "Precheck is zero-side-effect: unknown tool, empty steps, or len(steps) > "
    "max_steps raises before any dispatch (over-limit → BATCH_LIMIT_EXCEEDED). "
    "During execution, max_duration_s is checked only between steps (never "
    "interrupts an in-flight COM call); overtime stops with BATCH_LIMIT_EXCEEDED. "
    "stop_on_error=true (default) halts after the first failed step; false "
    "continues and keeps the first failure in failed_step. "
    "Outer OpResult.ok stays true when steps fail (same as replay_recipe); "
    "inspect payload ok / failed_step / error_code. "
    "error_code is the first step's real code when index 0 fails, else "
    "BATCH_PARTIAL_FAILURE when a later step fails. "
    "Returns {ok, count, steps, failed_step, error_code, elapsed_s, "
    "limits:{max_steps,max_duration_s}}. Help: cadmcp://help/task_layer "
    "(help topic)."
)

_STATUS_DESCRIPTION = (
    "Look up one in-process task job by job_id (task layer; synchronous — "
    "no cancel/priority/lock/async). Returns {job_id, tool, state, ok, "
    "error_code, started_at, finished_at, step_count}. Unknown id → "
    "INVALID_ARGUMENT. Help: cadmcp://help/task_layer (help topic)."
)

_LIST_DESCRIPTION = (
    "List recent in-process task jobs (task layer; synchronous — no "
    "cancel/priority/lock/async). Oldest first; paginate with limit/offset. "
    "Returns {tasks, total, offset}. Help: cadmcp://help/task_layer "
    "(help topic)."
)


def batch(
    ctx: OpContext,
    steps: list,
    stop_on_error: bool = True,
    max_steps: int = 50,
    max_duration_s: float = 600,
) -> dict:
    """Serial multi-tool job (mutating; expect_* injected by registry)."""

    def _call() -> dict:
        return run_batch(
            ctx,
            steps,
            stop_on_error=bool(stop_on_error),
            max_steps=int(max_steps),
            max_duration_s=float(max_duration_s),
        )

    return ledger.logged("batch", _call)


def task_status(ctx: OpContext, job_id: int) -> dict:
    """Read one ledger entry (bypass_queue; not mutating)."""
    entry = ledger.get(int(job_id))
    if entry is None:
        raise fail(
            "INVALID_ARGUMENT",
            f"Unknown job_id {job_id}",
            "Call task_list to see recent jobs (in-process only)",
        )
    return entry


def task_list(ctx: OpContext, limit: int = 20, offset: int = 0) -> dict:
    """Paginated ledger listing (bypass_queue; not mutating)."""
    page, total = ledger.list_jobs(limit=int(limit), offset=int(offset))
    return {"tasks": page, "total": total, "offset": int(offset)}


BATCH_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="batch",
        toolset="task",
        description=_BATCH_DESCRIPTION,
        input_schema=make_schema(
            {
                "steps": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 50,
                    "description": (
                        "Ordered tool calls: [{tool, args}, ...]. Nested batch forbidden."
                    ),
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["tool"],
                        "properties": {
                            "tool": {"type": "string"},
                            "args": {"type": "object"},
                        },
                    },
                },
                "stop_on_error": {
                    "type": "boolean",
                    "default": True,
                    "description": (
                        "If true (default), stop after the first failed step. "
                        "If false, continue and keep the first failure in failed_step."
                    ),
                },
                "max_steps": {
                    "type": "integer",
                    "default": 50,
                    "minimum": 1,
                    "maximum": 50,
                    "description": "Hard cap on steps length (precheck; default 50).",
                },
                "max_duration_s": {
                    "type": "number",
                    "default": 600,
                    "exclusiveMinimum": 0,
                    "description": (
                        "Wall-clock budget in seconds; checked between steps only "
                        "(default 600)."
                    ),
                },
            },
            ["steps"],
        ),
        handler=batch,
        mutating=True,
        timeout_class="slow",
        layer="task",
    ),
    ToolSpec(
        name="task_status",
        toolset="task",
        description=_STATUS_DESCRIPTION,
        input_schema=make_schema(
            {
                "job_id": {
                    "type": "integer",
                    "description": "In-process job id from a prior design_run/batch.",
                },
            },
            ["job_id"],
        ),
        handler=task_status,
        mutating=False,
        bypass_queue=True,
        timeout_class="fast",
        layer="task",
    ),
    ToolSpec(
        name="task_list",
        toolset="task",
        description=_LIST_DESCRIPTION,
        input_schema=make_schema(
            {
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 0,
                    "description": "Max rows to return (default 20).",
                },
                "offset": {
                    "type": "integer",
                    "default": 0,
                    "minimum": 0,
                    "description": "Rows to skip (default 0).",
                },
            },
        ),
        handler=task_list,
        mutating=False,
        bypass_queue=True,
        timeout_class="fast",
        layer="task",
    ),
]

__all__ = ["BATCH_SPECS", "batch", "task_list", "task_status"]
