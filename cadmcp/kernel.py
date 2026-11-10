"""Op-sequence kernel (v4 §10/17 W2-6): sole dispatch path for chat tools / batch / spec macros.

Every entry calls `Kernel.dispatch(name, args)` so three rules hold for all paths:

1. **Validate at boundary**: args pass jsonschema (input_schema) first; else INVALID_ARGUMENT,
   no handler (typos must not be silently ignored);
2. **Single writer for state**: state_version increments only in kernel, only on **successful**
   mutating tools; partial failure (side_effect=APPLIED) does not increment—caller reads fingerprint;
3. **Verification loop**: verify_delta tools fingerprint before/after; success attaches Delta and
   RebuildReport on OpResult.

Verification policy (cost tradeoff, centralized here):
- Feature ops (extrude etc.): verify_delta=True → dual fingerprint + rebuild;
- Sketch draw, open/close/save doc: mutating but verify_delta=False—no geometry fingerprint change;
  feedback from handler payload (e.g. entity_count).
- If fingerprint cost on real SW is material, tighten verify_delta set, do not bypass this layer.

Failure mapping:
- CadMcpError → OpResult as-is (side_effect / hint / context preserved);
- Unexpected → INTERNAL_ERROR (server defect); mutating conservatively APPLIED; log.exception.
"""
from __future__ import annotations

import difflib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import jsonschema

from cadmcp.backend.protocol.models import FingerprintSI
from cadmcp.backend.protocol.protocol import CADBackend
from cadmcp.errors import CadMcpError, ErrorInfo, SideEffect, fail
from cadmcp.registry import ToolRegistry, ToolSpec
from cadmcp.result import Delta, GeometrySnapshot, OpResult, RebuildReport, fail_result, ok_result
from cadmcp.units import UnitContext
from cadmcp.verification import attach_file_evidence, build_mutation_verification

if TYPE_CHECKING:  # deferred annotations; no import cycle at runtime
    from cadmcp.executor import HealthReport
    from cadmcp.toolbox import ToolVisibility

log = logging.getLogger(__name__)


@dataclass
class OpContext:
    """Sole handler environment: backend, unit binder, sandbox root, current state version."""

    backend: CADBackend
    units: UnitContext
    workspace: Path
    state_version: int
    tool_name: str
    health: Callable[[], HealthReport] | None = None
    """status only: health provider with detail tier (build_stack); None if unbound."""
    dispatch: Callable[[str, dict | None], OpResult] | None = None
    """Recipe replay etc.; default None."""
    visibility: ToolVisibility | None = None
    """Toolbox visibility (build_stack); None → list/open/close/search report INTERNAL."""
    registry: ToolRegistry | None = None
    """Full registry for toolbox list/search (decoupled from visibility filter)."""


class Kernel:
    def __init__(
        self,
        registry: ToolRegistry,
        backend: CADBackend,
        *,
        workspace: Path,
        units: UnitContext | None = None,
        verify_mutations: bool = True,
        health_provider: Callable[[], HealthReport] | None = None,
        visibility: ToolVisibility | None = None,
    ) -> None:
        self._registry = registry
        self._backend = backend
        self._workspace = workspace
        self._units = units or UnitContext("mm")
        self._verify = verify_mutations
        self._health = health_provider  # status tool; default None → status INTERNAL
        self._visibility = visibility
        self.state_version = 0

    # ---------- dispatch ----------

    def dispatch(self, name: str, args: dict | None = None) -> OpResult:
        args = args or {}
        spec = self._registry.get(name)
        if spec is None:
            close = difflib.get_close_matches(name, self._registry.names(), n=3, cutoff=0.5)
            hint = f"Did you mean: {', '.join(close)}?" if close else "Call tools/list for available tools"
            return fail_result(
                fail("INVALID_ARGUMENT", f"Unknown tool: {name}", hint, tool=name),
                state_version=self.state_version,
            )

        err = self._validate(spec, args)
        if err is not None:
            return fail_result(err, state_version=self.state_version)

        ctx = OpContext(
            backend=self._backend,
            units=self._units,
            workspace=self._workspace,
            state_version=self.state_version,
            tool_name=spec.name,
            health=self._health,
            dispatch=self.dispatch,
            visibility=self._visibility,
            registry=self._registry,
        )

        before = self._fingerprint_if_verify(spec)
        try:
            payload = spec.handler(ctx, **args)
        except CadMcpError as exc:
            return fail_result(exc, state_version=self.state_version)
        except Exception as exc:  # noqa: BLE001 — unexpected → server defect
            log.exception("Unexpected exception in tool %s", spec.name)
            return fail_result(
                fail(
                    "INTERNAL_ERROR",
                    f"{type(exc).__name__}: {exc}",
                    "Server defect; check server logs—do not retry blindly",
                    side_effect=_conservative_side_effect(spec),
                    tool=spec.name,
                ),
                state_version=self.state_version,
            )

        if not spec.mutating:
            return ok_result(payload, state_version=self.state_version)

        self.state_version += 1
        if not (self._verify and spec.verify_delta):
            verification = None
            if spec.name == "export" and isinstance(payload, dict) and payload.get("path"):
                verification = attach_file_evidence(None, str(payload["path"]))
            return ok_result(
                payload, state_version=self.state_version, verification=verification
            )

        # Verification layer failure must not hide a successful op: warn and return result
        try:
            outcome = self._backend.force_rebuild()
            snapshot = self._snapshot(self._backend.fingerprint())
        except CadMcpError as exc:
            log.warning("Verification read failed (%s: %s)", exc.code, exc.message)
            return ok_result(
                payload,
                state_version=self.state_version,
                warnings=[f"Verification read failed, result not re-checked: {exc.code}: {exc.message}"],
            )
        delta = Delta.between(before, snapshot) if before is not None else None
        rebuild = RebuildReport(
            ok=outcome.ok,
            feature_errors=list(outcome.feature_errors),
        )
        verification = build_mutation_verification(delta=delta, rebuild=rebuild)
        if spec.name == "export" and isinstance(payload, dict) and payload.get("path"):
            verification = attach_file_evidence(verification, str(payload["path"]))
        return ok_result(
            payload,
            delta=delta,
            rebuild=rebuild,
            verification=verification,
            state_version=self.state_version,
        )

    # ---------- internal ----------

    def _validate(self, spec: ToolSpec, args: dict) -> ErrorInfo | None:
        if not isinstance(args, dict):
            return fail(
                "INVALID_ARGUMENT", f"Arguments must be an object, got {type(args).__name__}",
                'Pass an object, e.g. {"radius": 5}',
            )
        validator = jsonschema.Draft202012Validator(spec.input_schema)
        errors = sorted(validator.iter_errors(args), key=lambda e: list(e.absolute_path))
        if not errors:
            return None
        first = errors[0]
        path = ".".join(str(p) for p in first.absolute_path) or "(root)"
        prop_desc = self._property_hint(spec, first)
        return fail(
            "INVALID_ARGUMENT",
            f"Argument validation failed: {path}: {first.message}",
            prop_desc or f"Fix args per {spec.name} inputSchema",
            tool=spec.name,
            schema_errors=[f"{'.'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}"
                           for e in errors[:5]],
        )

    @staticmethod
    def _property_hint(spec: ToolSpec, err: jsonschema.ValidationError) -> str | None:
        """If error is on a top-level property, attach schema description (teaching hint)."""
        elems = list(err.absolute_path)
        if len(elems) == 1 and isinstance(elems[0], str):
            prop = spec.input_schema.get("properties", {}).get(elems[0])
            if isinstance(prop, dict) and prop.get("description"):
                return str(prop["description"])
        return None

    def _fingerprint_if_verify(self, spec: ToolSpec) -> GeometrySnapshot | None:
        """Pre-op fingerprint; read failure (e.g. no doc) → no delta, handler still runs."""
        if not (self._verify and spec.verify_delta and spec.mutating):
            return None
        try:
            return self._snapshot(self._backend.fingerprint())
        except CadMcpError as exc:
            log.warning("Pre-op fingerprint failed (%s: %s); no delta on this call", exc.code, exc.message)
            return None

    def _snapshot(self, fp: FingerprintSI) -> GeometrySnapshot:
        """SI fingerprint → external mm snapshot (unit conversion only on this boundary)."""
        u = self._units
        return GeometrySnapshot(
            volume_mm3=u.volume_from_m3(fp.volume_m3),
            surface_area_mm2=u.area_from_m2(fp.surface_area_m2),
            mass_kg=fp.mass_kg,
            face_count=fp.face_count,
            edge_count=fp.edge_count,
            bbox_mm=tuple(u.tuple_from_m(fp.bbox_m)),  # type: ignore[arg-type]
        )


def _conservative_side_effect(spec: ToolSpec) -> SideEffect:
    """Unexpected exception: mutating → APPLIED (may have applied; read state before retry)."""
    return SideEffect.APPLIED if spec.mutating else SideEffect.NONE


__all__ = ["Kernel", "OpContext"]


def schema_json(spec: ToolSpec) -> str:
    """Stable schema serialization for MCP tools/list and snapshot tests."""
    return json.dumps(
        {"name": spec.name, "description": spec.description, "inputSchema": spec.input_schema},
        ensure_ascii=False,
        sort_keys=True,
    )
