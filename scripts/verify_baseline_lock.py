"""Verify baseline file SHA256 matches baseline.lock.

Usage:
    python scripts/verify_baseline_lock.py

Exit codes:
    0 = pass (or lock missing, allowed to continue)
    1 = mismatch
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK_FILE = ROOT / "cadmcp/backend/baseline.lock"


def main() -> int:
    if not LOCK_FILE.exists():
        print("Baseline lock missing (allowed before S0).")
        return 0
    try:
        lock = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Cannot parse lock file: {exc}")
        return 1

    files = lock.get("files", {})
    if not files:
        print("Lock file empty; skipping.")
        return 0

    failed = False
    for rel, expected_sha in files.items():
        path = ROOT / "cadmcp/backend" / rel
        if not path.exists():
            print(f"Missing baseline file: {path}")
            failed = True
            continue
        actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_sha != expected_sha:
            print(f"Baseline modified: {rel}")
            print(f"  expected: {expected_sha}")
            print(f"  actual:   {actual_sha}")
            print("  For intentional changes, use a [baseline-change] PR.")
            failed = True
        else:
            print(f"OK {rel}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
