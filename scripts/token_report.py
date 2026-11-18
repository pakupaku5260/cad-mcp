"""Tool-surface token report (F8 tiered budgets; wired in CI offline --strict).

Usage:
    python scripts/token_report.py
    python scripts/token_report.py --strict   # exit 1 on tier/headroom/profile/TOTAL breach
"""
from __future__ import annotations

import sys

from cadmcp.registry import (
    PROFILE_TOKEN_BUDGETS,
    TOOLSET_PROFILES,
    TOTAL_TOKEN_BUDGET,
    estimate_tokens,
    spec_tokens,
    toolset_budget,
    toolset_headroom_cap,
)
from cadmcp.resources.content import TOPICS
from cadmcp.toolsets.core import core_registry


def main(argv: list[str]) -> int:
    strict = "--strict" in argv
    specs = core_registry().all()

    groups: dict[str, list] = {}
    for spec in specs:
        groups.setdefault(spec.toolset, []).append(spec)

    print(
        f"{'toolset':14} {'tools':>5} {'tokens':>7} {'tier':>5} "
        f"{'cap20':>5} {'head%':>7}  status"
    )
    failures: list[str] = []
    total = 0
    for name, group in sorted(groups.items(), key=lambda kv: -sum(spec_tokens(s) for s in kv[1])):
        tokens = sum(spec_tokens(s) for s in group)
        total += tokens
        tier = toolset_budget(name)
        cap20 = toolset_headroom_cap(name)
        headroom_pct = (100.0 * (tier - tokens) / tier) if tier else 0.0
        status = "OK"
        if tokens > tier:
            status = "OVER_TIER"
            failures.append(f"{name}: {tokens} > tier {tier}")
        elif tokens > cap20:
            status = "NO_HEADROOM"
            failures.append(f"{name}: {tokens} > 20% cap {cap20} (tier {tier})")
        print(
            f"{name:14} {len(group):5} {tokens:7} {tier:5} {cap20:5} "
            f"{headroom_pct:6.1f}%  {status}"
        )
    print(f"{'TOTAL':14} {len(specs):5} {total:7}  (limit {TOTAL_TOKEN_BUDGET})")
    if total > TOTAL_TOKEN_BUDGET:
        failures.append(f"TOTAL {total} > {TOTAL_TOKEN_BUDGET}")

    print("\nprofile budgets:")
    for profile, toolsets in TOOLSET_PROFILES.items():
        tokens = sum(spec_tokens(s) for s in specs if s.toolset in toolsets)
        cap = PROFILE_TOKEN_BUDGETS.get(profile)
        if cap is None:
            print(f"  {profile:10} {tokens:6} tokens ({len(toolsets)} toolsets)  [warn-only]")
        else:
            ok = tokens <= cap
            print(
                f"  {profile:10} {tokens:6} / {cap:<5} tokens "
                f"({len(toolsets)} toolsets)  {'OK' if ok else 'OVER'}"
            )
            if not ok:
                failures.append(f"profile {profile}: {tokens} > {cap}")

    resource_tokens = sum(estimate_tokens(topic.text) for topic in TOPICS.values())
    print(f"\nresources body total: {resource_tokens} tokens (on-demand; usually not read in full)")

    if failures:
        print("\nbudget failures:", file=sys.stderr)
        for line in failures:
            print(f"  - {line}", file=sys.stderr)
    return 1 if strict and failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
