"""F5 COM_LOST / reattach / executor one-shot retry (Fake)."""
from __future__ import annotations

import asyncio

import pytest

from cadmcp.backend.fake.backend import FakeBackend
from cadmcp.errors import CATALOG, SideEffect, fail
from cadmcp.executor import Executor
from cadmcp.result import fail_result, ok_result


def test_com_lost_in_catalog():
    assert "COM_LOST" in CATALOG


def test_fake_simulate_disconnect_and_reattach():
    be = FakeBackend()
    be.new_part()
    assert be.active_document() is not None
    be.simulate_disconnect(lose_document=True)
    with pytest.raises(Exception) as exc:
        be.revision()
    err = exc.value
    assert err.code == "COM_LOST"
    assert err.side_effect is SideEffect.NONE
    assert err.context.get("unsaved_at_disconnect") is True

    info = be.reattach()
    assert info["reattached"] is True
    assert info["unsaved_at_disconnect"] is True
    # Document was lost with the process — not auto-restored
    assert be.active_document() is None
    assert be.revision() == "33.0"


def test_fake_reattach_sw_not_running():
    be = FakeBackend()
    be.simulate_disconnect(lose_document=False)
    be._sw_available = False
    with pytest.raises(Exception) as exc:
        be.reattach()
    assert exc.value.code == "SW_NOT_RUNNING"


def test_executor_retries_readonly_com_lost_once():
    be = FakeBackend()
    state = {"n": 0}

    def factory():
        return be

    ex = Executor(backend_factory=factory, tiers_s={"fast": 2, "normal": 2, "slow": 2})
    ex.start(wait_s=5)
    try:
        def fn():
            state["n"] += 1
            if state["n"] == 1:
                be.simulate_disconnect(mid_call=False, lose_document=False)
                raise fail(
                    "COM_LOST",
                    "lost",
                    "Restart SolidWorks then retry",
                    side_effect=SideEffect.NONE,
                    recoverable=True,
                )
            return ok_result({"ok": True, "n": state["n"]})

        r = asyncio.run(ex.run(fn, tool="revision", mutating=False))
        assert r.ok, r.error
        assert state["n"] == 2
        assert any("COM_LOST" in w for w in r.warnings)
    finally:
        ex.shutdown()


def test_executor_does_not_retry_mutating_unknown():
    be = FakeBackend()
    state = {"n": 0}

    def factory():
        return be

    ex = Executor(backend_factory=factory, tiers_s={"fast": 2, "normal": 2, "slow": 2})
    ex.start(wait_s=5)
    try:
        def fn():
            state["n"] += 1
            raise fail(
                "COM_LOST",
                "lost mid write",
                "Do not blindly retry a write",
                side_effect=SideEffect.UNKNOWN,
                recoverable=True,
                mid_call=True,
            )

        r = asyncio.run(ex.run(fn, tool="extrude", mutating=True))
        assert not r.ok
        assert r.error.code == "COM_LOST"
        assert r.error.side_effect is SideEffect.UNKNOWN
        assert state["n"] == 1  # no automatic retry
    finally:
        ex.shutdown()


def test_executor_retries_mutating_when_side_effect_none():
    be = FakeBackend()
    state = {"n": 0}

    def factory():
        return be

    ex = Executor(backend_factory=factory, tiers_s={"fast": 2, "normal": 2, "slow": 2})
    ex.start(wait_s=5)
    try:
        def fn():
            state["n"] += 1
            if state["n"] == 1:
                raise fail(
                    "COM_LOST",
                    "lost before dispatch",
                    "Restart SolidWorks then retry",
                    side_effect=SideEffect.NONE,
                    recoverable=True,
                    mid_call=False,
                )
            return ok_result({"applied": True})

        r = asyncio.run(ex.run(fn, tool="new_part", mutating=True))
        assert r.ok, r.error
        assert state["n"] == 2
    finally:
        ex.shutdown()


def test_should_retry_helpers():
    from cadmcp.executor import Executor as Ex

    class _J:
        mutating = False

    job = _J()
    assert Ex._should_retry_com_lost(job, fail_result(fail(
        "COM_LOST", "m", "h", side_effect=SideEffect.UNKNOWN
    )))
    job.mutating = True
    assert not Ex._should_retry_com_lost(job, fail_result(fail(
        "COM_LOST", "m", "h", side_effect=SideEffect.UNKNOWN
    )))
    assert Ex._should_retry_com_lost(job, fail_result(fail(
        "COM_LOST", "m", "h", side_effect=SideEffect.NONE
    )))
