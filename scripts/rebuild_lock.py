"""
Rebuild baseline.lock (when baseline files exist but lock is missing).

Usage:
    python scripts/rebuild_lock.py

Scans all baseline files under cadmcp/backend/ and writes baseline.lock.

"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "cadmcp" / "backend"
LOCK_FILE = BACKEND / "baseline.lock"

# Files to lock (v1.2.2 §12.4)
LOCKED_FILES = [
    "api_baseline_s0.json",
    "migration_scope.yaml",
    "com_sequence_baseline.yaml",
    "com_objects_whitelist.yaml",
]


def main() -> int:
    files = {}
    missing = []
    for name in LOCKED_FILES:
        path = BACKEND / name
        if not path.exists():
            missing.append(name)
            continue
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        files[name] = sha

    if missing:
        print("The following files are missing; cannot lock:")
        for m in missing:
            print(f"  - {m}")
        print()
        print("Run the script that generates the corresponding baseline first.")
        return 1

    if LOCK_FILE.exists():
        print("baseline.lock already exists.")
        print("  To rebuild (overwrites the old lock), delete it first:")
        print(f"    Remove-Item {LOCK_FILE}")
        return 1

    LOCK_FILE.write_text(
        json.dumps({"files": files}, indent=2),
        encoding="utf-8",
    )
    print(f"Rebuilt {LOCK_FILE}")
    for name, sha in files.items():
        print(f"  {name}: {sha[:16]}...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
