"""Naming gate: the product is `cadmcp`, the SolidWorks backend is `solidworks`.

One internal consumer, no compatibility layer: any tracked file that still says
`swmcp` (or the old distribution name `solidworks-mcp`) must either be a
historical record listed below, or carry an explicit `naming-gate: allow-legacy`
marker on that line.

Scan is limited to `git ls-files` so untracked scratch files never trip the gate.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

LEGACY_TOKENS = ("swmcp", "solidworks-mcp")
MARKER = "naming-gate: allow-legacy"

# Historical records: frozen evidence, dated design docs, and handoff notes.
# They describe the past and must not be rewritten.
# migration_*.yaml: allow whole file so original: can keep pre-rename paths;
# live target: / planned_target: must still be cadmcp.* (verified separately).
ALLOWED_PREFIXES = (
    "cadmcp/backend/api_baseline_s0.json",
    "cadmcp/backend/migration_map.yaml",
    "cadmcp/backend/migration_scope.yaml",
    "docs/naming.md",  # documents the rename; must mention legacy tokens
    "docs/SolidWorks MCP",
    "docs/Win2019 ",
    "docs/backend-refactor-plan-v1.2.2.md",
    "docs/com_backend和fake_backend的拆分方案_v1.2.2完整版.txt",
    "docs/handoff/",
    "docs/2026-",
    "docs/参考项目研读笔记.md",
    "archive/",
    "deliverables/",
    "internal-evidence/",
    # This gate file necessarily names the forbidden tokens.
    "tests/architecture/test_naming.py",
)


def _tracked_files() -> list[str]:
    proc = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return [p for p in proc.stdout.split("\0") if p]


def _is_allowed(path: str) -> bool:
    return path.startswith(ALLOWED_PREFIXES)


def test_no_legacy_names_in_tracked_files() -> None:
    offenders: list[str] = []
    for rel in _tracked_files():
        if _is_allowed(rel):
            continue
        raw = (ROOT / rel).read_bytes()
        if b"\0" in raw:
            continue
        text = raw.decode("utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if MARKER in line:
                continue
            for token in LEGACY_TOKENS:
                if token in line:
                    offenders.append(f"{rel}:{lineno}: {token}: {line.strip()[:120]}")
                    break
    assert not offenders, "legacy product names found:\n" + "\n".join(offenders)
