"""Kernel dispatch tests: boundary check, exception mapping, state_version, verify loop."""

from __future__ import annotations

from pathlib import Path

import pytest

from cadmcp.backend.fake.backend import FakeBackend
from cadmcp.errors import SideEffect, fail
from cadmcp.kernel import Kernel
from cadmcp.registry import ToolRegistry, ToolSpec, make_schema
from cadmcp.toolsets.core import core_registry


def _dummy_registry() -> ToolRegistry:
    reg = ToolRegistry()

    reg.register(ToolSpec(name="needs_size", description="d",
                          input_schema=make_schema(
                              {"size": {"type": "number", "description": "A size."}}, ["size"]),
                          handler=lambda ctx, size: {"size": size}))

    def _boom_read(ctx):
        raise RuntimeError("reader exploded")

    reg.register(ToolSpec(name="boom_read", description="d", input_schema=make_schema({}),
                          handler=_boom_read))

    def _boom_mut(ctx):
        raise RuntimeError("mutator exploded mid-flight")

    reg.register(ToolSpec(name="boom_mut", description="d", input_schema=make_schema({}),
                          handler=_boom_mut, mutating=True))

    def _partial_fail(ctx):
        raise fail("COM_CALL_FAILED", "调用失败但已写入一半", "先读状态再重试",
                   side_effect=SideEffect.APPLIED)

    reg.register(ToolSpec(name="partial_fail", description="d", input_schema=make_schema({}),
                          handler=_partial_fail, mutating=True))
    return reg


@pytest.fixture()
def dummy_kernel(tmp_path: Path) -> Kernel:
    return Kernel(_dummy_registry(), FakeBackend(), workspace=tmp_path)


# ---------- Boundary check (bad args never reach handler) ----------


def test_unknown_tool_with_close_match_hint(dummy_kernel):
    r = dummy_kernel.dispatch("needs_siz", {})
    assert r.ok is False
    assert r.error.code == "INVALID_ARGUMENT"
    assert "needs_size" in r.error.hint


def test_unknown_tool_without_match(dummy_kernel):
    r = dummy_kernel.dispatch("totally_unrelated", {})
    assert not r.ok
    assert "tools/list" in r.error.hint


def test_missing_required_rejected_with_schema_errors(dummy_kernel):
    r = dummy_kernel.dispatch("needs_size", {})
    assert not r.ok
    assert r.error.code == "INVALID_ARGUMENT"
    assert "size" in r.error.message
    assert r.error.context["schema_errors"]


def test_extra_property_rejected(dummy_kernel):
    r = dummy_kernel.dispatch("needs_size", {"size": 1, "szie": 2})
    assert not r.ok
    assert r.error.code == "INVALID_ARGUMENT"
    assert any("Additional properties" in e for e in r.error.context["schema_errors"])


def test_wrong_type_rejected_with_property_description(dummy_kernel):
    r = dummy_kernel.dispatch("needs_size", {"size": "big"})
    assert not r.ok
    assert r.error.code == "INVALID_ARGUMENT"
    assert "A size." in r.error.hint  # pedagogical: property description


def test_non_dict_args_rejected(dummy_kernel):
    r = dummy_kernel.dispatch("needs_size", [1, 2])  # type: ignore[arg-type]
    assert not r.ok
    assert r.error.code == "INVALID_ARGUMENT"


# ---------- Exception mapping ----------


def test_sw_mcp_error_propagates_with_side_effect(dummy_kernel):
    r = dummy_kernel.dispatch("partial_fail", {})
    assert not r.ok
    assert r.error.code == "COM_CALL_FAILED"
    assert r.error.side_effect == SideEffect.APPLIED
    assert r.state_version == 0  # no increment on failure


def test_unexpected_exception_read_is_none_side_effect(dummy_kernel):
    r = dummy_kernel.dispatch("boom_read", {})
    assert not r.ok
    assert r.error.code == "INTERNAL_ERROR"
    assert "reader exploded" in r.error.message
    assert r.error.side_effect == SideEffect.NONE


def test_unexpected_exception_mutating_is_conservative_applied(dummy_kernel):
    r = dummy_kernel.dispatch("boom_mut", {})
    assert not r.ok
    assert r.error.code == "INTERNAL_ERROR"
    assert r.error.side_effect == SideEffect.APPLIED
    assert r.state_version == 0  # no success → no increment


# ---------- state_version single writer ----------


def test_state_version_only_increments_on_mutating_success(kernel: Kernel):
    assert kernel.dispatch("new_part", {}).state_version == 1
    assert kernel.dispatch("get_active_document", {}).state_version == 1  # reads do not increment
    assert kernel.dispatch("list_planes", {}).state_version == 1
    assert kernel.dispatch("start_sketch", {}).state_version == 2
    assert kernel.dispatch("get_active_document", {}).state_version == 2


def test_failed_mutating_does_not_increment(kernel: Kernel):
    kernel.dispatch("new_part", {})
    r = kernel.dispatch("extrude", {"depth": 5})  # no sketch
    assert not r.ok
    assert r.error.code == "SKETCH_NOT_FOUND"
    assert r.state_version == 1


# ---------- Verify closed loop ----------


def test_verify_delta_attached_on_extrude(kernel: Kernel):
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {})
    kernel.dispatch("sketch_rectangle", {"x1": -25, "y1": -25, "x2": 25, "y2": 25})
    kernel.dispatch("end_sketch", {})
    r = kernel.dispatch("extrude", {"depth": 50})
    assert r.ok
    assert r.delta is not None and "volume_mm3" in r.delta.changed
    assert r.rebuild is not None and r.rebuild.ok is True
    assert r.state_version == 5


def test_read_tool_has_no_delta(kernel: Kernel):
    kernel.dispatch("new_part", {})
    r = kernel.dispatch("get_mass_properties", {})
    assert r.ok
    assert r.delta is None and r.rebuild is None


def test_pre_fingerprint_failure_does_not_crash_dispatch(tmp_path: Path):
    """No document: verify fingerprint skipped; handler returns domain error, not crash."""
    k = Kernel(core_registry(), FakeBackend(), workspace=tmp_path)
    r = k.dispatch("extrude", {"depth": 5})
    assert not r.ok
    assert r.error.code == "NO_ACTIVE_DOCUMENT"


def test_rebuild_failure_reported_but_result_kept(tmp_path: Path):
    fake = FakeBackend(rebuild_errors=["Boss-Extrude1: 重建报错"])
    k = Kernel(core_registry(), fake, workspace=tmp_path)
    k.dispatch("new_part", {})
    k.dispatch("start_sketch", {})
    k.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 10, "y2": 10})
    k.dispatch("end_sketch", {})
    r = k.dispatch("extrude", {"depth": 10})
    assert r.ok  # op ok
    assert r.rebuild is not None and r.rebuild.ok is False
    assert r.rebuild.feature_errors


def test_fail_on_injection_through_kernel(tmp_path: Path):
    fake = FakeBackend(fail_on=[("extrude_blind", 1)])
    k = Kernel(core_registry(), fake, workspace=tmp_path)
    k.dispatch("new_part", {})
    k.dispatch("start_sketch", {})
    k.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 10, "y2": 10})
    k.dispatch("end_sketch", {})
    r = k.dispatch("extrude", {"depth": 10})
    assert not r.ok
    assert r.error.code == "COM_CALL_FAILED"
    assert r.error.side_effect == SideEffect.APPLIED
    assert r.state_version == 4  # injection failure: no increment
    # conservative: op not applied → read state next
    mp = k.dispatch("get_mass_properties", {})
    assert mp.result["volume"] == 0
