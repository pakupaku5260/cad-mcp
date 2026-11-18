"""DesignSpec controlled runner (F11/F12): topological execute + param substitute + assert.

Pure orchestration — no COM, no executor changes. L1 checkpoint capture/resume lives in
cadmcp.checkpoints (save_copy_as + fingerprint; does not bump state_version).
Each feature is a normal Kernel.dispatch with its own OpResult. Outer tool semantics match
replay_recipe: handler returns a payload; step failures set payload ok=false without
raising (so the outer OpResult stays ok=true unless precheck/path guards fail).
"""
from __future__ import annotations

import heapq
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from cadmcp import checkpoints as cp
from cadmcp.design_spec import select_variant
from cadmcp.errors import fail
from cadmcp.recipe import check_assert
from cadmcp.registry import ToolRegistry
from cadmcp.result import OpResult

DispatchFn = Callable[[str, dict | None], OpResult]


class _RunnerEnv(Protocol):
    dispatch: DispatchFn
    registry: ToolRegistry | None
    workspace: Path
    state_version: int | None
    backend: Any


def topological_order(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Stable Kahn sort: same-layer features keep original features[] index order."""
    features: list[dict[str, Any]] = list(spec["features"])
    n = len(features)
    name_to_i = {f["name"]: i for i, f in enumerate(features)}
    indeg = [0] * n
    children: list[list[int]] = [[] for _ in range(n)]
    for i, feat in enumerate(features):
        for dep in feat.get("depends_on") or []:
            j = name_to_i.get(dep)
            if j is None:
                raise fail(
                    "INVALID_ARGUMENT",
                    f"design_spec.features[{i}].depends_on unknown {dep!r}",
                    "depends_on must name a features[].name",
                )
            children[j].append(i)
            indeg[i] += 1

    # Min-heap of ready original indices → stable among equal-indegree peers.
    ready: list[int] = [i for i in range(n) if indeg[i] == 0]
    heapq.heapify(ready)
    ordered: list[dict[str, Any]] = []
    while ready:
        i = heapq.heappop(ready)
        ordered.append(features[i])
        for j in children[i]:
            indeg[j] -= 1
            if indeg[j] == 0:
                heapq.heappush(ready, j)

    if len(ordered) != n:
        raise fail(
            "INVALID_ARGUMENT",
            "design_spec.features depends_on cycle (defensive)",
            "Remove the cyclic depends_on edge",
        )
    return ordered


def substitute_params(value: Any, params: dict[str, Any], *, path: str = "design_spec") -> Any:
    """Recursively replace ``{"$param": "<name>"}`` with ``params[name]``."""
    if isinstance(value, dict):
        if "$param" in value:
            if set(value) != {"$param"}:
                raise fail(
                    "INVALID_ARGUMENT",
                    f"{path} param ref must be only {{\"$param\": name}}, got keys {sorted(value)}",
                    'Use {"$param": "thickness"}',
                )
            name = value["$param"]
            if type(name) is bool or not isinstance(name, (str, int, float)):
                raise fail(
                    "INVALID_ARGUMENT",
                    f"{path}.$param must be a scalar name, got {type(name).__name__}",
                    "Pass the parameter name as a string",
                )
            key = str(name)
            if key not in params:
                raise fail(
                    "INVALID_ARGUMENT",
                    f"{path}: unknown param {key!r}",
                    f"Declare it under design_spec.params (known: {', '.join(sorted(params)) or 'none'})",
                )
            return params[key]
        return {
            k: substitute_params(v, params, path=f"{path}.{k}")
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [
            substitute_params(v, params, path=f"{path}[{i}]")
            for i, v in enumerate(value)
        ]
    return value


def _precheck(
    spec: dict[str, Any],
    registry: ToolRegistry,
    *,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Resolve topology + substitute all args; verify every tool exists. Zero dispatch."""
    ordered = topological_order(spec)
    params = dict(params if params is not None else (spec.get("params") or {}))
    known = set(registry.names())
    prepared: list[dict[str, Any]] = []
    for i, feat in enumerate(ordered):
        tool = str(feat["tool"])
        if tool not in known:
            import difflib

            close = difflib.get_close_matches(tool, sorted(known), n=3, cutoff=0.5)
            hint = (
                f"Did you mean: {', '.join(close)}?"
                if close
                else "Call tools/list for available tools"
            )
            raise fail(
                "INVALID_ARGUMENT",
                f"design_spec.features tool {tool!r} is not registered (feature {feat['name']!r})",
                hint,
                tool=tool,
            )
        orig_i = next(
            j for j, f in enumerate(spec["features"]) if f["name"] == feat["name"]
        )
        args = substitute_params(
            feat.get("args") or {},
            params,
            path=f"design_spec.features[{orig_i}].args",
        )
        if not isinstance(args, dict):
            raise fail(
                "INVALID_ARGUMENT",
                f"design_spec.features[{orig_i}].args must expand to an object",
                "Param substitution must leave a JSON object",
            )
        prepared.append({**feat, "args": args, "_order_index": i, "_orig_index": orig_i})
    return prepared


def _validate_resume(
    env: _RunnerEnv,
    spec: dict[str, Any],
    prepared: list[dict[str, Any]],
    resume_from: str,
) -> tuple[int, str, dict[str, Any]]:
    """C2(a–d) read-only checks. Returns (checkpoint_index, doc_key, sidecar meta)."""
    declared = list(spec.get("checkpoints") or [])
    if resume_from not in declared:
        raise fail(
            "INVALID_ARGUMENT",
            f"resume_from {resume_from!r} is not in design_spec.checkpoints",
            f"Declared checkpoints: {', '.join(declared) or '(none)'}",
        )
    order_names = [f["name"] for f in prepared]
    try:
        checkpoint_index = order_names.index(resume_from)
    except ValueError as exc:
        raise fail(
            "INVALID_ARGUMENT",
            f"resume_from {resume_from!r} is not a feature name",
            "checkpoints must name features[].name",
        ) from exc

    info = env.backend.active_document()
    if info is None:
        raise fail(
            "NO_ACTIVE_DOCUMENT",
            "No active document for resume_from",
            "Open or create the document before design_run",
        )
    key = cp.doc_key(info)
    meta = cp.find(env.workspace, key, resume_from)
    if meta is None:
        raise fail(
            "PATH_NOT_FOUND",
            f"Checkpoint {resume_from!r} not found for this document.",
            "Run design_run once with checkpoints declared before resume_from",
        )
    # C2(d): sidecar must be parseable — find() already parsed; require required fields.
    if not isinstance(meta.get("path"), str) or not meta.get("path"):
        raise fail(
            "INVALID_ARGUMENT",
            f"Checkpoint sidecar for {resume_from!r} is invalid (missing path).",
            "Delete corrupt sidecars under .cadmcp/checkpoints and re-run",
        )
    meta_type = meta.get("doc_type")
    active_type = getattr(info, "doc_type", None) or "part"
    if meta_type != active_type:
        raise fail(
            "INVALID_ARGUMENT",
            f"Checkpoint doc_type {meta_type!r} does not match active document "
            f"{active_type!r}",
            "Resume only against the same document kind that created the snapshot",
        )
    return checkpoint_index, key, meta


def run_design(
    env: _RunnerEnv,
    spec: dict[str, Any],
    *,
    stop_on_error: bool = True,
    resume_from: str | None = None,
    variant: str | None = None,
) -> dict[str, Any]:
    """Precheck → optional resume restore → ordered dispatch → asserts → verify_model."""
    if env.registry is None:
        raise fail(
            "INTERNAL_ERROR",
            "design_run requires ctx.registry",
            "Server defect; Kernel must bind registry on OpContext",
        )
    if env.dispatch is None:
        raise fail(
            "INTERNAL_ERROR",
            "design_run requires ctx.dispatch",
            "Server defect; Kernel must bind dispatch on OpContext",
        )

    effective_params = select_variant(spec, variant)
    prepared = _precheck(spec, env.registry, params=effective_params)
    declared = list(spec.get("checkpoints") or [])
    declared_set = set(declared)
    snapshots: list[dict[str, Any]] = []
    skipped: list[str] = []
    resumed_from: str | None = None
    checkpoint_index = -1

    if resume_from is not None:
        checkpoint_index, doc_key, _meta = _validate_resume(
            env, spec, prepared, resume_from
        )
        # Side effects only after all C2 checks pass.
        cp.restore(env.backend, env.workspace, key=doc_key, name=resume_from)
        resumed_from = resume_from
        skipped = [f["name"] for f in prepared if f["_order_index"] <= checkpoint_index]

    steps: list[dict[str, Any]] = []
    failed: dict[str, Any] | None = None
    aborted = False

    for feat in prepared:
        order_i = int(feat["_order_index"])
        if resumed_from is not None and order_i <= checkpoint_index:
            continue
        if aborted:
            break
        tool = str(feat["tool"])
        result = env.dispatch(tool, dict(feat["args"]))
        entry: dict[str, Any] = {
            "index": order_i,
            "name": feat["name"],
            "tool": tool,
            "ok": result.ok,
            "error_code": result.error.code if result.error else None,
            "result_keys": sorted(result.result) if result.result else None,
            "delta_changed": sorted(result.delta.changed) if result.delta else None,
            "state_version": result.state_version,
        }
        assertion = feat.get("assert")
        step_failed = False
        if isinstance(assertion, dict) and assertion:
            reason = check_assert(assertion, result)
            entry["assert_ok"] = reason is None
            if reason is not None:
                entry["assert_detail"] = reason
                step_failed = True
        if not result.ok:
            if not (isinstance(assertion, dict) and assertion.get("ok") is False):
                step_failed = True

        steps.append(entry)
        if entry["ok"] and feat["name"] in declared_set and not step_failed:
            snap = cp.capture(
                env.backend,
                env.workspace,
                name=str(feat["name"]),
                index=order_i,
                state_version=entry["state_version"],
            )
            snapshots.append(snap)

        if step_failed and failed is None:
            failed = {
                "index": order_i,
                "name": feat["name"],
                "error_code": entry["error_code"],
            }
            if stop_on_error:
                aborted = True

    verification: dict[str, Any] | None = None
    groups = list((spec.get("verify") or {}).get("groups") or [])
    thresholds = dict((spec.get("verify") or {}).get("thresholds") or {})
    if groups and not aborted:
        vr = env.dispatch(
            "verify_model",
            {"groups": groups, "thresholds": thresholds},
        )
        # verify_model keeps its envelope ok=True even when checks fail; the verdict
        # lives in result.verification.status ("verified" / "failed" / "unverified").
        block = (vr.result or {}).get("verification") or {}
        status = block.get("status") if isinstance(block, dict) else None
        verification = {
            "ok": vr.ok and status == "verified",
            "error_code": vr.error.code if vr.error else None,
            "result": vr.result,
        }

    declared_outputs = list(spec.get("outputs") or [])
    written: list[dict[str, Any]] = []
    if not aborted:
        for out in declared_outputs:
            written.append(_export_output(env, out))

    outputs_ok = all(w["ok"] for w in written)
    return {
        "ok": (
            failed is None
            and (verification is None or verification["ok"])
            and outputs_ok
        ),
        "spec": {
            "kind": spec["kind"],
            "doc": spec["doc"],
            "feature_count": len(spec["features"]),
            "verify_groups": groups,
        },
        "steps": steps,
        "failed_step": failed,
        "verification": verification,
        "checkpoints": {
            "declared": declared,
            "snapshots": snapshots,
            "resumed_from": resumed_from,
            "skipped": skipped,
        },
        "outputs": {
            "declared": [o["kind"] for o in declared_outputs],
            "written": written,
        },
    }


def _export_output(env: _RunnerEnv, out: dict[str, Any]) -> dict[str, Any]:
    """Dispatch export(overwrite=False); never raises — failures go into the entry."""
    kind = str(out["kind"])
    path = str(out["path"])
    entry: dict[str, Any] = {
        "kind": kind,
        "path": path,
        "ok": False,
        "bytes": None,
        "error_code": None,
    }
    result = env.dispatch("export", {"path": path, "overwrite": False})
    if result.ok:
        saved = (result.result or {}).get("path") or path
        entry["path"] = str(saved)
        try:
            size = Path(str(saved)).stat().st_size
        except OSError:
            size = 0
        entry["ok"] = True
        entry["bytes"] = size
        return entry
    entry["error_code"] = result.error.code if result.error else None
    if result.error is not None:
        entry["detail"] = result.error.message
    return entry


__all__ = [
    "run_design",
    "substitute_params",
    "topological_order",
]
