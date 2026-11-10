"""Fake backend · call log + fault injection (S8a).

`enter(calls, counts, fail_on, tool, **args)`: log call, bump count, inject per fail_on.
Pure functions, no `self` (section 4.6).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from cadmcp.errors import SideEffect, fail


def enter(
    calls: list[tuple[str, dict]],
    counts: dict[str, int],
    fail_on: set[tuple[str, int]],
    tool: str,
    **args: Any,
) -> None:
    """Record one call; if `(tool, nth)` hits fail_on, raise COM_CALL_FAILED.

    - `calls`: call log (including failed/injected attempts) for test assertions
    - `counts`: `tool -> call count`
    - `fail_on`: `{(tool, nth)}`, fail on nth call
    """
    clean = {k: (str(v) if isinstance(v, Path) else v) for k, v in args.items()}
    calls.append((tool, clean))
    counts[tool] = counts.get(tool, 0) + 1
    if (tool, counts[tool]) in fail_on:
        raise fail(
            "COM_CALL_FAILED",
            f"Injected fault: {tool} call #{counts[tool]} blocked by fail_on (not executed)",
            "Read model state (e.g. get_mass_properties) to confirm no side effects, then decide whether to retry",
            side_effect=SideEffect.APPLIED,
            injected=True,
            method=tool,
        )
        