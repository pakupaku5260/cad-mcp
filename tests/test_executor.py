"""Executor tests: busy reject, bounded queue, timeout→STUCK, health channel, worker survival."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from cadmcp.backend.fake.backend import FakeBackend
from cadmcp.errors import SideEffect
from cadmcp.executor import Executor
from cadmcp.probe import FakeDialogProbe, WindowInfo
from cadmcp.result import ok_result


def _ex(**kwargs) -> Executor:
    kwargs.setdefault("tiers_s", {"fast": 0.15, "normal": 0.3, "slow": 1.0})
    kwargs.setdefault("backend_factory", FakeBackend)
    ex = Executor(**kwargs)
    ex.start(wait_s=5)
    return ex


@pytest.fixture()
def ex() -> Executor:
    e = _ex()
    yield e
    e.shutdown()


def _slow(value: float = 0.05, result: dict | None = None):
    def fn():
        time.sleep(value)
        return ok_result(result or {"v": value})

    return fn


# ---------- Basic execution ----------


def test_factory_runs_in_worker_thread(ex: Executor):
    backend = ex.backend()
    assert isinstance(backend, FakeBackend)
    assert threading.current_thread().name != "cadmcp-sta"


def test_run_executes_on_worker_thread(ex: Executor):
    seen: dict = {}

    def fn():
        seen["thread"] = threading.current_thread().name
        return ok_result({"hi": True})

    r = asyncio.run(ex.run(fn, tool="t1"))
    assert r.ok and r.result == {"hi": True}
    assert seen["thread"] == "cadmcp-sta"


def test_state_transitions_idle_busy_idle(ex: Executor):
    states = []

    def fn():
        states.append(ex.health().state)
        time.sleep(0.02)
        return ok_result({})

    asyncio.run(ex.run(fn, tool="t"))
    states.append(ex.health().state)
    assert states == ["BUSY", "IDLE"]
    assert ex.health().jobs_total == 1


def test_business_error_passes_through(ex: Executor):
    def fn():
        raise _domain_error()

    r = asyncio.run(ex.run(fn, tool="bad"))
    assert not r.ok and r.error.code == "SKETCH_NOT_FOUND"
    # worker alive; next job ok
    assert asyncio.run(ex.run(_slow(), tool="after")).ok


def _domain_error():
    from cadmcp.errors import fail

    return fail("SKETCH_NOT_FOUND", "没有草图", "先 start_sketch")


def test_unexpected_exception_becomes_internal_error(ex: Executor):
    def fn():
        raise RuntimeError("boom")

    r = asyncio.run(ex.run(fn, tool="crash"))
    assert not r.ok and r.error.code == "INTERNAL_ERROR"
    assert ex.health().state == "IDLE"
    assert asyncio.run(ex.run(_slow(), tool="after")).ok


# ---------- Busy reject and queue ----------


def test_mutating_rejected_while_busy_read_queues(ex: Executor):
    order: list[str] = []

    def blocker():
        order.append("blocker-start")
        time.sleep(0.2)
        order.append("blocker-end")
        return ok_result({})

    async def main():
        task = asyncio.create_task(ex.run(blocker, tool="blocker", mutating=True, timeout=5))
        for _ in range(200):
            h = ex.health()
            if h.state == "BUSY" and h.tool == "blocker":
                break
            await asyncio.sleep(0.005)
        busy = await ex.run(_slow(), tool="write2", mutating=True)
        queued = await ex.run(_slow(result={"read": True}), tool="read1", timeout=5)
        await task
        return busy, queued

    busy, queued = asyncio.run(main())
    assert not busy.ok and busy.error.code == "EXECUTOR_BUSY"
    assert "blocker" in busy.error.message
    assert busy.error.context["busy_tool"] == "blocker"
    assert queued.ok  # read queues
    assert order.index("blocker-end") < len(order)  # blocker finishes first


def test_queue_full(ex: Executor):
    async def main():
        blocker = asyncio.create_task(ex.run(_slow(0.4), tool="blocker", timeout=5))
        for _ in range(200):
            h = ex.health()
            if h.state == "BUSY" and h.tool == "blocker":
                break
            await asyncio.sleep(0.005)
        # queue capacity 8: fill then overflow
        results = []
        for i in range(10):
            results.append(asyncio.create_task(ex.run(_slow(0.01), tool=f"q{i}", timeout=5)))
        done = await asyncio.gather(*results, return_exceptions=True)
        await blocker
        return done

    done = asyncio.run(main())
    codes = [r.error.code for r in done if not r.ok]
    assert "QUEUE_FULL" in codes


# ---------- Timeout → STUCK → recovery ----------


def test_timeout_marks_stuck_and_captures_dialog():
    probe = FakeDialogProbe(
        [WindowInfo(title="另存为", class_name="#32770", rect=(0, 0, 100, 50), modal=True)]
    )
    e = _ex(probe=probe)
    try:
        r = asyncio.run(e.run(_slow(0.5), tool="hang", timeout=0.05))
        assert not r.ok and r.error.code == "EXEC_TIMEOUT"
        assert r.error.side_effect == SideEffect.APPLIED
        assert r.error.context["windows"][0]["title"] == "另存为"
        assert "resolve_stuck" in r.error.hint

        h = e.health()
        assert h.state == "STUCK" and "hang" in (h.stuck_reason or "")

        # STUCK rejects new work
        again = asyncio.run(e.run(_slow(), tool="next", mutating=True))
        assert again.error.code == "EXEC_STUCK"

        # late result counted
        time.sleep(0.6)
        assert e.health().late_results == 1

        res = e.resolve_stuck()
        assert res.ok and res.result["was_stuck"] is True
        assert e.health().state == "IDLE"
        assert asyncio.run(e.run(_slow(), tool="ok_again")).ok
    finally:
        e.shutdown()


def test_queued_timeout_is_not_stuck():
    e = _ex()
    try:
        async def main():
            blocker = asyncio.create_task(e.run(_slow(0.25), tool="blocker", timeout=5))
            for _ in range(200):
                if e.health().state == "BUSY":
                    break
                await asyncio.sleep(0.005)
            queued = await e.run(_slow(), tool="late_read", timeout=0.05)
            await blocker
            return queued

        queued = asyncio.run(main())
        assert not queued.ok and queued.error.code == "EXEC_TIMEOUT"
        assert queued.error.context.get("queued") is True
        assert e.health().state == "IDLE"  # queue timeout not STUCK
    finally:
        e.shutdown()


# ---------- Health independent channel (§6) ----------


def test_health_responsive_while_worker_stuck():
    probe = FakeDialogProbe([WindowInfo(title="弹窗", class_name="x", rect=(0, 0, 0, 0), modal=True)])
    e = _ex(probe=probe)
    try:
        asyncio.run(e.run(_slow(0.5), tool="hang", timeout=0.05))
        # worker still stuck; health must answer immediately
        t0 = time.monotonic()
        h = e.health(detail=True)
        elapsed = time.monotonic() - t0
        assert elapsed < 0.2  # << remaining stuck sleep
        assert h.state == "STUCK"
        assert h.windows is not None and h.windows[0].modal is True
        assert h.thread_alive is True
    finally:
        e.shutdown()


def test_detector_timeout_does_not_block_health():
    probe = FakeDialogProbe(delay_s=1.0)
    e = _ex(probe=probe, detector_timeout_s=0.05)
    try:
        t0 = time.monotonic()
        h = e.health(detail=True)
        assert time.monotonic() - t0 < 0.5
        assert h.windows is None
        assert "detector_timeout" in (h.detector_error or "")
    finally:
        e.shutdown()


def test_health_without_probe_has_no_windows(ex: Executor):
    h = ex.health(detail=True)
    assert h.windows is None and h.detector_error is None
    assert h.blocker is None  # no probe → unknown


def test_health_blocker_from_probe():
    modal = FakeDialogProbe(
        [WindowInfo(title="另存为", class_name="#32770", rect=(0, 0, 0, 0), modal=True)]
    )
    e = _ex(probe=modal)
    try:
        assert e.health().blocker is True  # coarse health incl. /health row 3
        assert e.health().blocker is True  # idempotent
    finally:
        e.shutdown()

    clear = FakeDialogProbe(
        [WindowInfo(title="主窗", class_name="SWFrame", rect=(0, 0, 0, 0), modal=False)]
    )
    e2 = _ex(probe=clear)
    try:
        assert e2.health().blocker is False  # no modal → false
    finally:
        e2.shutdown()


def test_health_blocker_unknown_when_probe_fails(ex: Executor):
    e = _ex(probe=FakeDialogProbe(error="探测炸了"))
    try:
        assert e.health().blocker is None  # probe failed → unknown
        h = e.health(detail=True)
        assert "探测炸了" in (h.detector_error or "")
        assert h.blocker is None
    finally:
        e.shutdown()


# ---------- Init failure ----------


def test_init_failure_surfaces_in_run():
    def broken_factory():
        raise RuntimeError("COM 不可用")

    e = Executor(broken_factory)
    e.start(wait_s=2)
    r = asyncio.run(e.run(_slow(), tool="t"))
    assert not r.ok and r.error.code == "COM_ATTACH_FAILED"
    assert "COM 不可用" in r.error.message
    h = e.health()
    assert h.backend_ready is False and h.thread_alive is False  # dead thread: honest
    e.shutdown()


def test_run_before_start_rejected():
    e = Executor(FakeBackend)
    r = asyncio.run(e.run(_slow(), tool="t"))
    assert not r.ok and r.error.code == "COM_ATTACH_FAILED"
