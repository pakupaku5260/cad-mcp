"""F19: pure bend-allowance estimate (no model / unfold / bend table)."""
from __future__ import annotations

import math
from pathlib import Path

from cadmcp.backend.fake import FakeBackend
from cadmcp.kernel import Kernel
from cadmcp.sheetmetal_calc import (
    ASSUMPTIONS,
    BEND_CHECKS,
    assess,
    bend_allowance_m,
    evaluate,
)
from cadmcp.toolsets.core import core_registry
from cadmcp.units import UnitContext

_STD_BA = bend_allowance_m(90.0, 0.01, 0.002, 0.5)  # radians(90)×(0.01+0.001)


def _kernel(tmp_path: Path) -> Kernel:
    return Kernel(
        backend=FakeBackend(),
        units=UnitContext("mm"),
        workspace=tmp_path,
        registry=core_registry(),
    )


def test_bend_checks_count_and_names():
    assert len(BEND_CHECKS) == 6
    assert [c.name for c in BEND_CHECKS] == [
        "thickness_positive",
        "k_factor_in_range",
        "bends_nonempty",
        "angles_in_range",
        "radii_nonnegative",
        "values_finite",
    ]


def test_standard_ba_formula():
    expected = math.radians(90.0) * (0.01 + 0.5 * 0.002)
    assert math.isclose(_STD_BA, expected, rel_tol=0.0, abs_tol=1e-15)
    assert math.isclose(_STD_BA, math.pi / 2.0 * 0.011, rel_tol=0.0, abs_tol=1e-15)


def test_evaluate_pass_and_assess_payload():
    bends = [{"angle_deg": 90.0, "radius": 0.01}]
    checks, allowances = evaluate(0.002, 0.5, bends)
    assert all(c.ok for c in checks)
    assert len(allowances) == 1
    assert math.isclose(allowances[0]["bend_allowance"], _STD_BA, abs_tol=1e-15)
    payload = assess(0.002, 0.5, bends)
    assert set(payload) == {
        "status",
        "verification",
        "bend_allowances",
        "total_bend_allowance",
        "unit",
        "assumptions",
        "risk",
    }
    assert payload["status"] == "verified"
    assert payload["risk"] == "unverified"
    assert payload["unit"] == "m"
    assert payload["assumptions"] == list(ASSUMPTIONS)
    assert math.isclose(payload["total_bend_allowance"], _STD_BA, abs_tol=1e-15)


def test_fail_thickness_nonpositive():
    checks, allowances = evaluate(0.0, 0.5, [{"angle_deg": 90.0, "radius": 0.01}])
    by_name = {c.name: c for c in checks}
    assert by_name["thickness_positive"].ok is False
    assert allowances == []


def test_fail_k_factor_out_of_range():
    checks, allowances = evaluate(0.002, 1.0, [{"angle_deg": 90.0, "radius": 0.01}])
    by_name = {c.name: c for c in checks}
    assert by_name["k_factor_in_range"].ok is False
    assert allowances == []


def test_fail_bends_empty():
    checks, allowances = evaluate(0.002, 0.5, [])
    by_name = {c.name: c for c in checks}
    assert by_name["bends_nonempty"].ok is False
    assert allowances == []
    assert assess(0.002, 0.5, [])["status"] == "failed"


def test_fail_angle_out_of_range():
    checks, allowances = evaluate(0.002, 0.5, [{"angle_deg": 0.0, "radius": 0.01}])
    by_name = {c.name: c for c in checks}
    assert by_name["angles_in_range"].ok is False
    assert allowances == []


def test_fail_radius_negative():
    checks, allowances = evaluate(0.002, 0.5, [{"angle_deg": 90.0, "radius": -0.001}])
    by_name = {c.name: c for c in checks}
    assert by_name["radii_nonnegative"].ok is False
    assert allowances == []


def test_fail_nonfinite():
    checks, allowances = evaluate(
        0.002, 0.5, [{"angle_deg": float("nan"), "radius": 0.01}]
    )
    by_name = {c.name: c for c in checks}
    assert by_name["values_finite"].ok is False
    assert allowances == []


def test_multi_bend_total():
    bends = [
        {"angle_deg": 90.0, "radius": 0.01},
        {"angle_deg": 45.0, "radius": 0.005},
    ]
    checks, allowances = evaluate(0.002, 0.5, bends)
    assert all(c.ok for c in checks)
    assert len(allowances) == 2
    ba0 = bend_allowance_m(90.0, 0.01, 0.002, 0.5)
    ba1 = bend_allowance_m(45.0, 0.005, 0.002, 0.5)
    total = assess(0.002, 0.5, bends)["total_bend_allowance"]
    assert math.isclose(total, ba0 + ba1, abs_tol=1e-15)


def test_tool_unit_conversion_and_readonly(tmp_path: Path):
    k = _kernel(tmp_path)
    before = k.state_version
    result = k.dispatch(
        "calc_bend_allowance",
        {
            "thickness": 2.0,
            "k_factor": 0.5,
            "bends": [{"angle_deg": 90.0, "radius": 10.0}],
            "unit": "mm",
        },
    )
    assert result.ok
    assert k.state_version == before
    payload = result.result
    assert set(payload) == {
        "status",
        "verification",
        "bend_allowances",
        "total_bend_allowance",
        "unit",
        "assumptions",
        "risk",
    }
    assert payload["status"] == "verified"
    assert payload["unit"] == "mm"
    # SI BA → mm
    expected_mm = _STD_BA * 1000.0
    assert math.isclose(payload["total_bend_allowance"], expected_mm, rel_tol=1e-12)
    assert math.isclose(
        payload["bend_allowances"][0]["bend_allowance"], expected_mm, rel_tol=1e-12
    )
    assert math.isclose(payload["bend_allowances"][0]["radius"], 10.0, abs_tol=1e-12)


def test_tool_does_not_overlap_unfold_or_bend_table(tmp_path: Path):
    k = _kernel(tmp_path)
    # No active document: unfold / bend_table would fail; calc must still work.
    result = k.dispatch(
        "calc_bend_allowance",
        {
            "thickness": 2.0,
            "bends": [{"angle_deg": 90.0, "radius": 10.0}],
        },
    )
    assert result.ok
    assert result.result["status"] == "verified"
    unfold = k.dispatch("sheet_metal_unfold", {})
    assert unfold.ok is False
    table = k.dispatch("sheet_metal_bend_table", {})
    assert table.ok is False


def test_failed_checks_yield_empty_ba_via_tool(tmp_path: Path):
    k = _kernel(tmp_path)
    result = k.dispatch(
        "calc_bend_allowance",
        {
            "thickness": -1.0,
            "bends": [{"angle_deg": 90.0, "radius": 10.0}],
        },
    )
    assert result.ok  # outer OpResult unchanged
    assert result.result["status"] == "failed"
    assert result.result["bend_allowances"] == []
    assert result.result["total_bend_allowance"] == 0.0
