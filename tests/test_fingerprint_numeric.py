"""F7: optional numeric fingerprint block + tolerant diff."""

from __future__ import annotations

from cadmcp.consistency.fingerprint import (
    DEFAULT_ATOL,
    DEFAULT_RTOL,
    diff_fingerprints,
    extract_numeric,
    structural_fingerprint,
    values_close,
)
from cadmcp.result import Delta, GeometrySnapshot, ok_result


def _geo(**kwargs) -> GeometrySnapshot:
    defaults = dict(
        volume_mm3=1000.0,
        surface_area_mm2=600.0,
        mass_kg=0.0078,
        face_count=6,
        edge_count=12,
        bbox_mm=(0.0, 0.0, 0.0, 10.0, 10.0, 10.0),
    )
    defaults.update(kwargs)
    return GeometrySnapshot(**defaults)


def test_default_fingerprint_has_no_numeric_key():
    r = ok_result({"volume": 1000.0, "name": "Boss"}, state_version=1)
    fp = structural_fingerprint([("extrude", r)])
    assert "numeric" not in fp["steps"][0]
    assert set(fp["steps"][0]) == {
        "tool",
        "ok",
        "error_code",
        "error_side_effect",
        "result_keys",
        "delta_changed",
        "rebuild_ok",
        "state_version",
        "warning_count",
    }


def test_include_numeric_extracts_result_and_delta_whitelist():
    delta = Delta.between(_geo(), _geo(volume_mm3=2000.0, mass_kg=0.0156))
    r = ok_result(
        {"volume": 2000.0, "depth": 20.0, "name": "Boss", "face_count": 6},
        delta=delta,
        state_version=2,
    )
    fp = structural_fingerprint([("extrude", r)], include_numeric=True)
    numeric = fp["steps"][0]["numeric"]
    assert numeric is not None
    assert numeric["result"] == {"depth": 20.0, "volume": 2000.0}
    assert "face_count" not in numeric["result"]
    assert numeric["delta_after"]["volume_mm3"] == 2000.0
    assert "face_count" not in numeric["delta_after"]


def test_extract_numeric_null_when_no_whitelist_keys():
    r = ok_result({"name": "Boss", "unit": "mm"}, state_version=1)
    assert extract_numeric(r) is None
    fp = structural_fingerprint([("extrude", r)], include_numeric=True)
    assert fp["steps"][0]["numeric"] is None


def test_diff_ignores_numeric_when_absent_on_one_side():
    plain = structural_fingerprint([("extrude", ok_result({"volume": 1.0}, state_version=1))])
    with_num = structural_fingerprint(
        [("extrude", ok_result({"volume": 1.0}, state_version=1))],
        include_numeric=True,
    )
    assert not diff_fingerprints(plain, with_num)
    assert not diff_fingerprints(with_num, plain)


def test_diff_numeric_within_tolerance_passes():
    a = structural_fingerprint(
        [("get_geometry", ok_result({"volume": 1000.0, "bbox": [0, 0, 0, 10, 10, 10]}, state_version=1))],
        include_numeric=True,
    )
    b = structural_fingerprint(
        [
            (
                "get_geometry",
                ok_result(
                    {"volume": 1000.0 + 1e-10, "bbox": [0, 0, 0, 10, 10, 10 + 1e-12]},
                    state_version=1,
                ),
            )
        ],
        include_numeric=True,
    )
    assert not diff_fingerprints(a, b, rtol=DEFAULT_RTOL, atol=DEFAULT_ATOL)


def test_diff_numeric_beyond_tolerance_fails():
    a = structural_fingerprint(
        [("get_geometry", ok_result({"volume": 1000.0}, state_version=1))],
        include_numeric=True,
    )
    b = structural_fingerprint(
        [("get_geometry", ok_result({"volume": 1001.0}, state_version=1))],
        include_numeric=True,
    )
    diffs = diff_fingerprints(a, b)
    assert any("numeric.result.volume" in d for d in diffs)


def test_values_close_arrays():
    assert values_close([1.0, 2.0], [1.0, 2.0 + 1e-12])
    assert not values_close([1.0, 2.0], [1.0, 2.1])
