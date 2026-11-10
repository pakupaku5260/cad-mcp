"""Runtime tool-surface filtering (--profile / --toolsets): profile closure, filter results, token savings."""

from __future__ import annotations

from pathlib import Path

import pytest

from cadmcp.backend.fake.backend import FakeBackend
from cadmcp.registry import TOOLSET_DEFS, TOOLSET_PROFILES, resolve_toolsets, spec_tokens
from cadmcp.server import build_stack
from cadmcp.toolsets.core import core_registry


def test_default_registry_covers_every_declared_toolset():
    assert {s.toolset for s in core_registry().all()} == set(TOOLSET_DEFS)


def test_every_profile_only_references_declared_toolsets():
    for profile, toolsets in TOOLSET_PROFILES.items():
        assert toolsets, profile
        assert set(toolsets) <= set(TOOLSET_DEFS), profile


def test_part_profile_filters_out_assembly_and_drawing():
    profile = resolve_toolsets(profile="part")
    registry = core_registry(profile)
    assert {s.toolset for s in registry.all()} == set(profile)
    names = {s.name for s in registry.all()}
    assert {"new_part", "extrude", "help", "status"} <= names
    assert "insert_component" not in names
    assert "create_section_view" not in names


def test_sheetmetal_profile_includes_sheetmetal_not_assembly():
    profile = resolve_toolsets(profile="sheetmetal")
    assert "sheetmetal" in profile and "core" in profile
    assert "assembly" not in profile and "drawing" not in profile
    registry = core_registry(profile)
    names = {s.name for s in registry.all()}
    assert {"base_flange", "edge_flange", "miter_flange", "help"} <= names
    assert "insert_component" not in names


def test_part_profile_costs_fewer_tokens_than_full():
    full = sum(spec_tokens(s) for s in core_registry().all())
    part = sum(spec_tokens(s) for s in core_registry(resolve_toolsets(profile="part")).all())
    assert part < full * 0.8  # at least 20% savings or profile is pointless


def test_resolve_toolsets_strips_and_dedupes():
    assert resolve_toolsets(["core", " core ", "assembly", "core"]) == ("core", "assembly")


def test_resolve_toolsets_rejects_unknown_names():
    with pytest.raises(ValueError, match="Unknown toolset"):
        resolve_toolsets(["core", "nope"])
    with pytest.raises(ValueError, match="Unknown profile"):
        resolve_toolsets(profile="nope")


def test_cli_default_profile_is_part():
    from cadmcp.cli import build_parser

    ns = build_parser().parse_args(["serve"])
    assert ns.profile == "part"
    assert set(resolve_toolsets(profile=ns.profile)) == set(TOOLSET_PROFILES["part"])


def test_build_stack_wires_full_registry_with_visibility(tmp_path: Path):
    """Registry is always full; --profile only sets initially visible toolsets."""
    stack = build_stack(
        workspace=tmp_path,
        backend_factory=FakeBackend,
        toolsets=resolve_toolsets(profile="assembly"),
    )
    try:
        assert {s.toolset for s in stack.registry.all()} == set(TOOLSET_DEFS)
        assert set(stack.visibility.open_names()) == set(TOOLSET_PROFILES["assembly"])
        visible = {s.toolset for s in stack.visibility.visible_specs(stack.registry)}
        assert visible == set(TOOLSET_PROFILES["assembly"])
        assert stack.registry.get("insert_component") is not None  # registered
        assert not stack.visibility.is_visible(stack.registry.get("base_flange"))
    finally:
        stack.executor.shutdown()
