"""status tool (B4): bypass_queue + detail tier (§11.2 item 3, §16.5 stdio status query)."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from cadmcp.backend.fake.backend import FakeBackend
from cadmcp.executor import Executor
from cadmcp.kernel import Kernel
from cadmcp.probe import FakeDialogProbe, WindowInfo
from cadmcp.registry import ToolRegistry, ToolSpec, make_schema
from cadmcp.result import ok_result
from cadmcp.server import build_stack, call_through_executor
from cadmcp.toolsets.core import core_registry

PROBE_TITLE = "另存为 C:\\secret\\gear.sldprt"


def _probe() -> FakeDialogProbe:
    return FakeDialogProbe(
        [WindowInfo(title=PROBE_TITLE, class_name="#32770", rect=(1, 2, 3, 4), modal=True)]
    )


def test_status_answers_while_stuck_without_queueing(tmp_path: Path):
    """STUCK is why status bypasses queue and answers inline."""
    executor = Executor(
        FakeBackend,
        tiers_s={"fast": 0.05, "normal": 0.1, "slow": 0.2},
        probe=_probe(),
    )
    executor.start()
    registry = core_registry()
    kernel = Kernel(
        registry,
        executor.backend(),
        workspace=tmp_path,
        health_provider=lambda: executor.health(detail=True),
    )

    def slow_read():
        time.sleep(0.5)  # sleep >> fast tier → STUCK
        return ok_result({})

    async def body():
        r = await executor.run(slow_read, tool="slow_read", mutating=False, timeout_class="fast")
        payload = r.model_dump()
        assert payload["ok"] is False and payload["error"]["code"] == "EXEC_TIMEOUT"

        t0 = time.monotonic()
        st = await call_through_executor(kernel, executor, registry, "status", {})
        elapsed = time.monotonic() - t0
        # must inline not queue
        assert st.model_dump()["ok"] is True
        assert elapsed < 0.25

        health = st.model_dump()["result"]["health"]
        assert health["state"] == "STUCK"
        assert "slow_read" in health["stuck_reason"]
        assert health["windows"][0]["title"] == PROBE_TITLE  # detail=True provider

    try:
        asyncio.run(body())
    finally:
        executor.shutdown()


@pytest.mark.parametrize(
    "kw,expect_detail",
    [
        ({"transport": "stdio"}, True),
        ({"auth_token": "tok", "require_auth": True}, True),
        ({"auth_token": "tok", "require_auth": False}, False),
        ({}, False),  # HTTP no token → coarse
    ],
)
def test_status_detail_bound_at_stack_build(tmp_path: Path, kw: dict, expect_detail: bool):
    stack = build_stack(workspace=tmp_path, backend_factory=FakeBackend, probe=_probe(), **kw)

    async def body():
        return await call_through_executor(
            stack.kernel, stack.executor, stack.registry, "status", {}
        )

    try:
        health = asyncio.run(body()).model_dump()["result"]["health"]
        if expect_detail:
            assert health["windows"][0]["title"] == PROBE_TITLE
            assert health["detector_error"] is None
        else:
            assert "windows" not in health and "detector_error" not in health
        assert health["blocker"] is True  # coarse still gives blocker (like /health)
        assert health["state"] in {"IDLE", "BUSY", "STUCK"}
    finally:
        stack.executor.shutdown()


def test_registry_rejects_bypass_queue_mutating():
    reg = ToolRegistry()
    with pytest.raises(ValueError, match="bypass_queue"):
        reg.register(
            ToolSpec(
                name="bad_bypass",
                description="x",
                input_schema=make_schema({}),
                handler=lambda ctx: {},
                mutating=True,
                bypass_queue=True,
            )
        )


def test_status_spec_shape():
    spec = core_registry().get("status")
    assert spec is not None
    assert spec.bypass_queue and not spec.mutating and spec.timeout_class == "fast"
    assert spec.input_schema["properties"] == {}  # no params; tier not selectable
