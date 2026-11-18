"""F17: heuristic assembly DOF estimate."""
from __future__ import annotations

from pathlib import Path

from cadmcp.assembly_dof import (
    ASSUMPTIONS,
    MATE_DOF,
    assembly_order,
    assess,
    estimate_dof,
    not_applicable_payload,
)
from cadmcp.backend.fake import FakeBackend
from cadmcp.kernel import Kernel
from cadmcp.toolsets.core import core_registry
from cadmcp.units import UnitContext


def _kernel(tmp_path: Path) -> Kernel:
    return Kernel(
        backend=FakeBackend(),
        units=UnitContext("mm"),
        workspace=tmp_path,
        registry=core_registry(),
    )


def test_mate_dof_weights():
    assert MATE_DOF == {
        "coincident": 3,
        "concentric": 4,
        "distance": 1,
        "angle": 1,
        "tangent": 1,
        "screw": 2,
    }


def test_remaining_formula_and_floor():
    comps = ["a", "b"]
    mates = [{"name": "M1", "mate_type": "coincident"}]
    out = estimate_dof(comps, mates)
    assert out["total_dof"] == 12
    assert out["constrained"] == 3
    assert out["remaining"] == 9
    assert out["basis"] == "mate_type_heuristic"
    # Heavy constraints clamp at zero
    heavy = [{"name": f"M{i}", "mate_type": "concentric"} for i in range(10)]
    clamped = estimate_dof(["a"], heavy)
    assert clamped["total_dof"] == 6
    assert clamped["constrained"] == 40
    assert clamped["remaining"] == 0


def test_unknown_mate_type():
    out = estimate_dof(
        ["a", "b"],
        [
            {"name": "M1", "mate_type": "coincident"},
            {"name": "M2", "mate_type": "magic"},
            {"name": "M3", "mate_type": "magic"},
        ],
    )
    assert out["constrained"] == 3
    assert out["unknown_mate_types"] == ["magic"]
    assert out["mates"][1]["constrained_dof"] is None
    assert out["mates"][2]["constrained_dof"] is None


def test_unmated_coarse_deficit():
    # n=3, mates=0 → deficit max(0, 3-1-0)=2
    assert estimate_dof(["a", "b", "c"], [])["unmated_components"] == 2
    # n=3, mates=2 → tree-complete proxy → 0
    mates = [
        {"name": "M1", "mate_type": "distance"},
        {"name": "M2", "mate_type": "distance"},
    ]
    assert estimate_dof(["a", "b", "c"], mates)["unmated_components"] == 0


def test_assembly_order_preserves_enumeration():
    order = assembly_order(["z-1", "a-1", "m-1"])
    assert order == {
        "order": ["z-1", "a-1", "m-1"],
        "basis": "component_enumeration_order",
    }


def test_assess_assumptions_and_risk():
    payload = assess(
        ["p1-1", "p1-2"],
        [{"name": "Coincident1", "mate_type": "coincident"}],
    )
    assert payload["status"] == "ok"
    assert payload["risk"] == "unverified"
    assert payload["assumptions"] == list(ASSUMPTIONS)
    assert "heuristic, not a true SolidWorks DOF solver" in payload["assumptions"]
    assert set(payload) == {
        "status",
        "verification",
        "dof_estimate",
        "assembly_order",
        "mates",
        "unknown_mate_types",
        "assumptions",
        "risk",
    }
    v = payload["verification"]
    names = {c["name"]: c["ok"] for c in v["checks"]}
    assert names["components_present"] is True
    assert names["mates_present"] is True
    assert names["all_mate_types_known"] is True
    assert v["status"] == "verified"
    assert payload["dof_estimate"]["constrained"] == 3
    assert payload["assembly_order"]["order"] == ["p1-1", "p1-2"]


def test_empty_assembly_unverified():
    payload = not_applicable_payload(reason="assembly has no components")
    assert payload["status"] == "not_applicable"
    assert payload["verification"]["status"] == "unverified"
    assert payload["verification"]["checks"] == []
    assert payload["risk"] == "unverified"


def test_check_assembly_dof_non_assembly(tmp_path: Path):
    k = _kernel(tmp_path)
    assert k.dispatch("new_part", {}).ok
    sv = k.state_version
    r = k.dispatch("check_assembly_dof", {})
    assert r.ok
    assert k.state_version == sv
    assert r.result is not None
    assert r.result["status"] == "not_applicable"
    assert r.result["risk"] == "unverified"
    assert "facts" not in r.result


def test_check_assembly_dof_two_components_one_mate(tmp_path: Path):
    k = _kernel(tmp_path)
    assert k.dispatch("new_part", {}).ok
    assert k.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert k.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 20, "y2": 20}).ok
    assert k.dispatch("end_sketch", {}).ok
    assert k.dispatch("extrude", {"depth": 10}).ok
    assert k.dispatch("save_document", {"path": "p1.sldprt"}).ok
    assert k.dispatch("close_document", {"discard": True}).ok
    assert k.dispatch("new_assembly", {}).ok
    assert k.dispatch("insert_component", {"path": "p1.sldprt"}).ok
    assert k.dispatch("insert_component", {"path": "p1.sldprt", "x": 40}).ok
    assert k.dispatch(
        "mate",
        {
            "type": "coincident",
            "entity1": "Top Plane@p1-1",
            "entity2": "Top Plane@p1-2",
        },
    ).ok
    sv = k.state_version
    r = k.dispatch("check_assembly_dof", {})
    assert r.ok
    assert k.state_version == sv
    payload = r.result
    assert payload is not None
    assert payload["status"] == "ok"
    assert payload["dof_estimate"]["total_dof"] == 12
    assert payload["dof_estimate"]["constrained"] == 3
    assert payload["dof_estimate"]["remaining"] == 9
    assert payload["mates"][0]["mate_type"] == "coincident"
    assert payload["mates"][0]["constrained_dof"] == 3
    assert payload["assembly_order"]["order"] == ["p1-1", "p1-2"]
    assert payload["risk"] == "unverified"


def test_tool_registration_and_profiles():
    from cadmcp.registry import TOOLSET_PROFILES

    specs = core_registry().all()
    tool = next(s for s in specs if s.name == "check_assembly_dof")
    assert tool.toolset == "assembly"
    assert tool.mutating is False
    assert tool.bypass_queue is True
    assert tool.layer == "domain"
    assert tool.timeout_class == "fast"
    assert tool.input_schema.get("required") in (None, [])
    assert "assembly" in TOOLSET_PROFILES["full"]
    assert "assembly" in TOOLSET_PROFILES["assembly"]
    assert "assembly" not in TOOLSET_PROFILES["part"]
