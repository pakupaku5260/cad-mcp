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
import json
import logging
import os
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
_TOOL_TIMEOUT_ENV = "CADMCP_TOOL_TIMEOUTS"
_TOOL_TIMEOUT_MIN_S = 1.0
_TOOL_TIMEOUT_MAX_S = 300.0


def parse_tool_timeouts(raw: str | None = None) -> dict[str, float]:
    """Parse CADMCP_TOOL_TIMEOUTS JSON object; invalid entries are skipped with a warning."""
    text = raw if raw is not None else os.environ.get(_TOOL_TIMEOUT_ENV)
    if not text or not str(text).strip():
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        log.warning("%s ignored: invalid JSON (%s)", _TOOL_TIMEOUT_ENV, exc)
        return {}
    if not isinstance(data, dict):
        log.warning("%s ignored: expected a JSON object", _TOOL_TIMEOUT_ENV)
        return {}
    out: dict[str, float] = {}
    for key, value in data.items():
        name = str(key).strip()
        if not name:
            continue
        try:
            secs = float(value)
        except (TypeError, ValueError):
            log.warning("%s: skip %r (not a number)", _TOOL_TIMEOUT_ENV, key)
            continue
        if secs < _TOOL_TIMEOUT_MIN_S or secs > _TOOL_TIMEOUT_MAX_S:
            log.warning(
                "%s: skip %s=%r (must be in [%.0f, %.0f]s)",
                _TOOL_TIMEOUT_ENV,
                name,
                value,
                _TOOL_TIMEOUT_MIN_S,
                _TOOL_TIMEOUT_MAX_S,
            )
            continue
        out[name] = secs
    return out


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
        self._tool_timeouts = parse_tool_timeouts()
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
                        "COM cannot be interrupted; clear dialogs in SolidWorks, then check "
                        "status/dialogs and retry. resolve_stuck() is an internal recovery "
                        "method invoked by the host/client, not a CLI command",
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

        if timeout is not None:
            limit = timeout
        elif tool in self._tool_timeouts:
            limit = self._tool_timeouts[tool]
        else:
            limit = self._tiers.get(timeout_class, 60.0)
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
        dialog_ctx = None
        hint = (
            "COM cannot be interrupted; check SolidWorks dialogs/status, then "
            "resolve_stuck() (internal recovery invoked by the host/client, not a "
            "CLI command)—do not retry blindly"
        )
        if windows:
            from cadmcp.dialog_policy import classify_dialog, dialog_context, hint_for_policy
            from cadmcp.probe import primary_modal_dialog

            primary = primary_modal_dialog(windows)
            if primary is not None:
                policy = classify_dialog(
                    title=primary.title,
                    text=primary.text or "",
                    buttons=list(primary.buttons or []),
                )
                dialog_ctx = dialog_context(
                    title=primary.title,
                    text=primary.text,
                    buttons=list(primary.buttons or []),
                    modal=primary.modal,
                )
                hint = (
                    f"{hint_for_policy(policy)}; then resolve_stuck() "
                    "(internal host/client recovery, not a CLI command)—do not retry blindly"
                )
        ctx: dict = {
            "tool": tool,
            "timeout_s": limit,
            "windows": [w.model_dump() for w in windows] if windows else [],
        }
        if dialog_ctx is not None:
            ctx["dialog"] = dialog_ctx
        return fail_result(
            fail(
                "EXEC_TIMEOUT",
                f"{tool} did not return within {limit}s; executor marked STUCK",
                hint,
                side_effect=SideEffect.APPLIED,
                **ctx,
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

            # F5: at most one automatic retry after COM_LOST when safe
            if self._should_retry_com_lost(job, result):
                result = self._retry_after_com_lost(job, result)

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

    # ---------- F5 COM_LOST one-shot retry ----------

    @staticmethod
    def _should_retry_com_lost(job: _Job, result: OpResult) -> bool:
        if result.ok or result.error is None:
            return False
        if result.error.code != "COM_LOST":
            return False
        # Reads: always eligible for one reattach+retry
        if not job.mutating:
            return True
        # Writes: only when we know the call did not apply (side_effect=none)
        return result.error.side_effect == SideEffect.NONE

    def _retry_after_com_lost(self, job: _Job, first: OpResult) -> OpResult:
        """reattach then re-run job.fn once; never retries APPLIED/UNKNOWN mutating."""
        backend = self._backend
        reattach_info: dict = {}
        try:
            if backend is None or not hasattr(backend, "reattach"):
                return self._annotate_com_lost(first, retried=False, reason="no_reattach")
            reattach_info = backend.reattach() or {}
        except CadMcpError as exc:
            info = exc.to_info()
            ctx = dict(info.context)
            ctx.update({"retried": False, "reattach_attempted": True, "reattach_failed": True})
            return fail_result(
                fail(
                    info.code,
                    info.message,
                    info.hint,
                    side_effect=info.side_effect,
                    **ctx,
                )
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("reattach failed unexpectedly for job %s", job.id)
            return fail_result(
                fail(
                    "COM_ATTACH_FAILED",
                    f"reattach failed: {type(exc).__name__}: {exc}",
                    "Start SolidWorks and retry; if STA cannot recover, restart the cadmcp server",
                    side_effect=SideEffect.NONE,
                    retried=False,
                    reattach_attempted=True,
                )
            )

        try:
            second = job.fn()
        except CadMcpError as exc:
            second = fail_result(exc)
        except Exception as exc:  # noqa: BLE001
            log.exception("Retry after COM_LOST crashed for job %s (%s)", job.id, job.tool)
            second = fail_result(
                fail(
                    "INTERNAL_ERROR",
                    f"{type(exc).__name__}: {exc}",
                    "Server defect; check server logs",
                    tool=job.tool,
                    retried=True,
                )
            )

        if second.ok:
            warnings = list(second.warnings or [])
            warnings.append("Recovered via reattach after COM_LOST (one automatic retry)")
            return OpResult(
                ok=True,
                result=second.result,
                delta=second.delta,
                rebuild=second.rebuild,
                verification=second.verification,
                state_version=second.state_version,
                warnings=warnings,
            )
        if second.error is not None:
            return self._annotate_com_lost(
                second,
                retried=True,
                reattach_info=reattach_info,
            )
        return second

    @staticmethod
    def _annotate_com_lost(
        result: OpResult,
        *,
        retried: bool,
        reason: str | None = None,
        reattach_info: dict | None = None,
    ) -> OpResult:
        if result.error is None:
            return result
        ctx = dict(result.error.context)
        ctx["retried"] = retried
        ctx["reattach_attempted"] = True
        if reason:
            ctx["retry_skipped"] = reason
        if reattach_info:
            ctx["reattach"] = reattach_info
        err = fail(
            result.error.code,
            result.error.message,
            result.error.hint,
            side_effect=result.error.side_effect,
            **ctx,
        )
        return fail_result(err, state_version=result.state_version, warnings=list(result.warnings or []))

    # ---------- probe (daemon + join timeout) ----------

    def _scan_windows(self) -> list[WindowInfo]:
        windows, _ = self._scan_windows_with_error()
        return windows

    def scan_dialogs(self) -> tuple[list[WindowInfo] | None, str | None]:
        """Public side-thread scan for session_dialogs (bypass_queue tools)."""
        return self._scan_windows_with_error()

    def respond_dialog(self, action: str, match: str | None = None) -> dict:
        """Whitelist respond on side thread (no COM / STA)."""
        if self._probe is None:
            raise fail(
                "INTERNAL_ERROR",
                "Dialog probe not wired",
                "Start the server with a DialogProbe (Win32 or Fake)",
            )
        respond = getattr(self._probe, "respond", None)
        if not callable(respond):
            raise fail(
                "INTERNAL_ERROR",
                "Dialog probe does not support respond()",
                "Use Win32DialogProbe or FakeDialogProbe",
            )
        box: dict = {}

        def _target() -> None:
            try:
                box["r"] = respond(action, match)  # type: ignore[misc]
            except CadMcpError as exc:
                box["err"] = exc
            except Exception as exc:  # noqa: BLE001 — surface as INTERNAL
                box["err"] = fail(
                    "INTERNAL_ERROR",
                    f"{type(exc).__name__}: {exc}",
                    "session_respond failed; inspect session_dialogs and retry or dismiss manually",
                )

        t = threading.Thread(target=_target, name="cadmcp-dialog-respond", daemon=True)
        t.start()
        t.join(self._detector_timeout_s)
        if t.is_alive():
            raise fail(
                "EXEC_TIMEOUT",
                f"session_respond did not return within {self._detector_timeout_s}s",
                "Dialog UI may be hung; dismiss manually in SolidWorks",
            )
        if "err" in box:
            raise box["err"]
        return box["r"]

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
