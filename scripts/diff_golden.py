"""Output only the golden reference difference (do not print the full amount of JSON, avoid repeatedly plugging the 10–14 KB golden reference back into the context).

Usage:
    uv run python scripts/diff_golden.py # All sequences, print differences only
    uv run python scripts/diff_golden.py sweep_basic # Specify sequence
    uv run python scripts/diff_golden.py --all # Print a line with a consistent sequence"""
from __future__ import annotations

import json
import logging
import sys
import tempfile
from pathlib import Path

from cadmcp.backend.fake.backend import FakeBackend
from cadmcp.consistency import SEQUENCES, diff_fingerprints, run_sequence, structural_fingerprint

GOLDEN_DIR = Path(__file__).resolve().parent.parent / "tests" / "data" / "consistency"
MAX_LINES = 20

# The doc_cycle and other sequences in the golden reference close the document
# first, so fingerprint reading will inevitably alarm; diff only cares about the
# difference and blocks the noise.
logging.disable(logging.WARNING)


def diff_one(name: str) -> list[str]:
    path = GOLDEN_DIR / f"{name}.json"
    if not path.exists():
        return [f"Missing golden reference file: {path.name}"]
    expected = json.loads(path.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        actual = structural_fingerprint(
            run_sequence(FakeBackend, SEQUENCES[name], workspace=Path(tmp))
        )
    return diff_fingerprints(expected, actual)


def main(argv: list[str]) -> int:
    show_all = "--all" in argv
    names = [arg for arg in argv if not arg.startswith("-")] or sorted(SEQUENCES)
    unknown = [name for name in names if name not in SEQUENCES]
    if unknown:
        print(f"Unknown sequence(s): {', '.join(unknown)}", file=sys.stderr)
        return 2

    changed = 0
    for name in names:
        diffs = diff_one(name)
        if not diffs:
            if show_all:
                print(f"OK   {name}")
            continue
        changed += 1
        print(f"\nDIFF {name} at {len(diffs)}")
        for line in diffs[:MAX_LINES]:
            print(f"  - {line}")
        if len(diffs) > MAX_LINES:
            print(f"... and {len(diffs) - MAX_LINES} more omitted")

    print(f"\n {len(names) - changed}/{len(names)} Consistent, {changed} difference")
    return 0 if changed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
