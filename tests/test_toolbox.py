"""Dynamic toolbox: visibility, recoverable errors, list_changed capability declaration."""

from __future__ import annotations

from pathlib import Path

import pytest

from cadmcp.backend.fake.backend import FakeBackend
from cadmcp.kernel import Kernel
from cadmcp.registry import TOOLSET_DEFS, resolve_toolsets
from cadmcp.server import build_stack, call_through_executor
from cadmcp.toolbox import ToolVisibility
from cadmcp.toolsets.core import core_registry


def test_visibility_core_always_open_and_cannot_close():
    vis = ToolVisibility(["core", "sheetmetal"])
    assert vis.is_open("core") and vis.is_open("sheetmetal")
    with pytest.raises(Exception) as exc:
        vis.close(["core"])
    assert "core" in str(exc.value).lower() or getattr(exc.value, "code", "") == "INVALID_ARGUMENT"


def test_open_close_and_search():
    registry = core_registry()
    vis = ToolVisibility(["core"])
    assert not vis.is_open("assembly")
    opened = vis.open(["assembly", "export"])
    assert "assembly" in opened["opened"]
    assert vis.is_open("assembly")
    hits = vis.search_tools(registry, "mate")
    assert hits["count"] >= 1
    assert any(m["name"] == "mate" and m["open"] for m in hits["matches"])
    closed = vis.close(["assembly"])
    assert "assembly" in closed["closed"]
    assert not vis.is_open("assembly")


def test_closed_tool_returns_toolset_closed(tmp_path: Path):
    import asyncio

    stack = build_stack(
        workspace=tmp_path,
        backend_factory=FakeBackend,
        toolsets=resolve_toolsets(profile="part"),
    )

    async def body():
        result = await call_through_executor(
            stack.kernel,
            stack.executor,
            stack.registry,
            "insert_component",
            {"path": "x.sldprt"},
            visibility=stack.visibility,
        )
        assert not result.ok
        assert result.error is not None
        assert result.error.code == "TOOLSET_CLOSED"
        assert result.error.context.get("toolset") == "assembly"
        opened = stack.kernel.dispatch("open_toolbox", {"toolsets": ["assembly"]})
        assert opened.ok
        # After open, param validation may still fail, but not TOOLSET_CLOSED
        result2 = await call_through_executor(
            stack.kernel,
            stack.executor,
            stack.registry,
            "insert_component",
            {"path": "x.sldprt"},
            visibility=stack.visibility,
        )
        assert result2.error is None or result2.error.code != "TOOLSET_CLOSED"

    try:
        asyncio.run(body())
    finally:
        stack.executor.shutdown()


def test_list_tools_respects_visibility(tmp_path: Path):
    stack = build_stack(
        workspace=tmp_path,
        backend_factory=FakeBackend,
        toolsets=resolve_toolsets(profile="drawing"),
    )
    try:
        names = {s.name for s in stack.visibility.visible_specs(stack.registry)}
        assert "help" in names and "create_section_view" in names
        assert "insert_component" not in names
        assert "base_flange" not in names
        assert "list_toolboxes" in names and "open_toolbox" in names
        boxes = stack.kernel.dispatch("list_toolboxes")
        assert boxes.ok
        drawing = next(b for b in boxes.result["toolboxes"] if b["name"] == "drawing")
        assert drawing["open"] is True
        assembly = next(b for b in boxes.result["toolboxes"] if b["name"] == "assembly")
        assert assembly["open"] is False
    finally:
        stack.executor.shutdown()


def test_tools_changed_capability_bound(tmp_path: Path):
    stack = build_stack(workspace=tmp_path, backend_factory=FakeBackend)
    try:
        opts = stack.server.create_initialization_options()
        assert opts.capabilities.tools is not None
        assert opts.capabilities.tools.list_changed is True
    finally:
        stack.executor.shutdown()


def test_kernel_without_visibility_rejects_toolbox_meta(tmp_path: Path):
    k = Kernel(core_registry(), FakeBackend(), workspace=tmp_path)
    r = k.dispatch("list_toolboxes")
    assert not r.ok and r.error is not None
    assert r.error.code == "INTERNAL_ERROR"


def test_sheetmetal_profile_in_defs():
    assert "sheetmetal" in resolve_toolsets(profile="sheetmetal")
    assert set(resolve_toolsets(profile="sheetmetal")) <= set(TOOLSET_DEFS)
