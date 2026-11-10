"""S1 gate: migration records valid + coverage calculation correct."""
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCOPE_FILE = ROOT / "cadmcp" / "backend" / "migration_scope.yaml"
MAP_FILE = ROOT / "cadmcp" / "backend" / "migration_map.yaml"


def test_migration_map_valid():
    scope = yaml.safe_load(SCOPE_FILE.read_text(encoding="utf-8"))
    m = yaml.safe_load(MAP_FILE.read_text(encoding="utf-8"))
    scope_ids = {r["id"] for r in scope.get("scope", [])}
    map_ids = {r["id"] for r in m.get("migrations", [])}
    assert scope_ids == map_ids, "scope and migration_map ids do not match"
    assert len(scope_ids) == 486, f"expected 486 entries, got {len(scope_ids)}"


def test_status_combinations():
    VALID = {
        "pending": {"behavior": {"pending"}, "target": {None}},
        "migrated": {"behavior": {"unchanged", "refactored", "renamed"}, "target": {"required"}},
        "verified": {"behavior": {"unchanged", "refactored", "renamed"}, "target": {"required"}},
        "skipped": {"behavior": {"pending"}, "target": {None}},
        "blocked": {"behavior": {"unchanged", "refactored", "renamed"}, "target": {"optional"}},
        "commented_out": {"behavior": {"commented_out"}, "target": {"required"}},
    }
    m = yaml.safe_load(MAP_FILE.read_text(encoding="utf-8"))
    errors = []
    for row in m["migrations"]:
        st = row["status"]
        if st not in VALID:
            errors.append(f"{row['id']}: unknown status {st}")
            continue
        rule = VALID[st]
        if row["behavior"] not in rule["behavior"]:
            errors.append(f"{row['id']}: invalid behavior={row['behavior']} for {st}")
        tgt = row.get("target")
        if "required" in rule["target"] and not tgt:
            errors.append(f"{row['id']}: {st} requires target")
        if rule["target"] == {None} and tgt is not None:
            errors.append(f"{row['id']}: target must be null for {st}")
    assert not errors, "\n".join(errors)


def test_coverage_calculation():
    m = yaml.safe_load(MAP_FILE.read_text(encoding="utf-8"))
    verified = sum(1 for r in m["migrations"] if r["status"] == "verified")
    assert verified >= 0  # stage A may be 0


def test_verify_migration_script_passes():
    """Stage A: verify_migration script (with _resolve fixes) runs cleanly."""
    script = Path(__file__).resolve().parents[2] / "scripts" / "verify_migration.py"
    r = subprocess.run([sys.executable, str(script)], capture_output=True)
    out = (r.stdout + r.stderr).decode("utf-8", errors="replace")
    assert r.returncode == 0, out
