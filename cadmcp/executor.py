"""Executor (v4 §6 W3-8): single STA thread + bounded queue + tiered timeouts + IDLE/BUSY/STUCK.

- **Dedicated thread** (no pool): backend_factory() on thread start (CoInitialize STA + SW on Windows;
  fake on macOS); all backend work queued serially on that thread.
- **Busy reject, no write pile-up**: mutating when not IDLE → EXECUTOR_BUSY; reads may queue.
  pending_mutating closes race where two writes pass the check.
- **Timeout tiers**: fast=10s, normal=60s, slow=300s; per-call override. Cannot cancel in-flight COM:
  abandon wait, mark STUCK, probe dialogs into error context.
- **STUCK cleared only via resolve_stuck()** (doctor); never auto-kill. Late jobs counted in late_results.
- **Health is independent**: health() is lock-protected snapshot, no queue, no COM; probe on daemon + join timeout.
- Not ready / init failure: run() returns fail_result; unexpected → INTERNAL_ERROR, worker keeps serving.

Future (elsewhere): RPC busy retry (§6.7) in com wrapper; batch cancel (§6.8) in spec/batch layer.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import itertools
import logging
import queue
import threading
import time
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict

from cadmcp.backend.protocol.protocol import CADBackend
from cadmcp.errors import CadMcpError, SideEffect, fail
from cadmcp.probe import DialogProbe, WindowInfo, derive_blocker
from cadmcp.result import OpResult, fail_result, ok_result

log = logging.getLogger(__name__)

TimeoutClass = Literal["fast", "normal", "slow"]

# Default timeout tiers (v4 §6.4; per-call override)
DEFAULT_TIERS_S: dict[str, float] = {"fast": 10.0, "normal": 60.0, "slow": 300.0}
DEFAULT_QUEUE_SIZE = 8
DEFAULT_DETECTOR_TIMEOUT_S = 0.5


class HealthReport(BaseModel):
    """Health snapshot. detail=False → coarse only (window titles need auth, W4 tiers)."""

    model_config = ConfigDict(extra="forbid")

    state: Literal["IDLE", "BUSY", "STUCK"]
    tool: str | None = None  # current (or stuck) tool
    elapsed_s: float | None = None  # seconds current job has run
    queue_depth: int
    pending_mutating: int
    thread_alive: bool
    backend_ready: bool
    stuck_reason: str | None = None
    late_results: int = 0  # jobs finished after caller timed out
    jobs_total: int = 0
    windows: list[WindowInfo] | None = None  # detail=True with probe
    detector_error: str | None = None
    blocker: bool | None = None  # True=modal dialog; None=unknown (W8 row 3)


class _Job:
    __slots__ = ("id", "tool", "mutating", "fn", "future", "started", "started_at", "abandoned")

    def __init__(self, job_id: int, tool: str, mutating: bool, fn: Callable[[], OpResult]) -> None:
        self.id = job_id
        self.tool = tool
        self.mutating = mutating
        self.fn = fn
        self.future: concurrent.futures.Future[OpResult] = concurrent.futures.Future()
        self.started = False
        self.started_at: float | None = None
        self.abandoned = False  # caller timed out; worker may skip or count late


class Executor:
    def __init__(
        self,
        backend_factory: Callable[[], CADBackend],
        *,
        queue_size: int = DEFAULT_QUEUE_SIZE,
        tiers_s: dict[str, float] | None = None,
        probe: DialogProbe | None = None,
        detector_timeout_s: float = DEFAULT_DETECTOR_TIMEOUT_S,
    ) -> None:
        self._factory = backend_factory
        self._queue: queue.Queue[_Job | None] = queue.Queue(maxsize=queue_size)
        self._tiers = dict(DEFAULT_TIERS_S) if tiers_s is None else dict(tiers_s)
        self._probe = probe
        self._detector_timeout_s = detector_timeout_s

        self._lock = threading.Lock()
        self._current: _Job | None = None
        self._pending_mutating = 0
        self._stuck_since: float | None = None
        self._stuck_reason: str | None = None
        self._late_results = 0
        self._jobs_total = 0
        self._backend: CADBackend | None = None
        self._init_error: Exception | None = None

        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._thread_alive = False
        self._ids = itertools.count(1)

    # ---------- lifecycle ----------

    def start(self, *, wait_s: float = 10.0) -> None:
        """Start dedicated thread and wait for backend init (STA affinity on this thread)."""
        if self._thread is not None:
            return
        with self._lock:
            self._thread_alive = True
        self._thread = threading.Thread(target=self._worker, name="cadmcp-sta", daemon=True)
        self._thread.start()
        self._ready.wait(wait_s)

    def shutdown(self, *, wait_s: float = 5.0) -> None:
        if self._thread is None:
            return
        try:
            self._queue.put_nowait(None)  # sentinel: exit
        except queue.Full:
            pass
        self._thread.join(wait_s)

    # ---------- execution ----------

    async def run(
        self,
        fn: Callable[[], OpResult],
        *,
        tool: str,
        mutating: bool = False,
        timeout_class: TimeoutClass = "normal",
        timeout: float | None = None,
    ) -> OpResult:
        """Submit one tool call to the dedicated thread; returns OpResult or infra error."""
        if not self._ready.is_set() or self._init_error is not None:
            return fail_result(
                fail(
                    "COM_ATTACH_FAILED",
                    f"Backend not ready; refused {tool}"
                    + (f": {self._init_error}" if self._init_error else ": init incomplete"),
                    "Run cadmcp doctor to check SolidWorks attach and version",
                    tool=tool,
                )
            )

        with self._lock:
            if self._stuck_since is not None:
                return fail_result(
                    fail(
                        "EXEC_STUCK",
                        f"Executor STUCK: {self._stuck_reason}",
                        "COM cannot be interrupted; clear dialogs in SolidWorks, then "
                        "cadmcp doctor (resolve_stuck) and retry",
                        stuck_reason=self._stuck_reason,
                    )
                )
            if mutating and self._state() != "IDLE":
                cur = self._current
                elapsed = (time.monotonic() - cur.started_at) if cur and cur.started_at else 0.0
                return fail_result(
                    fail(
                        "EXECUTOR_BUSY",
                        f"Executor busy running {cur.tool if cur else '?'} ({elapsed:.1f}s); "
                        "mutating calls are not queued",
                        "Retry the mutation later; read-only queries may still be submitted",
                        busy_tool=cur.tool if cur else None,
                        busy_elapsed_s=round(elapsed, 3),
                    )
                )
            job = _Job(next(self._ids), tool, mutating, fn)
            if mutating:
                self._pending_mutating += 1
            try:
                self._queue.put_nowait(job)
            except queue.Full:
                if mutating:
                    self._pending_mutating -= 1
                return fail_result(
                    fail(
                        "QUEUE_FULL",
                        f"Job queue full (capacity {self._queue.maxsize})",
                        "Retry later; chronic fullness means too much parallelism—serialize calls",
                        tool=tool,
                    )
                )

        limit = timeout if timeout is not None else self._tiers.get(timeout_class, 60.0)
        try:
            return await asyncio.wait_for(asyncio.wrap_future(job.future), limit)
        except TimeoutError:
            return self._on_timeout(job, tool, limit)

    def _on_timeout(self, job: _Job, tool: str, limit: float) -> OpResult:
        with self._lock:
            # wait_for cancels wrapper future; only a truly finished job wins the race.
            if job.future.done() and not job.future.cancelled():
                return job.future.result()
            job.abandoned = True
            started = job.started
            if started:
                self._stuck_since = time.monotonic()
                self._stuck_reason = f"{tool} did not return within {limit}s"
        if not started:
            return fail_result(
                fail(
                    "EXEC_TIMEOUT",
                    f"{tool} waited in queue over {limit}s without starting",
                    "Executor busy on other work; retry (queue timeout is not STUCK)",
                    tool=tool,
                    timeout_s=limit,
                    queued=True,
                )
            )
        windows = self._scan_windows()
        return fail_result(
            fail(
                "EXEC_TIMEOUT",
                f"{tool} did not return within {limit}s; executor marked STUCK",
                "COM cannot be interrupted; check SolidWorks for dialogs, then "
                "cadmcp doctor (resolve_stuck)—do not retry blindly",
                side_effect=SideEffect.APPLIED,
                tool=tool,
                timeout_s=limit,
                windows=[w.model_dump() for w in windows] if windows else [],
            )
        )

    # ---------- worker ----------

    def _worker(self) -> None:
        try:
            backend = self._factory()  # init on this thread (STA)
        except Exception as exc:  # noqa: BLE001 — init failure must be queryable
            with self._lock:
                self._init_error = exc
                self._thread_alive = False
            self._ready.set()
            log.exception("Backend initialization failed")
            return
        with self._lock:
            self._backend = backend
        self._ready.set()

        while True:
            job = self._queue.get()
            if job is None:
                with self._lock:
                    self._thread_alive = False
                return
            with self._lock:
                job.started = True
                job.started_at = time.monotonic()
                self._current = job
                self._jobs_total += 1
                if job.mutating:
                    self._pending_mutating -= 1  # BUSY owned by _current
            if job.abandoned or job.future.cancelled():
                with self._lock:
                    self._current = None
                continue

            try:
                result = job.fn()
            except CadMcpError as exc:
                result = fail_result(exc)
            except Exception as exc:  # noqa: BLE001 — one job must not kill worker
                log.exception("Unexpected exception in job %s (%s)", job.id, job.tool)
                result = fail_result(
                    fail(
                        "INTERNAL_ERROR",
                        f"{type(exc).__name__}: {exc}",
                        "Server defect; check server logs",
                        tool=job.tool,
                    )
                )
            with self._lock:
                self._current = None
                if job.abandoned:
                    self._late_results += 1
                if not job.future.done():
                    job.future.set_result(result)

    # ---------- health (no queue, no COM) ----------

    def _state(self) -> Literal["IDLE", "BUSY", "STUCK"]:
        if self._stuck_since is not None:
            return "STUCK"
        if self._current is not None or not self._queue.empty() or self._pending_mutating:
            return "BUSY"
        return "IDLE"

    def health(self, *, detail: bool = False) -> HealthReport:
        with self._lock:
            cur = self._current
            report = HealthReport(
                state=self._state(),
                tool=cur.tool if cur else None,
                elapsed_s=round(time.monotonic() - cur.started_at, 3) if cur and cur.started_at else None,
                queue_depth=self._queue.qsize(),
                pending_mutating=self._pending_mutating,
                thread_alive=self._thread_alive,
                backend_ready=self._backend is not None,
                stuck_reason=self._stuck_reason,
                late_results=self._late_results,
                jobs_total=self._jobs_total,
            )
        if self._probe is not None:
            windows, error = self._scan_windows_with_error()
            report.blocker = derive_blocker(windows, error)
            if detail:
                report.windows = windows
                report.detector_error = error
        return report

    def resolve_stuck(self) -> OpResult:
        """Clear STUCK after explicit user confirmation (doctor); never auto-kill."""
        with self._lock:
            was = self._stuck_reason
            self._stuck_since = None
            self._stuck_reason = None
            busy = self._current is not None
            late = self._late_results
        return ok_result(
            {
                "was_stuck": was is not None,
                "previous_reason": was,
                "worker_busy": busy,
                "late_results": late,
            }
        )

    def backend(self) -> CADBackend:
        if self._backend is None:
            if self._init_error is not None:
                if isinstance(self._init_error, CadMcpError):
                    raise self._init_error
                raise fail(
                    "COM_ATTACH_FAILED", f"Backend init failed: {self._init_error}",
                    "Run cadmcp doctor to check SolidWorks attach and version",
                )
            raise fail("COM_ATTACH_FAILED", "Backend not initialized", "Call start() and wait for init")
        return self._backend

    # ---------- probe (daemon + join timeout) ----------

    def _scan_windows(self) -> list[WindowInfo]:
        windows, _ = self._scan_windows_with_error()
        return windows

    def _scan_windows_with_error(self) -> tuple[list[WindowInfo] | None, str | None]:
        if self._probe is None:
            return None, None
        box: dict = {}

        def _target() -> None:
            try:
                box["w"] = self._probe.scan()  # type: ignore[union-attr]
            except Exception as exc:  # noqa: BLE001 — probe failure must not break health
                box["e"] = f"{type(exc).__name__}: {exc}"

        t = threading.Thread(target=_target, name="cadmcp-detector", daemon=True)
        t.start()
        t.join(self._detector_timeout_s)
        if t.is_alive():
            return None, f"detector_timeout>{self._detector_timeout_s}s"
        return box.get("w"), box.get("e")
