"""F7 bench regression helpers (offline)."""

from __future__ import annotations

from cadmcp.consistency.fingerprint import diff_fingerprints, structural_fingerprint
from cadmcp.result import ok_result
from scripts.bench import PRECISION_FLOOR, _baseline_view, _compare_to_baseline, _run_all


def test_compare_detects_numeric_regression():
    good = structural_fingerprint(
        [("get_geometry", ok_result({"volume": 1000.0}, state_version=1))],
        include_numeric=True,
    )
    bad = structural_fingerprint(
        [("get_geometry", ok_result({"volume": 999.0}, state_version=1))],
        include_numeric=True,
    )
    baseline = {
        "schema_version": 1,
        "sequences": {
            "toy": {
                "success_rate": 1.0,
                "fingerprint": good,
            }
        },
    }
    report = {
        "schema_version": 1,
        "sequences": {
            "toy": {
                "success_rate": 1.0,
                "fingerprint": bad,
            }
        },
    }
    failures = _compare_to_baseline(report, baseline, rtol=1e-6, atol=1e-9)
    assert failures
    assert any("precision" in f or "numeric" in f for f in failures)
    assert PRECISION_FLOOR == 1.0


def test_compare_detects_success_rate_drop():
    fp = structural_fingerprint(
        [("new_part", ok_result({"title": "Part1"}, state_version=1))],
        include_numeric=True,
    )
    baseline = {
        "schema_version": 1,
        "sequences": {"toy": {"success_rate": 1.0, "fingerprint": fp}},
    }
    report = {
        "schema_version": 1,
        "sequences": {"toy": {"success_rate": 0.5, "fingerprint": fp}},
    }
    failures = _compare_to_baseline(report, baseline, rtol=1e-6, atol=1e-9)
    assert any("success_rate declined" in f for f in failures)


def test_baseline_view_strips_elapsed():
    report = _run_all(rtol=1e-6, atol=1e-9)
    view = _baseline_view(report)
    assert "elapsed_ms" not in view["summary"]
    assert "generated_at" not in view
    name = next(iter(view["sequences"]))
    assert "elapsed_ms" not in view["sequences"][name]
    assert "fingerprint" in view["sequences"][name]
    # structural+numeric diffs vs self are empty
    fp = view["sequences"][name]["fingerprint"]
    assert not diff_fingerprints(fp, fp)
