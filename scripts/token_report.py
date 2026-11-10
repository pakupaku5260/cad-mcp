"""Tool-surface token report (local gate; not wired in CI yet).

Usage:
    uv run python scripts/token_report.py
    uv run python scripts/token_report.py --strict   # exit 1 if any toolset over budget
"""
from __future__ import annotations

import sys

from cadmcp.registry import (
    DEFAULT_TOOLSET_BUDGET_TOKENS,
    TOOLSET_PROFILES,
    estimate_tokens,
    spec_tokens,
)
from cadmcp.resources.content import TOPICS
from cadmcp.toolsets.core import core_registry


def main(argv: list[str]) -> int:
    strict = "--strict" in argv
    specs = core_registry().all()

    groups: dict[str, list] = {}
    for spec in specs:
        groups.setdefault(spec.toolset, []).append(spec)

    print(f"{'toolset':14} {'tools':>5} {'tokens':>7} {'budget':>7}  status")
    over: list[str] = []
    total = 0
    for name, group in sorted(groups.items(), key=lambda kv: -sum(spec_tokens(s) for s in kv[1])):
        tokens = sum(spec_tokens(s) for s in group)
        total += tokens
        ok = tokens <= DEFAULT_TOOLSET_BUDGET_TOKENS
        if not ok:
            over.append(name)
        print(
            f"{name:14} {len(group):5} {tokens:7} {DEFAULT_TOOLSET_BUDGET_TOKENS:7}"
            f"  {'OK' if ok else 'OVER'}"
        )
    print(f"{'TOTAL':14} {len(specs):5} {total:7}")

    print("\nprofile budgets:")
    for profile, toolsets in TOOLSET_PROFILES.items():
        tokens = sum(spec_tokens(s) for s in specs if s.toolset in toolsets)
        print(f"  {profile:10} {tokens:6} tokens ({len(toolsets)} toolsets)")

    resource_tokens = sum(estimate_tokens(topic.text) for topic in TOPICS.values())
    print(f"\nresources body total: {resource_tokens} tokens (on-demand; usually not read in full)")

    if over:
        print(f"\ntoolsets over budget: {', '.join(over)}", file=sys.stderr)
    return 1 if strict and over else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
