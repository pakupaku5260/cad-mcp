"""Wave 7 param: part_parameters/update_parameters."""
from __future__ import annotations

from pathlib import Path

from cadmcp.backend.fake.backend import FakeBackend
from cadmcp.kernel import Kernel
from cadmcp.toolsets.core import core_registry


def _k(tmp_path: Path) -> Kernel:
    return Kernel(core_registry(), FakeBackend(), workspace=tmp_path, verify_mutations=True)


def _ok(k: Kernel, name: str, args: dict | None = None):
    r = k.dispatch(name, args or {})
    assert r.ok, f"{name}: {r.error}"
    return r


def test_part_parameters_reads_bundle(tmp_path: Path):
    k = _k(tmp_path)
    _ok(k, "new_part")
    _ok(k, "start_sketch", {"plane": "Front Plane"})
    _ok(k, "sketch_rectangle", {"x1": 0, "y1": 0, "x2": 40, "y2": 20})
    _ok(k, "end_sketch")
    _ok(k, "extrude", {"depth": 10})
    _ok(k, "set_equation", {"name": "D", "expression": "80"})
    r = _ok(k, "part_parameters")
    assert r.result["count"]["dimensions"] >= 1
    assert any(eq["name"] == "D" for eq in r.result["equations"])
    assert r.result["active_configuration"]
    assert r.result["configurations"]


def test_update_parameters_depth_and_equation(tmp_path: Path):
    k = _k(tmp_path)
    _ok(k, "new_part")
    _ok(k, "start_sketch", {"plane": "Front Plane"})
    _ok(k, "sketch_rectangle", {"x1": 0, "y1": 0, "x2": 40, "y2": 20})
    _ok(k, "end_sketch")
    _ok(k, "extrude", {"depth": 10})
    before = _ok(k, "get_geometry").result["volume"]
    dims = _ok(k, "list_dimensions").result["dimensions"]
    depth_name = next(d["name"] for d in dims if "Extrude" in d["name"] or "拉伸" in d["name"])
    r = _ok(
        k,
        "update_parameters",
        {
            "equations": [{"name": "D", "expression": "20"}],
            "dimensions": [{"name": depth_name, "value": 20}],
        },
    )
    assert r.result["failed"] is None
    assert len(r.result["applied"]) == 2
    assert r.delta is not None
    after = _ok(k, "get_geometry").result["volume"]
    assert after > before


def test_update_parameters_illegal_expression_no_partial(tmp_path: Path):
    k = _k(tmp_path)
    _ok(k, "new_part")
    _ok(k, "start_sketch", {"plane": "Front Plane"})
    _ok(k, "sketch_rectangle", {"x1": 0, "y1": 0, "x2": 10, "y2": 10})
    _ok(k, "end_sketch")
    _ok(k, "extrude", {"depth": 5})
    r = k.dispatch(
        "update_parameters",
        {"equations": [{"name": "D", "expression": "MsgBox(1)"}]},
    )
    assert not r.ok
    assert r.error.code == "INVALID_ARGUMENT"
    # No Partial Write: Equation is still empty or does not contain a D
    listed = _ok(k, "list_equations").result["equations"]
    assert not any(eq["name"] == "D" for eq in listed)


def test_update_parameters_empty_rejected(tmp_path: Path):
    k = _k(tmp_path)
    _ok(k, "new_part")
    r = k.dispatch("update_parameters", {})
    assert not r.ok and r.error.code == "INVALID_ARGUMENT"
