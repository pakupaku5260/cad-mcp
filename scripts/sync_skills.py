"""Sync cadmcp/resources/content/skills to .opencode/skills/<id>/SKILL.md.

Usage:
  python scripts/sync_skills.py
  python scripts/sync_skills.py --check   # compare repo copy; exit 1 on mismatch
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cadmcp.skills import SKILL_IDS, load_skill_text, sync_opencode_skills  # noqa: E402


def check() -> int:
    mismatches: list[str] = []
    for skill_id in SKILL_IDS:
        dest = ROOT / ".opencode" / "skills" / skill_id / "SKILL.md"
        expected = load_skill_text(skill_id)
        if not dest.is_file():
            mismatches.append(f"missing {dest.relative_to(ROOT).as_posix()}")
            continue
        actual = dest.read_text(encoding="utf-8")
        if actual.replace("\r\n", "\n") != expected.replace("\r\n", "\n"):
            mismatches.append(f"stale {dest.relative_to(ROOT).as_posix()}")
    if mismatches:
        print("skill sync check failed:", file=sys.stderr)
        for item in mismatches:
            print(f"  - {item}", file=sys.stderr)
        print("run: python scripts/sync_skills.py", file=sys.stderr)
        return 1
    print(f"ok: {len(SKILL_IDS)} skills in sync")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="check whether .opencode copies are stale")
    args = parser.parse_args()
    if args.check:
        return check()
    written = sync_opencode_skills(ROOT)
    for path in written:
        print(path.relative_to(ROOT).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
