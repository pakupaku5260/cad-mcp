"""F16: machine-checkable rules + check_rules tool."""
from __future__ import annotations

from pathlib import Path

import pytest

from cadmcp.backend.fake import FakeBackend
from cadmcp.errors import CadMcpError
from cadmcp.kernel import Kernel
from cadmcp.rules import RULES, evaluate_rules
from cadmcp.toolsets.core import core_registry
from cadmcp.units import UnitContext


def _kernel(tmp_path: Path) -> Kernel:
    return Kernel(
        backend=FakeBackend(),
        units=UnitContext("mm"),
        workspace=tmp_path,
        registry=core_registry(),
    )


def _base_doc(**overrides):
    doc = {
        "title": "Part1",
        "path": None,
        "doc_type": "part",
        "modified": False,
        "units": "mm",
        "configuration": "Default",
        "epoch": "e1",
        "saved": True,
    }
    doc.update(overrides)
    return doc


def _params(**overrides):
    payload = {
        "dimensions": [{"name": "D1@Boss", "kind": "length", "value": 10.0, "unit": "mm"}],
        "equations": [{"name": "D", "expression": "80"}],
        "active_configuration": "Default",
        "configurations": ["Default"],
        "count": {"dimensions": 1, "equations": 1, "configurations": 1},
    }
    payload.update(overrides)
    return payload


def test_rules_count_and_names():
    assert len(RULES) == 10
    assert [r.name for r in RULES] == [
        "active_document",
        "units_declared",
        "feature_tree_present",
        "positive_dimensions",
        "equations_nonempty",
        "configuration_present",
        "sketches_constrained",
        "no_unsaved_edits",
        "no_interference",
        "document_saved",
    ]


@pytest.mark.parametrize(
    "name,facts,expect_ok,expect_skip",
    [
        ("active_document", {"active_document": _base_doc()}, True, False),
        ("active_document", {}, None, True),
        ("units_declared", {"active_document": _base_doc(units="mm")}, True, False),
        ("units_declared", {"active_document": _base_doc(units="cm")}, False, False),
        (
            "feature_tree_present",
            {
                "active_document": _base_doc(),
                "features": {"features": [{"name": "Boss-Extrude1", "kind": "extrude"}]},
            },
            True,
            False,
        ),
        (
            "feature_tree_present",
            {"active_document": _base_doc(), "features": {"features": []}},
            False,
            False,
        ),
        (
            "feature_tree_present",
            {"active_document": _base_doc(doc_type="drawing"), "features": {"features": []}},
            None,
            True,
        ),
        ("positive_dimensions", {"part_parameters": _params()}, True, False),
        (
            "positive_dimensions",
            {
                "part_parameters": _params(
                    dimensions=[{"name": "D1", "kind": "length", "value": 0, "unit": "mm"}]
                )
            },
            False,
            False,
        ),
        ("equations_nonempty", {"part_parameters": _params()}, True, False),
        (
            "equations_nonempty",
            {"part_parameters": _params(equations=[{"name": "D", "expression": ""}])},
            False,
            False,
        ),
        ("configuration_present", {"part_parameters": _params()}, True, False),
        (
            "configuration_present",
            {"part_parameters": _params(configurations=[], count={"dimensions": 0, "equations": 0, "configurations": 0})},
            False,
            False,
        ),
        (
            "sketches_constrained",
            {"sketch_statuses": [{"state": "fully_defined", "dof": 0, "sketch": "Sketch1"}]},
            True,
            False,
        ),
        (
            "sketches_constrained",
            {"sketch_statuses": [{"state": "under_defined", "dof": None, "sketch": "Sketch1"}]},
            False,
            False,
        ),
        ("sketches_constrained", {}, None, True),
        ("no_unsaved_edits", {"active_document": _base_doc(modified=False)}, True, False),
        ("no_unsaved_edits", {"active_document": _base_doc(modified=True)}, False, False),
        (
            "no_interference",
            {
                "active_document": _base_doc(doc_type="assembly"),
                "interference": {"count": 0, "pairs": [], "method": "aabb"},
            },
            True,
            False,
        ),
        (
            "no_interference",
            {
                "active_document": _base_doc(doc_type="assembly"),
                "interference": {
                    "count": 1,
                    "pairs": [{"a": "A", "b": "B", "status": "interfere"}],
                    "method": "aabb",
                },
            },
            False,
            False,
        ),
        ("no_interference", {"active_document": _base_doc(doc_type="part")}, None, True),
        ("document_saved", {"active_document": _base_doc(saved=True)}, True, False),
        ("document_saved", {"active_document": _base_doc(saved=False)}, False, False),
    ],
)
def test_each_rule_pass_fail_skip(name, facts, expect_ok, expect_skip):
    checks, skipped = evaluate_rules(facts, [name])
    if expect_skip:
        assert checks == []
        assert len(skipped) == 1
        assert skipped[0]["name"] == name
        assert skipped[0]["reason"]
    else:
        assert skipped == []
        assert len(checks) == 1
        assert checks[0].name == name
        assert checks[0].ok is expect_ok


def test_subset_filter_and_unknown_name():
    facts = {"active_document": _base_doc()}
    checks, skipped = evaluate_rules(facts, ["units_declared", "document_saved"])
    assert [c.name for c in checks] == ["units_declared", "document_saved"]
    assert skipped == []
    with pytest.raises(CadMcpError) as ei:
        evaluate_rules(facts, ["units_declared", "no_such_rule"])
    assert ei.value.code == "INVALID_ARGUMENT"


def test_empty_facts_all_skipped():
    checks, skipped = evaluate_rules({})
    assert checks == []
    assert len(skipped) == 10
    assert {s["name"] for s in skipped} == {r.name for r in RULES}


def test_check_rules_payload_keys_and_readonly(tmp_path: Path):
    k = _kernel(tmp_path)
    sv0 = k.state_version
    r = k.dispatch("check_rules", {})
    assert r.ok
    assert r.result is not None
    assert set(r.result) == {"verification", "rules_run", "skipped"}
    assert "facts" not in r.result
    assert "state_version" not in r.result
    assert k.state_version == sv0
    assert len(r.result["rules_run"]) == 10
    v = r.result["verification"]
    assert set(v) >= {"status", "checks", "evidence"}
    # No active doc → all skipped → unverified
    assert r.result["skipped"]
    assert v["status"] == "unverified"
    assert v["checks"] == []


def test_check_rules_after_modeling(tmp_path: Path):
    k = _kernel(tmp_path)
    assert k.dispatch("new_part", {}).ok
    assert k.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert k.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 40, "y2": 20}).ok
    assert k.dispatch("end_sketch", {}).ok
    assert k.dispatch("extrude", {"depth": 10}).ok
    sv = k.state_version
    r = k.dispatch("check_rules", {"rules": ["active_document", "units_declared", "no_interference"]})
    assert r.ok
    assert k.state_version == sv
    assert r.result["rules_run"] == ["active_document", "units_declared", "no_interference"]
    names = {c["name"] for c in r.result["verification"]["checks"]}
    skip_names = {s["name"] for s in r.result["skipped"]}
    assert "active_document" in names
    assert "units_declared" in names
    assert "no_interference" in skip_names


def test_check_rules_unknown_name(tmp_path: Path):
    k = _kernel(tmp_path)
    r = k.dispatch("check_rules", {"rules": ["nope"]})
    assert not r.ok
    assert r.error is not None
    assert r.error.code == "INVALID_ARGUMENT"


def test_rules_toolset_registration():
    from cadmcp.registry import TOOLSET_BUDGET_TOKENS, TOOLSET_DEFS, TOOLSET_PROFILES

    assert "rules" in TOOLSET_DEFS
    assert TOOLSET_BUDGET_TOKENS["rules"] == 4000
    assert "rules" in TOOLSET_PROFILES["part"]
    assert "rules" in TOOLSET_PROFILES["full"]
    assert "rules" not in TOOLSET_PROFILES["assembly"]
    specs = core_registry().all()
    check = next(s for s in specs if s.name == "check_rules")
    assert check.toolset == "rules"
    assert check.mutating is False
    assert check.bypass_queue is True
    assert check.layer == "domain"
    assert check.timeout_class == "fast"
