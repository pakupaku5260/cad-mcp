"""In-process task ledger for design_run / batch (F14).

Responsibility: record start/finish of synchronous task-layer tool calls so
``task_status`` / ``task_list`` can query recent jobs.
Does not: persist to disk, start threads, call backend/executor, or cancel jobs.
Boundary: process-local FIFO of at most 100 entries; job ids are monotonic ints.
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import UTC, datetime
from typing import Any

from cadmcp.errors import CadMcpError

_KEEP = 100
_next_id = 1
_jobs: OrderedDict[int, dict[str, Any]] = OrderedDict()


def _now() -> str:
    """UTC timestamp; tests may monkeypatch this symbol."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def start(tool: str) -> int:
    """Register a running job; return a new monotonic job_id."""
    global _next_id
    job_id = _next_id
    _next_id += 1
    _jobs[job_id] = {
        "job_id": job_id,
        "tool": tool,
        "state": "running",
        "ok": None,
        "error_code": None,
        "started_at": _now(),
        "finished_at": None,
        "step_count": 0,
    }
    _prune()
    return job_id


def finish(
    job_id: int,
    payload: dict[str, Any] | None = None,
    *,
    state: str = "done",
    error_code: str | None = None,
) -> None:
    """Complete a job. Exception paths pass ``state='failed'`` and an error_code."""
    entry = _jobs.get(job_id)
    if entry is None:
        return
    if payload is None:
        # No payload means the handler raised; every such path is a failure.
        entry["state"] = "failed"
        entry["ok"] = False
        entry["error_code"] = error_code
        entry["step_count"] = 0
    else:
        entry["state"] = "done"
        entry["ok"] = bool(payload.get("ok", True))
        steps = payload.get("steps")
        entry["step_count"] = len(steps) if isinstance(steps, list) else int(
            payload.get("count") or 0
        )
        code = error_code
        if code is None:
            code = payload.get("error_code")
        if code is None:
            failed = payload.get("failed_step")
            if isinstance(failed, dict):
                code = failed.get("error_code")
        entry["error_code"] = code
    entry["finished_at"] = _now()


def logged(tool: str, fn):
    """Run a task handler with ledger start/finish; re-raise after recording failure."""
    job_id = start(tool)
    try:
        payload = fn()
    except CadMcpError as exc:
        finish(job_id, None, state="failed", error_code=exc.code)
        raise
    except Exception:
        finish(job_id, None, state="failed", error_code="INTERNAL_ERROR")
        raise
    finish(job_id, payload)
    return payload


def get(job_id: int) -> dict[str, Any] | None:
    """Return a shallow copy of one job, or None if unknown / pruned."""
    entry = _jobs.get(int(job_id))
    return dict(entry) if entry is not None else None


def list_jobs(*, limit: int = 20, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
    """Return (page copies, total). Order is insertion order (oldest first)."""
    from cadmcp.toolsets.paging import paginate

    rows = [dict(v) for v in _jobs.values()]
    total = len(rows)
    page, _start = paginate(rows, int(limit), int(offset))
    return page, total


def _prune() -> None:
    while len(_jobs) > _KEEP:
        _jobs.popitem(last=False)


def reset_for_tests() -> None:
    """Clear ledger state (unit tests only)."""
    global _next_id
    _jobs.clear()
    _next_id = 1


__all__ = [
    "finish",
    "get",
    "list_jobs",
    "logged",
    "reset_for_tests",
    "start",
]
