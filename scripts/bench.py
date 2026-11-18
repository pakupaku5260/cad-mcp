"""F7 offline numeric/structure bench (Fake SEQUENCES → report vs baseline).

Usage (repo root):
    python scripts/bench.py                  # write report.json + check vs baseline
    python scripts/bench.py --update-baseline
    python scripts/bench.py --output path.json

Exit 0 when check passes (or --update-baseline succeeds). Exit 1 on regression.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cadmcp.backend.fake.backend import FakeBackend  # noqa: E402
from cadmcp.consistency import SEQUENCES, run_sequence  # noqa: E402
from cadmcp.consistency.fingerprint import (  # noqa: E402
    DEFAULT_ATOL,
    DEFAULT_RTOL,
    NUMERIC_DELTA_AFTER_KEYS,
    NUMERIC_RESULT_KEYS,
    diff_fingerprints,
    iter_numeric_leaves,
    numeric_deviation,
    structural_fingerprint,
    values_close,
)

SCHEMA_VERSION = 1
BENCH_DIR = ROOT / "benchmarks"
DEFAULT_REPORT = BENCH_DIR / "report.json"
DEFAULT_BASELINE = BENCH_DIR / "baseline.json"
PRECISION_FLOOR = 1.0  # hard gate: every compared numeric leaf must be within tolerance


def _run_all(*, rtol: float, atol: float) -> dict[str, Any]:
    sequences: dict[str, Any] = {}
    total_ok = 0
    total_steps = 0
    total_close = 0
    total_numeric = 0
    global_max_abs = 0.0
    global_max_rel = 0.0
    t0 = time.perf_counter()

    for name in sorted(SEQUENCES):
        steps = SEQUENCES[name]
        with tempfile.TemporaryDirectory(prefix=f"bench_{name}_") as td:
            t_seq = time.perf_counter()
            results = run_sequence(
                FakeBackend, steps, workspace=Path(td), sequence_name=name
            )
            elapsed_ms = (time.perf_counter() - t_seq) * 1000.0
        fp = structural_fingerprint(results, include_numeric=True)

        ok_count = sum(1 for _, r in results if r.ok)
        n_steps = len(results)
        close = 0
        n_num = 0
        max_abs = 0.0
        max_rel = 0.0
        # Self-consistency precision: compare fingerprint to itself (should be 1.0);
        # deviations only appear vs baseline. Here we count leaves present for coverage.
        for step in fp["steps"]:
            leaves = iter_numeric_leaves(step.get("numeric"))
            n_num += len(leaves)
            close += len(leaves)  # identical to self
        precision = 1.0 if n_num == 0 else close / n_num
        success_rate = ok_count / n_steps if n_steps else 1.0

        sequences[name] = {
            "n_steps": n_steps,
            "n_ok": ok_count,
            "success_rate": success_rate,
            "n_numeric_fields": n_num,
            "precision": precision,
            "max_abs_dev": max_abs,
            "max_rel_dev": max_rel,
            "elapsed_ms": round(elapsed_ms, 3),
            "fingerprint": fp,
        }
        total_ok += ok_count
        total_steps += n_steps
        total_close += close
        total_numeric += n_num

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return {
        "schema_version": SCHEMA_VERSION,
        "tolerances": {"rtol": rtol, "atol": atol, "precision_floor": PRECISION_FLOOR},
        "numeric": {
            "result_keys": sorted(NUMERIC_RESULT_KEYS),
            "delta_after_keys": sorted(NUMERIC_DELTA_AFTER_KEYS),
        },
        "summary": {
            "n_sequences": len(sequences),
            "n_steps": total_steps,
            "success_rate": (total_ok / total_steps) if total_steps else 1.0,
            "precision": (total_close / total_numeric) if total_numeric else 1.0,
            "n_numeric_fields": total_numeric,
            "max_abs_dev": global_max_abs,
            "max_rel_dev": global_max_rel,
            "elapsed_ms": round(elapsed_ms, 3),
        },
        "sequences": sequences,
    }


def _baseline_view(report: dict[str, Any]) -> dict[str, Any]:
    """Strip wall-clock / fingerprints for a deterministic committed baseline."""
    seqs = {}
    for name, data in report["sequences"].items():
        seqs[name] = {
            "n_steps": data["n_steps"],
            "n_ok": data["n_ok"],
            "success_rate": data["success_rate"],
            "n_numeric_fields": data["n_numeric_fields"],
            "precision": data["precision"],
            "fingerprint": data["fingerprint"],
        }
    return {
        "schema_version": report["schema_version"],
        "tolerances": report["tolerances"],
        "numeric": report["numeric"],
        "summary": {
            "n_sequences": report["summary"]["n_sequences"],
            "n_steps": report["summary"]["n_steps"],
            "success_rate": report["summary"]["success_rate"],
            "precision": report["summary"]["precision"],
            "n_numeric_fields": report["summary"]["n_numeric_fields"],
        },
        "sequences": seqs,
    }


def _compare_to_baseline(
    report: dict[str, Any],
    baseline: dict[str, Any],
    *,
    rtol: float,
    atol: float,
) -> list[str]:
    failures: list[str] = []
    if baseline.get("schema_version") != report.get("schema_version"):
        failures.append(
            f"schema_version: baseline {baseline.get('schema_version')!r} "
            f"vs report {report.get('schema_version')!r}"
        )

    base_seqs = baseline.get("sequences") or {}
    report_seqs = report.get("sequences") or {}
    if set(base_seqs) != set(report_seqs):
        missing = sorted(set(base_seqs) - set(report_seqs))
        extra = sorted(set(report_seqs) - set(base_seqs))
        if missing:
            failures.append(f"sequences missing from report: {missing}")
        if extra:
            failures.append(f"sequences new vs baseline: {extra}")

    for name in sorted(set(base_seqs) & set(report_seqs)):
        b = base_seqs[name]
        a = report_seqs[name]
        if a["success_rate"] < b["success_rate"] - 1e-15:
            failures.append(
                f"{name}: success_rate declined {b['success_rate']:.6g} → {a['success_rate']:.6g}"
            )
        # Numeric fingerprint compare (tolerant)
        diffs = diff_fingerprints(
            {"steps": b["fingerprint"]["steps"]},
            {"steps": a["fingerprint"]["steps"]},
            rtol=rtol,
            atol=atol,
        )
        # Count numeric-only failures for precision
        numeric_diffs = [d for d in diffs if " numeric" in d]
        structural_diffs = [d for d in diffs if " numeric" not in d]
        if structural_diffs:
            failures.append(f"{name}: structural drift:\n  " + "\n  ".join(structural_diffs[:8]))
        if numeric_diffs:
            # compute precision vs baseline leaves
            close = 0
            total = 0
            max_abs = 0.0
            max_rel = 0.0
            for es, as_ in zip(
                b["fingerprint"]["steps"], a["fingerprint"]["steps"], strict=False
            ):
                if "numeric" not in es or "numeric" not in as_:
                    continue
                exp_leaves = dict(iter_numeric_leaves(es.get("numeric")))
                act_leaves = dict(iter_numeric_leaves(as_.get("numeric")))
                for path in sorted(set(exp_leaves) | set(act_leaves)):
                    if path not in exp_leaves or path not in act_leaves:
                        total += 1
                        continue
                    total += 1
                    left, right = exp_leaves[path], act_leaves[path]
                    if values_close(left, right, rtol=rtol, atol=atol):
                        close += 1
                    ad, rd = numeric_deviation(left, right)
                    max_abs = max(max_abs, ad if ad != float("inf") else max_abs)
                    max_rel = max(max_rel, rd if rd != float("inf") else max_rel)
            precision = 1.0 if total == 0 else close / total
            if precision < PRECISION_FLOOR:
                failures.append(
                    f"{name}: precision {precision:.6g} < {PRECISION_FLOOR} "
                    f"(max_abs={max_abs:.6g}, max_rel={max_rel:.6g}); "
                    f"examples:\n  " + "\n  ".join(numeric_diffs[:8])
                )
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="F7 Fake numeric/structure bench")
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT, help="report.json path")
    parser.add_argument(
        "--baseline", type=Path, default=DEFAULT_BASELINE, help="baseline.json path"
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Rewrite committed baseline from this run (maintainer only)",
    )
    parser.add_argument("--rtol", type=float, default=DEFAULT_RTOL)
    parser.add_argument("--atol", type=float, default=DEFAULT_ATOL)
    parser.add_argument(
        "--no-check",
        action="store_true",
        help="Write report only; skip baseline comparison",
    )
    args = parser.parse_args(argv)

    report = _run_all(rtol=args.rtol, atol=args.atol)
    # Attach generated_at only on report (not baseline)
    from datetime import UTC, datetime

    report_out = dict(report)
    report_out["generated_at"] = datetime.now(UTC).isoformat()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report_out, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        f"wrote {args.output.relative_to(ROOT).as_posix()} "
        f"sequences={report['summary']['n_sequences']} "
        f"success={report['summary']['success_rate']:.6g} "
        f"precision={report['summary']['precision']:.6g} "
        f"elapsed_ms={report['summary']['elapsed_ms']:.1f}"
    )

    summary_lines = [
        "### F7 bench",
        f"- sequences: **{report['summary']['n_sequences']}**",
        f"- success_rate: **{report['summary']['success_rate']:.6g}**",
        f"- precision: **{report['summary']['precision']:.6g}**",
        f"- numeric fields: **{report['summary']['n_numeric_fields']}**",
        f"- elapsed_ms: **{report['summary']['elapsed_ms']:.1f}**",
    ]

    if args.update_baseline:
        baseline = _baseline_view(report)
        args.baseline.parent.mkdir(parents=True, exist_ok=True)
        args.baseline.write_text(
            json.dumps(baseline, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(f"updated baseline {args.baseline.relative_to(ROOT).as_posix()}")
        summary_lines.append("- baseline: **updated**")
        _write_step_summary(summary_lines)
        return 0

    if args.no_check:
        summary_lines.append("- check: **skipped**")
        _write_step_summary(summary_lines)
        return 0

    if not args.baseline.is_file():
        print(
            f"baseline missing: {args.baseline} (run with --update-baseline once)",
            file=sys.stderr,
        )
        summary_lines.append("- check: **FAIL** (baseline missing)")
        _write_step_summary(summary_lines)
        return 1

    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    failures = _compare_to_baseline(report, baseline, rtol=args.rtol, atol=args.atol)
    if failures:
        print("bench regression:", file=sys.stderr)
        for line in failures:
            print(f"  - {line}", file=sys.stderr)
        summary_lines.append(f"- check: **FAIL** ({len(failures)} issue(s))")
        _write_step_summary(summary_lines)
        return 1

    print("bench check: OK vs baseline")
    summary_lines.append("- check: **OK**")
    _write_step_summary(summary_lines)
    return 0


def _write_step_summary(lines: list[str]) -> None:
    """Best-effort GitHub Step Summary; never raises into main flow."""
    path = __import__("os").environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    except OSError:
        return


if __name__ == "__main__":
    raise SystemExit(main())
