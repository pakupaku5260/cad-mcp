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
    TIMEOUT_CLASSES,
    TOOLSET_DEFS,
    ToolRegistry,
    ToolSpec,
    estimate_tokens,
    make_schema,
    spec_tokens,
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
    # L1 views/BOM + section/dims/balloons + L3 sheets/GD&T + layers
    assert by_set.get("drawing", 0) == 16
    assert by_set.get("export", 0) == 1
    assert by_set.get("sheetmetal", 0) == 7
    assert by_set.get("selection", 0) == 6  # faces/edges/vertices/select×2 + get_selection
    assert by_set.get("view", 0) == 2  # set_view + screenshot


def test_toolset_and_timeout_class_are_declared(specs):
    for s in specs:
        assert s.toolset in TOOLSET_DEFS, s.name
        assert s.timeout_class in TIMEOUT_CLASSES, s.name


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
    for toolset in {s.toolset for s in specs}:
        total = sum(spec_tokens(s) for s in specs if s.toolset == toolset)
        assert total <= DEFAULT_TOOLSET_BUDGET_TOKENS, f"{toolset} over budget: {total}"


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
