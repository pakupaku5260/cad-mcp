"""
S10: compare the split SolidWorks backend against the frozen S0 COM call-sequence baseline.

Usage:
    python scripts/snapshot_com_sequence.py --compare
    python scripts/snapshot_com_sequence.py --compare --report cadmcp/backend/com_sequence_baseline_diff.md

--compare (S10):
    Rescan the same public methods under `cadmcp/backend/solidworks/`.
    The S0 baseline (`com_sequence_baseline.yaml`) was captured from the pre-split
    monolithic backend and is frozen; this script never regenerates it.
    Compare baseline entry-by-entry on object + method + argument expression (v1.2.2 section 12.5).
    Diffs must land in `com_sequence_baseline_diff.md` with human approval;
    approvals live in `com_sequence_approvals.yaml` (fingerprinted; re-alerts if sequences change).

Limitations (S0 v1, still used at compare time):
    - Only direct COM calls in public methods; helpers are not expanded.
    - Public methods with no direct COM call are omitted from the baseline.



"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
BASELINE_FILE = ROOT / "cadmcp/backend/com_sequence_baseline.yaml"
WHITELIST_FILE = ROOT / "cadmcp/backend/com_objects_whitelist.yaml"
COM_DIR = ROOT / "cadmcp" / "backend" / "solidworks"
APPROVALS_FILE = ROOT / "cadmcp/backend/com_sequence_approvals.yaml"


def _display_path(path: Path) -> str:
    """Use repo-relative paths in reports so local absolutes never land in git."""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def load_whitelist() -> set[str]:
    if not WHITELIST_FILE.exists():
        print(f"⚠ whitelist missing: {WHITELIST_FILE}")
        return set()
    data = yaml.safe_load(WHITELIST_FILE.read_text(encoding="utf-8"))
    return set(data.get("objects", []))


def is_com_object(expr: ast.expr, whitelist: set[str]) -> str | None:
    """Whether expr is attribute access on a whitelisted object (e.g. doc.ClearSelection2).

    Returns the object name when matched, else None.
    """
    if not isinstance(expr, ast.Attribute):
        return None
    value = expr.value
    # direct self.doc or local name in whitelist
    if isinstance(value, ast.Name) and value.id in whitelist:
        return value.id
    if isinstance(value, ast.Attribute):
        # self.doc.xxx: walk to self.<attr> and match whitelist
        if isinstance(value.value, ast.Name) and value.value.id == "self":
            if value.attr in whitelist:
                return f"self.{value.attr}"
    return None


def scan_method(
    class_name: str,
    method: ast.FunctionDef | ast.AsyncFunctionDef,
    whitelist: set[str],
    *,
    source_label: str = "com_backend.py",
) -> list[dict]:
    sequence: list[dict] = []
    for node in ast.walk(method):
        if not isinstance(node, ast.Call):
            continue
        obj = is_com_object(node.func, whitelist)
        if obj is None:
            continue
        method_name = node.func.attr
        # argument expression strings (not expanded)
        args_str = ", ".join(ast.unparse(a) for a in node.args)
        sequence.append({
            "object": obj.replace("self.", ""),
            "method": method_name,
            "args": args_str,
            "location": f"{source_label}:{node.lineno}",
            "call_path": [f"{class_name}.{method.name}"],
        })
    return sequence


def scan_com_package(
    whitelist: set[str],
) -> tuple[dict[str, dict], list[dict]]:
    """Scan the split com/ package; return (method snapshots, duplicate method list).

    Public Mixin methods become ComBackend methods after composition,
    so keys are always `ComBackend.<method>`, matching the S0 baseline.
    """
    methods: dict[str, dict] = {}
    duplicates: list[dict] = []
    for path in sorted(COM_DIR.rglob("*.py")):
        source_label = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if node.name != "ComBackend" and not node.name.endswith("Mixin"):
                continue
            for child in node.body:
                if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if child.name.startswith("_"):
                    continue
                seq = scan_method(
                    node.name, child, whitelist, source_label=source_label
                )
                if not seq:
                    continue
                key = f"ComBackend.{child.name}"
                if key in methods:
                    duplicates.append({
                        "method": key,
                        "first": methods[key]["file"],
                        "second": source_label,
                    })
                    continue
                methods[key] = {
                    "method": key,
                    "mixin": node.name,
                    "file": source_label,
                    "sequence": seq,
                }
    return methods, duplicates


def _main_sequence(entry: dict) -> list[dict]:
    scenarios = entry.get("scenarios") or []
    for scenario in scenarios:
        if scenario.get("name") == "main_path":
            return scenario.get("sequence", [])
    return scenarios[0].get("sequence", []) if scenarios else []


def _norm_sequence(sequence: list[dict]) -> list[list[str]]:
    """Normalize to comparable triples; location/call_path are structural and ignored."""
    return [
        [str(call.get("object")), str(call.get("method")), str(call.get("args", ""))]
        for call in sequence
    ]


def _fingerprint(method: str, status: str, baseline: list, current: list) -> str:
    payload = {
        "method": method,
        "status": status,
        "baseline": baseline,
        "current": current,
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def load_approvals(path: Path) -> dict[str, dict]:
    """Load approvals; keys are diff fingerprints, values are approval records."""
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: dict[str, dict] = {}
    for index, item in enumerate(data.get("approved", [])):
        method = item.get("method")
        digest = item.get("diff_sha256")
        if not method or not digest:
            raise ValueError(f"{path} entry {index + 1} approval missing method/diff_sha256")
        if not item.get("reason") or not item.get("approved_by"):
            raise ValueError(f"{path} entry {index + 1} approval missing reason/approved_by")
        out[digest] = item
    return out


def compare(approvals_path: Path) -> dict:
    baseline = yaml.safe_load(BASELINE_FILE.read_text(encoding="utf-8"))
    baseline_methods = {item["method"]: item for item in baseline.get("methods", [])}

    whitelist = load_whitelist()
    if not whitelist:
        raise ValueError("whitelist is empty; cannot compare")

    current_methods, duplicates = scan_com_package(whitelist)
    approvals = load_approvals(approvals_path)

    diffs: list[dict] = []
    for method in sorted(set(baseline_methods) | set(current_methods)):
        old_entry = baseline_methods.get(method)
        new_entry = current_methods.get(method)
        if old_entry is None:
            status = "added"
            old_seq, new_seq = [], _norm_sequence(new_entry["sequence"])
        elif new_entry is None:
            status = "removed"
            old_seq, new_seq = _norm_sequence(_main_sequence(old_entry)), []
        else:
            old_seq = _norm_sequence(_main_sequence(old_entry))
            new_seq = _norm_sequence(new_entry["sequence"])
            if old_seq == new_seq:
                continue
            status = "changed"

        digest = _fingerprint(method, status, old_seq, new_seq)
        approval = approvals.get(digest)
        diffs.append({
            "method": method,
            "status": status,
            "mixin": (new_entry or {}).get("mixin"),
            "file": (new_entry or {}).get("file"),
            "baseline_calls": len(old_seq),
            "current_calls": len(new_seq),
            "baseline": old_seq,
            "current": new_seq,
            "diff_sha256": digest,
            "approved": approval is not None,
            "approval": approval,
        })

    used = {item["diff_sha256"] for item in diffs if item["approved"]}
    stale = [approval for digest, approval in approvals.items() if digest not in used]
    unapproved = [item for item in diffs if not item["approved"]]
    return {
        "baseline_file": _display_path(BASELINE_FILE),
        "baseline_source_sha": baseline.get("source_sha"),
        "current_root": COM_DIR.relative_to(ROOT).as_posix(),
        "baseline_methods": len(baseline_methods),
        "current_methods": len(current_methods),
        "baseline_calls": sum(
            len(_main_sequence(item)) for item in baseline_methods.values()
        ),
        "current_calls": sum(
            len(item["sequence"]) for item in current_methods.values()
        ),
        "diffs": diffs,
        "unapproved": len(unapproved),
        "approved": len(diffs) - len(unapproved),
        "stale_approvals": stale,
        "duplicates": duplicates,
        "ok": not unapproved and not duplicates,
    }


def _render_sequence(sequence: list) -> str:
    if not sequence:
        return "(empty)"
    return "\n".join(
        f"    {index + 1}. {call[0]}.{call[1]}({call[2]})"
        for index, call in enumerate(sequence)
    )


def render_markdown(result: dict) -> str:
    lines = [
        "# COM call sequence diff report",
        "",
        f"- Baseline: `{result['baseline_file']}` (source_sha={result['baseline_source_sha']})",
        f"- Current scan root: `{result['current_root']}`",
        f"- Baseline: {result['baseline_methods']} methods / {result['baseline_calls']} call sites",
        f"- Current: {result['current_methods']} methods / {result['current_calls']} call sites",
        f"- Diffs: {len(result['diffs'])} (unapproved {result['unapproved']}, "
        f"approved {result['approved']})",
        f"- Result:{'PASS' if result['ok'] else 'BLOCKED'}",
        "",
        "## Unapproved diffs",
        "",
    ]
    pending = [item for item in result["diffs"] if not item["approved"]]
    if not pending:
        lines += ["None.", ""]
    for item in pending:
        lines += [
            f"### `{item['method']}` ({item['status']})",
            "",
            f"- Location: `{item['file']}` / {item['mixin']}",
            f"- Baseline {item['baseline_calls']} call sites; current {item['current_calls']}",
            f"- Approval fingerprint: `{item['diff_sha256']}`",
            "",
            "Baseline:",
            "```",
            _render_sequence(item["baseline"]),
            "```",
            "",
            "Current:",
            "```",
            _render_sequence(item["current"]),
            "```",
            "",
        ]

    approved = [item for item in result["diffs"] if item["approved"]]
    lines += ["## Approved diffs", ""]
    if not approved:
        lines += ["None.", ""]
    for item in approved:
        approval = item["approval"] or {}
        lines += [
            f"- `{item['method']}`（{item['status']}）：{approval.get('reason')} "
            f"— approved by {approval.get('approved_by')}",
        ]

    if result["stale_approvals"]:
        lines += ["", "## Stale approvals (unused in current diff; clean up)", ""]
        for item in result["stale_approvals"]:
            lines.append(
                f"- `{item.get('method')}`(fingerprint `{item.get('diff_sha256')}`）"
            )

    if result["duplicates"]:
        lines += ["", "## Scan anomalies: duplicate method definitions", ""]
        for item in result["duplicates"]:
            lines.append(
                f"- `{item['method']}`：`{item['first']}` and `{item['second']}` duplicate"
            )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="COM call sequence baseline capture / compare")
    parser.add_argument(
        "--compare",
        action="store_true",
        required=True,
        help="compare current solidworks/ package to the frozen S0 baseline",
    )
    parser.add_argument(
        "--approvals",
        type=Path,
        default=APPROVALS_FILE,
        help="approvals YAML (default cadmcp/backend/com_sequence_approvals.yaml)",
    )
    parser.add_argument("--report", type=Path, help="write Markdown diff report to the given file")
    parser.add_argument("--json", action="store_true", help="emit full JSON (no summary lines)")
    args = parser.parse_args()

    if not BASELINE_FILE.exists():
        print(f"[!] baseline missing:{BASELINE_FILE}")
        return 2
    try:
        result = compare(args.approvals)
    except ValueError as exc:
        print(f"[!] {exc}")
        return 2

    report = render_markdown(result)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report, encoding="utf-8")
        print(f"[OK] wrote report:{args.report}")

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(
            f"diffs {len(result['diffs'])} (unapproved {result['unapproved']}, "
            f"approved {result['approved']})"
        )
        for item in result["diffs"]:
            mark = "OK" if item["approved"] else "XX"
            print(
                f"  {mark} [{item['status']}] {item['method']} "
                f"({item['file']} / {item['mixin']}) "
                f"{item['baseline_calls']} -> {item['current_calls']} call sites"
            )
            if not item["approved"]:
                print(f"      approval fingerprint:{item['diff_sha256']}")
        for item in result["stale_approvals"]:
            print(f"  [!] stale approval:{item.get('method')} ({item.get('diff_sha256')})")
        for item in result["duplicates"]:
            print(f"  [!] duplicate method: {item['method']} ({item['first']} / {item['second']})")

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
