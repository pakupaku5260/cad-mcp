"""Wave 7 recipe: replay_recipe."""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from cadmcp.backend.fake.backend import FakeBackend
from cadmcp.kernel import Kernel
from cadmcp.recipe import compare_replays, load_recipe, replay_recipe
from cadmcp.toolbox import ToolVisibility
from cadmcp.toolsets.core import core_registry

BRACKET = Path(__file__).resolve().parent / "data" / "recipes" / "bracket.json"
PARAM_SKETCH = Path(__file__).resolve().parent / "data" / "recipes" / "param_sketch_circle.json"
EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
SKILL_CASES = (
    EXAMPLES / "skill_case_1_plate.json",
    EXAMPLES / "skill_case_2_fillet_pattern.json",
    EXAMPLES / "skill_case_3_surface_thicken.json",
)


def _k(tmp_path: Path) -> Kernel:
    return Kernel(core_registry(), FakeBackend(), workspace=tmp_path, verify_mutations=True)


def _k_with_toolbox(tmp_path: Path) -> Kernel:
    # part profile initially; recipes may open features_adv via open_toolbox
    return Kernel(
        core_registry(),
        FakeBackend(),
        workspace=tmp_path,
        verify_mutations=True,
        visibility=ToolVisibility(initially_open=("core", "sketch_adv", "features_adv")),
    )


def test_replay_bracket_recipe_twice(tmp_path: Path):
    recipe_path = tmp_path / "bracket.json"
    recipe_path.write_text(BRACKET.read_text(encoding="utf-8"), encoding="utf-8")
    k = _k(tmp_path)
    r1 = k.dispatch("replay_recipe", {"path": "bracket.json"})
    assert r1.ok and r1.result["ok"] is True
    assert r1.result["failed_step"] is None
    k2 = _k(tmp_path)
    r2 = k2.dispatch("replay_recipe", {"path": "bracket.json"})
    assert r2.ok and r2.result["ok"] is True
    diffs = compare_replays(r1.result, r2.result)
    assert diffs == [], diffs


def test_replay_param_sketch_driving_dimension_twice(tmp_path: Path):
    """Add_sketch_dimension first, then play back the modified section; the two trajectories are the same and the volume = π · 10 ² · 10."""
    recipe_path = tmp_path / "param_sketch_circle.json"
    recipe_path.write_text(PARAM_SKETCH.read_text(encoding="utf-8"), encoding="utf-8")
    k = _k(tmp_path)
    r1 = k.dispatch("replay_recipe", {"path": "param_sketch_circle.json"})
    assert r1.ok and r1.result["ok"] is True, r1.result
    assert r1.result["failed_step"] is None
    mp = k.dispatch("get_mass_properties", {})
    assert mp.ok
    assert mp.result["volume"] == pytest.approx(math.pi * 10.0**2 * 10.0, rel=1e-6)

    k2 = _k(tmp_path)
    r2 = k2.dispatch("replay_recipe", {"path": "param_sketch_circle.json"})
    assert r2.ok and r2.result["ok"] is True, r2.result
    diffs = compare_replays(r1.result, r2.result)
    assert diffs == [], diffs
    mp2 = k2.dispatch("get_mass_properties", {})
    assert mp2.result["volume"] == pytest.approx(math.pi * 10.0**2 * 10.0, rel=1e-6)


def test_replay_unknown_tool(tmp_path: Path):
    bad = {"name": "bad", "steps": [{"tool": "not_a_real_tool", "args": {}}]}
    (tmp_path / "bad.json").write_text(json.dumps(bad), encoding="utf-8")
    k = _k(tmp_path)
    r = k.dispatch("replay_recipe", {"path": "bad.json"})
    assert r.ok
    assert r.result["ok"] is False
    assert r.result["failed_step"] == 0
    assert r.result["steps"][0]["error_code"] == "INVALID_ARGUMENT"


@pytest.mark.parametrize("recipe_path", SKILL_CASES, ids=lambda p: p.stem)
def test_replay_skill_case_examples(tmp_path: Path, recipe_path: Path):
    assert recipe_path.is_file(), recipe_path
    dest = tmp_path / recipe_path.name
    dest.write_text(recipe_path.read_text(encoding="utf-8"), encoding="utf-8")
    report = replay_recipe(_k_with_toolbox(tmp_path), load_recipe(dest))
    assert report["ok"] is True, report
    assert report["failed_step"] is None, report


def test_replay_assert_failure_locates_step(tmp_path: Path):
    (tmp_path / "a.json").write_text(
        json.dumps(
            {
                "name": "assert_fail",
                "steps": [
                    {"tool": "new_part", "args": {}, "assert": {"ok": True}},
                    {"tool": "get_geometry", "args": {}, "assert": {"ok": False}},
                ],
            }
        ),
        encoding="utf-8",
    )
    k = _k(tmp_path)
    r = k.dispatch("replay_recipe", {"path": "a.json"})
    assert r.ok
    assert r.result["ok"] is False
    assert r.result["failed_step"] == 1
    assert r.result["steps"][1]["assert_ok"] is False
