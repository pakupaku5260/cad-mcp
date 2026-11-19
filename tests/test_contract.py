"""Contract tests (v4 §17 W2-7): schema↔handler alignment, token budget, URI resolution, registry rules."""

from __future__ import annotations

import inspect
import json
import re

import jsonschema
import pytest

from cadmcp.registry import (
    DEFAULT_TOOLSET_BUDGET_TOKENS,
    NAME_PATTERN,
    PROFILE_TOKEN_BUDGETS,
    TIMEOUT_CLASSES,
    TOOLSET_BUDGET_TOKENS,
    TOOLSET_DEFS,
    TOTAL_TOKEN_BUDGET,
    ToolRegistry,
    ToolSpec,
    estimate_tokens,
    make_schema,
    spec_tokens,
    toolset_budget,
    toolset_headroom_cap,
)
from cadmcp.resources import RESOURCE_SCHEME, known_uris
from cadmcp.toolsets.core import core_registry

URI_RE = re.compile(rf"\b{re.escape(RESOURCE_SCHEME)}://[^\s'\"，。）)]+")


@pytest.fixture(scope="module")
def specs():
    return core_registry().all()


# ---------- Structure and grouping ----------


def test_all_tool_names_snake_case_and_unique(specs):
    names = [s.name for s in specs]
    assert len(names) == len(set(names))
    for n in names:
        assert NAME_PATTERN.match(n), n


# Still frozen: Toolbox (insert_bom/create_drawing unfrozen).
_STAGE_N_NON_TOOLS = frozenset({
    "sheet_metal",
    "insert_hole_wizard",
    "insert_toolbox", "insert_standard_part",
    "create_bolt", "insert_iso_bolt",
    "axial_feed", "screw_in",
})


def test_stage_n_nongoals_are_not_registered(specs):
    names = {s.name for s in specs}
    leaked = sorted(_STAGE_N_NON_TOOLS & names)
    assert not leaked, f"Stage N frozen tools registered: {leaked}"
    by_set: dict[str, int] = {}
    for s in specs:
        by_set[s.toolset] = by_set.get(s.toolset, 0) + 1
    # L1 views/BOM + section/dims/balloons + L3 sheets/GD&T/layers + weld×4
    assert by_set.get("drawing", 0) == 21  # + check_drawing_spec (F18)
    assert by_set.get("export", 0) == 2  # export + export_batch
    assert by_set.get("verification", 0) == 2  # verify_model + verify_step_readback (P5)
    assert by_set.get("sheetmetal", 0) == 8  # + calc_bend_allowance (F19)
    assert by_set.get("selection", 0) == 6  # faces/edges/vertices/select×2 + get_selection
    assert by_set.get("view", 0) == 2  # set_view + screenshot
    assert by_set.get("rules", 0) == 1  # check_rules
    assert by_set.get("assembly", 0) == 26  # + fix_components (P4); list_components_lite (P3); check_assembly_dof (F17)
    assert by_set.get("diagnostics", 0) == 1  # check_doctor_matrix (F20)
    assert by_set.get("design", 0) == 3  # + list_part_strategies (F21)
    assert len(TOOLSET_DEFS) == 15  # diagnostics (F20); F21 reuses design


def test_rules_tool_schema(specs):
    check = next(s for s in specs if s.name == "check_rules")
    assert check.toolset == "rules"
    assert check.mutating is False
    assert check.bypass_queue is True
    assert check.layer == "domain"
    assert check.timeout_class == "fast"
    props = check.input_schema["properties"]
    assert set(props) == {"rules"}
    assert check.input_schema.get("required") in (None, [])
    assert props["rules"]["default"] is None
    assert props["rules"]["type"] == ["array", "null"]


def test_check_assembly_dof_schema(specs):
    from cadmcp.registry import TOOLSET_PROFILES

    tool = next(s for s in specs if s.name == "check_assembly_dof")
    assert tool.toolset == "assembly"
    assert tool.mutating is False
    assert tool.bypass_queue is True
    assert tool.layer == "domain"
    assert tool.timeout_class == "fast"
    assert tool.input_schema.get("properties") == {}
    assert tool.input_schema.get("required") in (None, [])
    assert "assembly" in TOOLSET_PROFILES["full"]
    assert "assembly" in TOOLSET_PROFILES["assembly"]
    assert "assembly" not in TOOLSET_PROFILES["part"]


def test_check_drawing_spec_schema(specs):
    from cadmcp.registry import TOOLSET_PROFILES

    tool = next(s for s in specs if s.name == "check_drawing_spec")
    assert tool.toolset == "drawing"
    assert tool.mutating is False
    assert tool.bypass_queue is True
    assert tool.layer == "domain"
    assert tool.timeout_class == "fast"
    assert tool.input_schema.get("required") == ["spec_path"]
    assert set(tool.input_schema["properties"]) == {"spec_path"}
    assert "drawing" in TOOLSET_PROFILES["full"]
    assert "drawing" in TOOLSET_PROFILES["drawing"]
    assert "drawing" not in TOOLSET_PROFILES["part"]


def test_calc_bend_allowance_schema(specs):
    from cadmcp.registry import TOOLSET_PROFILES

    tool = next(s for s in specs if s.name == "calc_bend_allowance")
    assert tool.toolset == "sheetmetal"
    assert tool.mutating is False
    assert tool.bypass_queue is True
    assert tool.layer == "domain"
    assert tool.timeout_class == "fast"
    assert tool.input_schema.get("required") == ["bends", "thickness"]
    props = tool.input_schema["properties"]
    assert set(props) == {"bends", "thickness", "k_factor", "unit"}
    assert props["k_factor"]["default"] == 0.5
    assert "sheetmetal" in TOOLSET_PROFILES["full"]
    assert "sheetmetal" in TOOLSET_PROFILES["sheetmetal"]
    assert "sheetmetal" not in TOOLSET_PROFILES["part"]


def test_check_doctor_matrix_schema(specs):
    from cadmcp.registry import TOOLSET_PROFILES

    tool = next(s for s in specs if s.name == "check_doctor_matrix")
    assert tool.toolset == "diagnostics"
    assert tool.mutating is False
    assert tool.bypass_queue is True
    assert tool.layer == "domain"
    assert tool.timeout_class == "fast"
    assert tool.input_schema.get("required") == ["report"]
    assert set(tool.input_schema["properties"]) == {"report"}
    assert "diagnostics" in TOOLSET_PROFILES["full"]
    assert "diagnostics" not in TOOLSET_PROFILES["part"]
    assert "diagnostics" not in TOOLSET_PROFILES["drawing"]
    assert "diagnostics" not in TOOLSET_PROFILES["sheetmetal"]
    assert "diagnostics" not in TOOLSET_PROFILES["assembly"]
    assert TOOLSET_BUDGET_TOKENS["diagnostics"] == 4000
    assert toolset_headroom_cap("diagnostics") == 3200


def test_list_part_strategies_schema(specs):
    from cadmcp.registry import TOOLSET_PROFILES, spec_tokens

    tool = next(s for s in specs if s.name == "list_part_strategies")
    assert tool.toolset == "design"
    assert tool.mutating is False
    assert tool.bypass_queue is True
    assert tool.layer == "domain"
    assert tool.timeout_class == "fast"
    assert tool.input_schema.get("required") in (None, [])
    props = tool.input_schema["properties"]
    assert set(props) == {"part_type"}
    assert props["part_type"]["default"] is None
    assert props["part_type"]["type"] == ["string", "null"]
    assert "design" in TOOLSET_PROFILES["full"]
    assert "design" in TOOLSET_PROFILES["part"]
    assert spec_tokens(tool) <= 300


def test_f16_budget_constants():
    assert TOTAL_TOKEN_BUDGET == 25000
    assert PROFILE_TOKEN_BUDGETS["part"] == 17000
    assert TOOLSET_BUDGET_TOKENS["rules"] == 4000
    assert TOOLSET_BUDGET_TOKENS["core"] == 6500
    assert toolset_headroom_cap("rules") == 3200
    assert toolset_headroom_cap("core") == 5200


def test_toolset_and_timeout_class_are_declared(specs):
    for s in specs:
        assert s.toolset in TOOLSET_DEFS, s.name
        assert s.timeout_class in TIMEOUT_CLASSES, s.name


def test_layer_is_declared(specs):
    from cadmcp.registry import TOOL_LAYERS

    for s in specs:
        assert s.layer in TOOL_LAYERS, s.name
        assert "layer" not in (s.input_schema.get("properties") or {}), s.name
    task_names = {s.name for s in specs if s.layer == "task"}
    assert task_names == {"batch", "design_run", "fix_components", "task_list", "task_status"}


def test_design_run_variant_is_optional_additive(specs):
    design_run = next(s for s in specs if s.name == "design_run")
    props = design_run.input_schema["properties"]
    assert set(props) >= {"spec_path", "stop_on_error", "resume_from", "variant"}
    assert design_run.input_schema.get("required") == ["spec_path"]
    assert props["stop_on_error"]["default"] is True
    assert props["resume_from"]["default"] is None
    assert props["variant"]["default"] is None
    assert props["variant"]["type"] == ["string", "null"]


def test_verify_delta_implies_mutating(specs):
    for s in specs:
        if s.verify_delta:
            assert s.mutating, f"{s.name} verify_delta but not mutating"


def test_every_object_schema_forbids_additional_properties(specs):
    def walk(schema: dict, where: str):
        if schema.get("type") == "object":
            assert schema.get("additionalProperties") is False, f"{where} missing additionalProperties:false"
        for key in ("properties",):
            for pname, sub in (schema.get(key) or {}).items():
                walk(sub, f"{where}.{pname}")

    for s in specs:
        walk(s.input_schema, s.name)


def test_schemas_are_valid_against_metaschema(specs):
    for s in specs:
        jsonschema.Draft202012Validator.check_schema(s.input_schema)


# ---------- schema ↔ handler alignment ----------


def test_signature_matches_schema_properties_exactly(specs):
    for s in specs:
        params = inspect.signature(s.handler).parameters
        assert set(params) - {"ctx", "self"} == set(s.input_schema["properties"]), s.name


def test_required_matches_signature_defaults(specs):
    for s in specs:
        params = inspect.signature(s.handler).parameters
        required = set(s.input_schema.get("required", []))
        assert required <= set(s.input_schema["properties"]), s.name
        for pname, p in params.items():
            if pname in ("ctx", "self"):
                continue
            has_default = p.default is not inspect.Parameter.empty
            if has_default:
                assert pname not in required, f"{s.name}.{pname} default but required"
            else:
                assert pname in required, f"{s.name}.{pname} no default, not required"


def test_schema_defaults_match_signature_defaults(specs):
    for s in specs:
        params = inspect.signature(s.handler).parameters
        for pname, prop in s.input_schema["properties"].items():
            if "default" in prop:
                assert prop["default"] == params[pname].default, f"{s.name}.{pname}"


# ---------- Description quality and budget ----------


def test_descriptions_present_and_budget_within_limit(specs):
    for s in specs:
        assert s.description.strip(), s.name
    assert set(TOOLSET_BUDGET_TOKENS) == set(TOOLSET_DEFS)
    assert DEFAULT_TOOLSET_BUDGET_TOKENS == 4000
    for toolset in {s.toolset for s in specs}:
        total = sum(spec_tokens(s) for s in specs if s.toolset == toolset)
        tier = toolset_budget(toolset)
        cap20 = toolset_headroom_cap(toolset)
        assert total <= tier, f"{toolset} over tier {tier}: {total}"
        assert total <= cap20, f"{toolset} exceeds 20% headroom cap {cap20}: {total}"


def test_toolset_budget_unknown_falls_back_to_default():
    assert toolset_budget("no_such_toolset") == DEFAULT_TOOLSET_BUDGET_TOKENS


def test_headroom_cap_matches_tier_ratio():
    assert toolset_headroom_cap("core") == 5200
    assert toolset_headroom_cap("features_adv") == 4800
    assert toolset_headroom_cap("drawing") == 3200


def test_strict_report_fails_when_over_headroom(monkeypatch):
    """`token_report --strict` must exit 1 when a toolset exceeds its 20% cap."""
    from scripts import token_report

    # Core (4550) exceeds a synthetic 4000 headroom cap while staying under the tier.
    monkeypatch.setattr(token_report, "toolset_budget", lambda name: 5000)
    monkeypatch.setattr(token_report, "toolset_headroom_cap", lambda name: 4000)
    assert token_report.main(["--strict"]) == 1

    monkeypatch.setattr(token_report, "toolset_budget", lambda name: 1_000_000)
    monkeypatch.setattr(token_report, "toolset_headroom_cap", lambda name: 1_000_000)
    assert token_report.main(["--strict"]) == 0


def test_estimate_tokens_handles_cjk():
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("建立立方体") == 5


def test_resource_uris_in_descriptions_are_registered(specs):
    for s in specs:
        for uri in URI_RE.findall(s.description + json.dumps(s.input_schema, ensure_ascii=False)):
            assert uri in known_uris(), f"{s.name} unregistered resource {uri}"


# ---------- Registry discipline ----------


def _toy(name: str = "toy_tool") -> ToolSpec:
    return ToolSpec(name=name, description="toy", input_schema=make_schema({}),
                    handler=lambda ctx: {})


def test_registry_rejects_duplicates_unknown_toolset_bad_name():
    reg = ToolRegistry()
    reg.register(_toy())
    with pytest.raises(ValueError, match="Duplicate tool registration"):
        reg.register(_toy())
    with pytest.raises(ValueError, match="Unknown toolset"):
        reg.register(ToolSpec(name="toy2", description="t", input_schema=make_schema({}),
                              handler=lambda ctx: {}, toolset="nope"))
    with pytest.raises(ValueError, match="Invalid tool name"):
        reg.register(_toy("BadName"))
    with pytest.raises(ValueError, match="must be object"):
        reg.register(ToolSpec(name="toy3", description="t",
                              input_schema={"type": "array"}, handler=lambda ctx: {}))
