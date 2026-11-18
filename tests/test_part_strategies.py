"""F21: part-type strategy catalog (data only; does not run recipes)."""
from __future__ import annotations

from pathlib import Path

from cadmcp.backend.fake import FakeBackend
from cadmcp.kernel import Kernel
from cadmcp.part_strategies import (
    PART_STRATEGIES,
    get_part_strategy,
    list_part_strategies,
)
from cadmcp.recipe import load_recipe
from cadmcp.registry import spec_tokens
from cadmcp.toolsets.core import core_registry
from cadmcp.units import UnitContext

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _kernel(tmp_path: Path) -> Kernel:
    return Kernel(
        backend=FakeBackend(),
        units=UnitContext("mm"),
        workspace=tmp_path,
        registry=core_registry(),
    )


def test_catalog_four_unique_ids_and_types():
    assert len(PART_STRATEGIES) == 4
    ids = [s["id"] for s in PART_STRATEGIES]
    types = [s["part_type"] for s in PART_STRATEGIES]
    assert ids == ["plate", "box", "fillet_pattern", "surface_thicken"]
    assert types == ids
    assert len(set(ids)) == 4


def test_list_all_and_filter_and_unknown():
    all_rows = list_part_strategies()
    assert len(all_rows) == 4
    assert {r["id"] for r in all_rows} == {
        "plate",
        "box",
        "fillet_pattern",
        "surface_thicken",
    }
    plates = list_part_strategies("plate")
    assert len(plates) == 1 and plates[0]["id"] == "plate"
    assert list_part_strategies("no_such_type") == []
    assert get_part_strategy("box")["source_recipe"] == "examples/box_recipe.json"
    assert get_part_strategy("missing") is None


def test_source_recipes_exist_and_load():
    for row in PART_STRATEGIES:
        path = _REPO_ROOT / row["source_recipe"]
        assert path.is_file(), row["source_recipe"]
        recipe = load_recipe(path)
        assert isinstance(recipe.get("steps"), list) and recipe["steps"]


def test_feature_tools_are_registered():
    registry = core_registry()
    registered = {s.name for s in registry}
    for row in PART_STRATEGIES:
        for tool in row["feature_tools"]:
            assert tool in registered, f"{row['id']}: unregistered {tool}"


def test_surface_thicken_requires_features_adv():
    row = get_part_strategy("surface_thicken")
    assert row is not None
    assert "features_adv" in row["required_toolsets"]


def test_tool_readonly_payload(tmp_path: Path):
    k = _kernel(tmp_path)
    before = k.state_version
    result = k.dispatch("list_part_strategies", {})
    assert result.ok
    assert k.state_version == before
    payload = result.result
    assert set(payload) == {"ok", "strategies", "count"}
    assert payload["ok"] is True
    assert payload["count"] == 4
    assert len(payload["strategies"]) == 4
    filtered = k.dispatch("list_part_strategies", {"part_type": "box"})
    assert filtered.ok
    assert filtered.result["count"] == 1
    assert filtered.result["strategies"][0]["id"] == "box"


def test_tool_spec_flags_and_token_budget():
    tool = next(s for s in core_registry() if s.name == "list_part_strategies")
    assert tool.mutating is False
    assert tool.bypass_queue is True
    assert tool.layer == "domain"
    assert tool.timeout_class == "fast"
    assert spec_tokens(tool) <= 300
