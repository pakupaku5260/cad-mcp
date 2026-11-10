"""
Compare S0 / S9 API baselines; separate interface vs structural changes.

Usage:
    python scripts/compare_api.py
    python scripts/compare_api.py --report cadmcp/backend/api_diff_s9.md
    python scripts/compare_api.py --json

Rules (v1.2.2 §12.3.5):
    - Interface: removed members, kind changes, signature/default/annotation changes, broken compat imports.
      Must be 0 or exit 1.
    - Structural: member source class changes, new public members in S9.
      Allowed but require approval in `structural_changes.md`.

Read-only on two baseline files; does not import backend or modify baselines.

"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
S0_FILE = ROOT / "cadmcp/backend/api_baseline_s0.json"
S9_FILE = ROOT / "cadmcp/backend/api_baseline_s9.json"


def _display(path: Path) -> str:
    """Repo-relative paths in reports (avoid machine absolutes in git)."""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _member_view(member: dict | None) -> dict | None:
    if member is None:
        return None
    return {
        "kind": member.get("kind"),
        "signature_str": member.get("signature_str"),
        "source": member.get("source"),
    }


def compare_class(name: str, old: dict, new: dict) -> tuple[list[dict], list[dict]]:
    """Return (interface_diffs, structural_changes), both flat lists."""
    interface_diffs: list[dict] = []
    structural: list[dict] = []

    old_names, new_names = set(old), set(new)
    for member in sorted(old_names - new_names):
        interface_diffs.append({
            "class": name,
            "member": member,
            "change": "removed",
            "s0": _member_view(old[member]),
            "s9": None,
        })
    for member in sorted(new_names - old_names):
        structural.append({
            "class": name,
            "member": member,
            "change": "added",
            "s0": None,
            "s9": _member_view(new[member]),
        })

    for member in sorted(old_names & new_names):
        before, after = old[member], new[member]
        if before.get("kind") != after.get("kind"):
            interface_diffs.append({
                "class": name,
                "member": member,
                "change": "kind",
                "s0": _member_view(before),
                "s9": _member_view(after),
            })
        elif before.get("signature_struct") != after.get("signature_struct"):
            interface_diffs.append({
                "class": name,
                "member": member,
                "change": "signature",
                "s0": _member_view(before),
                "s9": _member_view(after),
                "s0_struct": before.get("signature_struct"),
                "s9_struct": after.get("signature_struct"),
            })
        if before.get("source") != after.get("source"):
            structural.append({
                "class": name,
                "member": member,
                "change": "source",
                "s0": _member_view(before),
                "s9": _member_view(after),
            })
    return interface_diffs, structural


def _structural_summary(structural: list[dict]) -> dict:
    """Aggregate structural changes by class for human-readable reports."""
    out: dict[str, dict] = {}
    for item in structural:
        bucket = out.setdefault(item["class"], {
            "members": 0,
            "added": [],
            "s0_sources": set(),
            "s9_sources": set(),
        })
        bucket["members"] += 1
        if item["change"] == "added":
            bucket["added"].append(item["member"])
        for side, key in (("s0", "s0_sources"), ("s9", "s9_sources")):
            view = item.get(side)
            if view and view.get("source"):
                bucket[key].add(view["source"])
    for bucket in out.values():
        bucket["s0_sources"] = sorted(bucket["s0_sources"])
        bucket["s9_sources"] = sorted(bucket["s9_sources"])
        bucket["added"].sort()
    return out


def compare(s0: dict, s9: dict) -> dict:
    s0_classes = s0.get("classes", {})
    s9_classes = s9.get("classes", {})

    interface_diffs: list[dict] = []
    structural: list[dict] = []
    class_reports: dict[str, dict] = {}

    for name in sorted(set(s0_classes) | set(s9_classes)):
        old, new = s0_classes.get(name), s9_classes.get(name)
        if old is None:
            structural.append({
                "class": name,
                "member": None,
                "change": "class_added",
                "s0": None,
                "s9": {"kind": "class", "members": len(new or {})},
            })
            continue
        if new is None:
            interface_diffs.append({
                "class": name,
                "member": None,
                "change": "class_removed",
                "s0": {"kind": "class", "members": len(old)},
                "s9": None,
            })
            continue
        class_iface, class_struct = compare_class(name, old, new)
        interface_diffs.extend(class_iface)
        structural.extend(class_struct)
        class_reports[name] = {
            "member_count_s0": len(old),
            "member_count_s9": len(new),
            "interface_diffs": len(class_iface),
            "structural_changes": len(class_struct),
        }

    compat_failures = [
        item for item in s9.get("compat_imports_s9", [])
        if not item.get("ok")
    ]
    for item in compat_failures:
        interface_diffs.append({
            "class": "<compat_import>",
            "member": f"{item.get('path')}.{item.get('name')}",
            "change": "import_failed",
            "s0": {"kind": item.get("kind")},
            "s9": {"error": item.get("error")},
        })

    unavailable = s9.get("unavailable", [])
    for item in unavailable:
        interface_diffs.append({
            "class": item.get("class"),
            "member": None,
            "change": "class_unavailable",
            "s0": None,
            "s9": {"kind": "class", "signature_str": item.get("error")},
        })

    summary = {
        "classes_compared": len(class_reports),
        "interface_diffs": len(interface_diffs),
        "structural_changes": len(structural),
        "compat_imports_checked": len(s9.get("compat_imports_s9", [])),
        "compat_imports_failed": len(compat_failures),
        "ok": not interface_diffs,
    }
    return {
        "s0": {"file": str(S0_FILE), "capture_stage": s0.get("capture_stage")},
        "s9": {"file": str(S9_FILE), "capture_stage": s9.get("capture_stage")},
        "summary": summary,
        "classes": class_reports,
        "interface_diffs": interface_diffs,
        "structural_changes": structural,
        "structural_summary": _structural_summary(structural),
    }


def _fmt_view(view: dict | None) -> str:
    if not view:
        return "—"
    return f"{view.get('kind')} {view.get('signature_str') or ''}".strip()


def render_markdown(result: dict) -> str:
    summary = result["summary"]
    lines = [
        "# S0 → S9 API diff report",
        "",
        f"- S0 baseline: `{result['s0']['file']}` ({result['s0']['capture_stage']})",
        f"- S9 baseline: `{result['s9']['file']}` ({result['s9']['capture_stage']})",
        "",
        "## Summary",
        "",
        f"- Interface diffs: **{summary['interface_diffs']}** (must be 0)",
        f"- Structural changes: **{summary['structural_changes']}** (need approval)",
        f"- Compat imports: checked {summary['compat_imports_checked']}, "
        f"failed {summary['compat_imports_failed']}",
        f"- Result: {'pass' if summary['ok'] else 'blocked'}",
        "",
        "## Interface diffs",
        "",
    ]
    if not result["interface_diffs"]:
        lines.append("None.")
    else:
        lines += [
            "| class | member | change | S0 | S9 |",
            "|---|---|---|---|---|",
        ]
        for item in result["interface_diffs"]:
            lines.append(
                f"| {item['class']} | {item['member'] or '—'} | {item['change']} | "
                f"{_fmt_view(item.get('s0'))} | {_fmt_view(item.get('s9'))} |"
            )

    lines += ["", "## Structural changes (by class)", ""]
    if not result["structural_summary"]:
        lines.append("None.")
    else:
        lines += [
            "| class | members | S0 sources | S9 sources | added |",
            "|---|---|---|---|---|",
        ]
        for name, bucket in sorted(result["structural_summary"].items()):
            added = ", ".join(bucket["added"]) if bucket["added"] else "—"
            lines.append(
                f"| {name} | {bucket['members']} | "
                f"{', '.join(bucket['s0_sources'])} | "
                f"{', '.join(bucket['s9_sources'])} | {added} |"
            )
        lines += [
            "",
            "> Confirm structural changes per class in `structural_changes.md`; "
            "interface diffs must be fixed, not waived by approval.",
        ]
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare S0 / S9 API baselines")
    parser.add_argument("--s0", type=Path, default=S0_FILE, help="S0 baseline path")
    parser.add_argument("--s9", type=Path, default=S9_FILE, help="S9 baseline path")
    parser.add_argument("--report", type=Path, help="Write Markdown report to path")
    parser.add_argument("--json", action="store_true", help="Emit full JSON (no summary)")
    args = parser.parse_args()

    for label, path in (("S0", args.s0), ("S9", args.s9)):
        if not path.exists():
            print(f"[X] {label} baseline missing: {path}")
            if label == "S9":
                print("  Run first: python scripts/snapshot_api_s9.py")
            return 2

    s0 = json.loads(args.s0.read_text(encoding="utf-8"))
    s9 = json.loads(args.s9.read_text(encoding="utf-8"))
    result = compare(s0, s9)
    result["s0"]["file"] = _display(args.s0)
    result["s9"]["file"] = _display(args.s9)

    report = render_markdown(result)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report, encoding="utf-8")
        print(f"[OK] Report written: {args.report}")

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        summary = result["summary"]
        print(
            f"interface {summary['interface_diffs']} / "
            f"structural {summary['structural_changes']} / "
            f"compat import failures {summary['compat_imports_failed']}"
        )
        for item in result["interface_diffs"]:
            print(
                f"  [X] [{item['change']}] {item['class']}.{item['member'] or ''}: "
                f"{_fmt_view(item.get('s0'))} -> {_fmt_view(item.get('s9'))}"
            )
        for name, bucket in sorted(result["structural_summary"].items()):
            extra = f", added {bucket['added']}" if bucket["added"] else ""
            print(
                f"  - [structural] {name}: {bucket['members']} members, "
                f"S0 sources {len(bucket['s0_sources'])} -> "
                f"S9 sources {len(bucket['s9_sources'])}{extra}"
            )

    return 0 if result["summary"]["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
