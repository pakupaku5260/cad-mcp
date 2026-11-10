"""Validate migration_map.yaml and compute coverage.

Usage:
    python scripts/verify_migration.py                # strict mode (S2+)
    python scripts/verify_migration.py --stage a      # stage A (planned pending not errors)
    python scripts/verify_migration.py --quiet        # stats only, skip per-error lines
"""
from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MAP_FILE = ROOT / "cadmcp/backend/migration_map.yaml"
SCOPE_FILE = ROOT / "cadmcp/backend/migration_scope.yaml"

VALID_STATUS = {"pending", "migrated", "verified", "skipped", "blocked", "commented_out"}
VALID_BEHAVIOR = {"pending", "unchanged", "refactored", "renamed", "commented_out"}
VALID_VERIFICATION = {"verified", "partial", "unverified"}
VALID_COVERAGE = {"com_only", "fake_only", "shared"}
VALID_CATEGORY = {"method", "state", "lifecycle", "thread", "helper"}
VALID_VERIFICATION_REQ = {
    "unit_test", "fake_verification", "com_real_machine",
    "consistency", "baseline_compare",
}

MIN_VERIFICATION = {
    "com_only": {"unit_test", "com_real_machine", "baseline_compare"},
    "fake_only": {"unit_test", "fake_verification", "baseline_compare"},
    "shared": {"unit_test", "com_real_machine", "fake_verification",
               "consistency", "baseline_compare"},
}

# Stage A exemption: methods migrated in stages B/C/D (pending allowed in strict too)
A_STAGE_PENDING_IDS = {
    # C stage (explode.py)
    "M-0051", "M-0052", "M-0053", "M-0054", "M-0055",
    # D stage (component.py array private methods)
    "M-0057", "M-0058",
    # B stage (mate.py)
    "M-0068", "M-0069", "M-0070", "M-0071",
    "M-0072", "M-0073", "M-0074",
    "M-0075", "M-0076", "M-0077", "M-0078",
    "M-0079", "M-0080",
    "M-0082", "M-0083", "M-0084",
}


def _resolve(target: str):
    """target is like 'pkg.mod.Class.attr' or 'pkg.mod.func'.

    Try the longest importable prefix segment by segment, then getattr the rest.
    Legacy colon form 'pkg.mod:Class.attr' is supported.
    """
    if ":" in target:
        mod_path, _, obj_path = target.partition(":")
        mod = importlib.import_module(mod_path)
        obj = mod
        for name in obj_path.split("."):
            obj = getattr(obj, name)
        return obj

    parts = target.split(".")
    last_err: Exception | None = None
    for i in range(len(parts), 0, -1):
        mod_path = ".".join(parts[:i])
        try:
            mod = importlib.import_module(mod_path)
        except Exception as exc:  # noqa: BLE001 — shorten prefix and retry
            last_err = exc
            continue
        obj = mod
        try:
            for attr in parts[i:]:
                obj = getattr(obj, attr)
            return obj
        except AttributeError as exc:
            last_err = exc
            continue
    raise ImportError(f"cannot resolve {target} (last: {last_err})")


def check_target(target: str) -> None:
    _resolve(target)


def check_path(path: str) -> bool:
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    return p.exists()


def check_commented_block(row: dict, errors: list[str], prefix: str) -> None:
    target = row.get("target") or ""
    if ":" in target:
        module_path, _, object_path = target.partition(":")
    else:
        module_path, _, object_path = target.rpartition(".")
    method_name = object_path.rsplit(".", 1)[-1]
    file_path = ROOT / (module_path.replace(".", "/") + ".py")
    if not file_path.exists():
        errors.append(f"{prefix}: commented_out target file missing: {file_path}")
        return
    lines = file_path.read_text(encoding="utf-8").splitlines()
    found = False
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith("#"):
            block_start = i
            while i < len(lines) and lines[i].lstrip().startswith("#"):
                i += 1
            block = "\n".join(lines[block_start:i])
            if method_name in block:
                found = True
                break
        else:
            i += 1
    if not found:
        errors.append(f"{prefix}: no comment block containing {method_name}")


def _check_row(
    row: dict,
    scope_index: dict,
    errors: list[str],
    stage: str,
) -> dict:
    """Validate one row; return stats {status, migrated, verified, public, public_verified}."""
    rid = row.get("id", "?")
    prefix = f"migration[{rid}]"

    status = row.get("status")
    behavior = row.get("behavior")
    verification = row.get("verification")

    stats = {
        "status": status,
        "migrated_or_verified": 0,
        "verified": 0,
        "public": False,
        "public_verified": 0,
    }

    if status not in VALID_STATUS:
        errors.append(f"{prefix}: invalid status={status}")
        return stats
    if behavior not in VALID_BEHAVIOR:
        errors.append(f"{prefix}: invalid behavior={behavior}")
        return stats
    if verification not in VALID_VERIFICATION:
        errors.append(f"{prefix}: invalid verification={verification}")
        return stats

    # verification consistency
    if status == "verified" and verification != "verified":
        errors.append(f"{prefix}: status=verified requires verification=verified")
    if status != "verified" and verification == "verified":
        errors.append(f"{prefix}: status!=verified cannot have verification=verified")

    # scope side
    scope_item = scope_index.get(rid)
    if scope_item is None:
        # consistency reported in main; skip duplicate
        return stats

    coverage = scope_item.get("coverage_type")
    public = bool(scope_item.get("public", False))
    category = scope_item.get("category")
    req = set(scope_item.get("verification_required") or [])
    stats["public"] = public

    if category not in VALID_CATEGORY:
        errors.append(f"{prefix}: invalid scope.category: {category}")

    # verification_required validity
    if status != "skipped":
        if not req:
            errors.append(f"{prefix}: verification_required missing")
        bad = req - VALID_VERIFICATION_REQ
        if bad:
            errors.append(f"{prefix}: verification_required has invalid values: {bad}")
        # coverage minimum: only for verified rows
        if status == "verified" and coverage in MIN_VERIFICATION:
            missing = MIN_VERIFICATION[coverage] - req
            if missing:
                errors.append(
                    f"{prefix}: verified row verification_required below {coverage} minimum; missing {missing}"
                )

    # status branches
    if status == "pending":
        if row.get("target"):
            errors.append(f"{prefix}: pending requires target=null")
        # stage A: planned pending is not an error (strict also allows legal pending)
        if stage == "a" and rid not in A_STAGE_PENDING_IDS:
            pass

    elif status == "migrated":
        stats["migrated_or_verified"] = 1
        if not row.get("target"):
            errors.append(f"{prefix}: migrated requires target")
        else:
            try:
                check_target(row["target"])
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{prefix}: target not found: {exc}")

    elif status == "verified":
        stats["migrated_or_verified"] = 1
        stats["verified"] = 1
        if not row.get("target"):
            errors.append(f"{prefix}: verified requires target")
        else:
            try:
                check_target(row["target"])
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{prefix}: target not found: {exc}")
        if not (row.get("verification_evidence") or []):
            errors.append(f"{prefix}: verified missing verification_evidence")
        if not (row.get("tests") or []):
            errors.append(f"{prefix}: verified missing tests")
        if public:
            stats["public_verified"] = 1

    elif status == "skipped":
        if not row.get("skip_reason"):
            errors.append(f"{prefix}: skipped requires skip_reason")
        if not row.get("skip_approved_by"):
            errors.append(f"{prefix}: skipped requires skip_approved_by")

    elif status == "blocked":
        if not row.get("notes"):
            errors.append(f"{prefix}: blocked requires notes")

    elif status == "commented_out":
        if behavior != "commented_out":
            errors.append(f"{prefix}: commented_out requires behavior=commented_out")
        check_commented_block(row, errors, prefix)

    # evidence path existence
    for path in (row.get("verification_evidence") or []) + (row.get("tests") or []):
        if not isinstance(path, str):
            errors.append(f"{prefix}: evidence path must be a string")
            continue
        file_part = path.split("::", 1)[0]
        if not check_path(file_part):
            errors.append(f"{prefix}: file not found: {file_part}")

    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migration record validation + coverage")
    parser.add_argument("--stage", default="strict", choices=["a", "strict"],
                        help="a=stage A friendly; strict=strict (S2+)")
    parser.add_argument("--quiet", action="store_true", help="stats only, omit per-error detail")
    args = parser.parse_args(argv)

    errors: list[str] = []

    if not MAP_FILE.exists() or not SCOPE_FILE.exists():
        print("migration_map.yaml or migration_scope.yaml missing; S0 incomplete?")
        return 0

    try:
        map_data = yaml.safe_load(MAP_FILE.read_text(encoding="utf-8")) or {}
        scope_data = yaml.safe_load(SCOPE_FILE.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        print(f"Cannot read YAML: {exc}")
        return 1

    rows = map_data.get("migrations") or []
    scope_rows = scope_data.get("scope") or []

    if not scope_rows:
        print("scope empty; S0 scan not done?")
        return 0

    scope_index = {r["id"]: r for r in scope_rows if "id" in r}
    map_index = {r["id"]: r for r in rows if "id" in r}

    # consistency
    for sid in scope_index:
        if sid not in map_index:
            errors.append(f"scope item {sid} missing from migration_map")
    for mid in map_index:
        if mid not in scope_index:
            errors.append(f"migration_map item {mid} not in scope")

    # per-row validation + stats
    counts = {k: 0 for k in VALID_STATUS}
    vcounts = {k: 0 for k in VALID_VERIFICATION}
    migrated_or_verified = 0
    verified_count = 0
    public_total = 0
    public_verified = 0

    for row in rows:
        st = _check_row(row, scope_index, errors, args.stage)
        if st["status"] in counts:
            counts[st["status"]] += 1
        ver = row.get("verification")
        if ver in vcounts:
            vcounts[ver] += 1
        migrated_or_verified += st["migrated_or_verified"]
        verified_count += st["verified"]
        if st["public"]:
            public_total += 1
        public_verified += st["public_verified"]

    if errors:
        print("Validation failed:")
        if args.quiet:
            print(f"  (--quiet, {len(errors)} errors, detail omitted)")
        else:
            for e in errors:
                print(f"  ✗ {e}")

    com_rows = [r for r in rows if not str(r.get("original", "")).startswith("fake_backend.py:")]
    com_skipped = sum(1 for r in com_rows if r.get("status") == "skipped")
    com_migrated = sum(1 for r in com_rows if r.get("status") in ("migrated", "verified"))
    total_com = len(com_rows) - com_skipped
    if total_com:
        print(f"COM migration completeness: {com_migrated} / {total_com} = {com_migrated / total_com:.1%}")
    else:
        print("COM migration completeness: 0 / 0 = 0.0%")

    migrated_total = migrated_or_verified
    total_non_skipped = len(scope_rows) - counts["skipped"]
    migration_rate = migrated_or_verified / total_non_skipped if total_non_skipped else 0.0
    api_rate = public_verified / public_total if public_total else 0.0
    verified_rate = verified_count / migrated_total if migrated_total else 0.0

    print("status: " + ", ".join(f"{k}={counts[k]}" for k in VALID_STATUS))
    print("verification: " + ", ".join(f"{k}={vcounts[k]}" for k in VALID_VERIFICATION))
    print(
        f"Migration rate (all, fake pending S8): "
        f"{migrated_or_verified} / {total_non_skipped} = {migration_rate:.1%}"
    )
    print(f"API compatibility: {public_verified} / {public_total} = {api_rate:.1%}")
    print(f"verified coverage: {verified_count} / {migrated_total} = {verified_rate:.1%}")
    if counts["skipped"]:
        print(f"skipped (approved): {counts['skipped']}")

    if args.stage == "a":
        pending_ids = {
            r.get("id") for r in rows
            if r.get("status") == "pending"
            and str(r.get("original", "")).startswith("com_backend.py:")
            and r.get("id") not in A_STAGE_PENDING_IDS
        }
        if pending_ids:
            print(f"Stage A: unplanned pending (confirm): {sorted(pending_ids)}")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
