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
from cadmcp.registry import EXPECT_PATH, EXPECT_TITLE, ToolRegistry, ToolSpec
from cadmcp.result import Delta, GeometrySnapshot, OpResult, RebuildReport, fail_result, ok_result
from cadmcp.units import UnitContext
from cadmcp.verification import attach_file_evidence, build_mutation_verification

if TYPE_CHECKING:  # deferred annotations; no import cycle at runtime
    from cadmcp.executor import HealthReport
    from cadmcp.toolbox import ToolVisibility
    from cadmcp.transaction import TxManager

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
    tx: TxManager | None = None
    """Active transaction manager (F4); None when Kernel has no tx support."""


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
        from cadmcp.transaction import TxManager

        self._registry = registry
        self._backend = backend
        self._workspace = workspace
        self._units = units or UnitContext("mm")
        self._verify = verify_mutations
        self._health = health_provider  # status tool; default None → status INTERNAL
        self._visibility = visibility
        self.state_version = 0
        self._tx = TxManager(workspace)

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

        # F6: optional expect_* doc guard — before any side effect / tx capture / fingerprint
        if spec.mutating:
            guard_err = self._check_expect_document(args)
            if guard_err is not None:
                return fail_result(guard_err, state_version=self.state_version)
            args.pop(EXPECT_TITLE, None)
            args.pop(EXPECT_PATH, None)

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
            tx=self._tx,
        )

        # F4: capture compensator pre-state only when an active same-doc tx exists
        tx_capture: dict = {}
        if (
            spec.mutating
            and not spec.name.startswith("tx_")
            and self._tx.active is not None
            and self._tx.active.status == "active"
        ):
            if self._tx_doc_matches():
                tx_capture = self._tx.capture_before(self._backend, spec.name, args)
            else:
                self._tx.note_doc_mismatch()

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
        tx_warnings: list[str] = []
        if (
            not spec.name.startswith("tx_")
            and self._tx.active is not None
            and self._tx.active.status == "active"
        ):
            if self._tx_doc_matches():
                tx_warnings = self._tx.record_step(
                    tool=spec.name,
                    args=args,
                    state_version=self.state_version,
                    payload=payload if isinstance(payload, dict) else None,
                    delta_changed=None,  # filled below when delta known
                    capture=tx_capture,
                )
            else:
                self._tx.note_doc_mismatch()
                tx_warnings = ["TX_UNSUPPORTED_STEP: document binding drift (step not journaled for compensate)"]

        if not (self._verify and spec.verify_delta):
            verification = None
            if spec.name == "export" and isinstance(payload, dict) and payload.get("path"):
                verification = attach_file_evidence(None, str(payload["path"]))
            return ok_result(
                payload,
                state_version=self.state_version,
                verification=verification,
                warnings=tx_warnings or None,
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
                warnings=[
                    *tx_warnings,
                    f"Verification read failed, result not re-checked: {exc.code}: {exc.message}",
                ],
            )
        delta = Delta.between(before, snapshot) if before is not None else None
        # Patch last journal step with delta.changed when present
        if (
            delta is not None
            and self._tx.active is not None
            and self._tx.active.steps
            and not spec.name.startswith("tx_")
        ):
            self._tx.active.steps[-1].delta_changed = list(delta.changed)
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
            warnings=tx_warnings or None,
        )

    # ---------- internal ----------

    def _check_expect_document(self, args: dict) -> CadMcpError | None:
        """Reject mutating calls whose expect_* does not match the active document.

        When either expect_title or expect_path is provided (non-None), mismatch **or**
        no active document → WRONG_DOCUMENT (side_effect=NONE). Omitted expect_* keeps
        prior tool behaviour (e.g. NO_ACTIVE_DOCUMENT from handlers).
        """
        if EXPECT_TITLE not in args and EXPECT_PATH not in args:
            return None
        expect_title = args.get(EXPECT_TITLE)
        expect_path = args.get(EXPECT_PATH)
        if expect_title is None and expect_path is None:
            return None

        try:
            info = self._backend.active_document()
        except CadMcpError as exc:
            # Treat backend doc-read failure as non-matching context for the guard
            if exc.code == "NO_ACTIVE_DOCUMENT":
                info = None
            else:
                raise

        actual_title = info.title if info is not None else None
        actual_path = info.path if info is not None else None
        mismatch = False
        if info is None:
            mismatch = True
        else:
            if expect_title is not None and str(expect_title).strip() != str(actual_title).strip():
                mismatch = True
            if expect_path is not None and not _paths_match(str(expect_path), actual_path):
                mismatch = True
        if not mismatch:
            return None
        return fail(
            "WRONG_DOCUMENT",
            "Active document does not match expect_title/expect_path",
            "Call list_open_documents or get_active_document; activate the intended "
            "document or correct expect_title/expect_path",
            side_effect=SideEffect.NONE,
            expected_title=expect_title,
            expected_path=expect_path,
            actual_title=actual_title,
            actual_path=actual_path,
        )

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

    def _tx_doc_matches(self) -> bool:
        """True when active doc still matches the transaction binding (single-doc F4)."""
        session = self._tx.active
        if session is None:
            return False
        try:
            info = self._backend.active_document()
        except CadMcpError:
            return False
        if info is None:
            return False
        return info.title == session.title and (info.path or None) == (session.path or None)

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


def _paths_match(expected: str, actual: str | None) -> bool:
    if actual is None:
        return False
    try:
        left = Path(expected).expanduser().resolve()
        right = Path(actual).expanduser().resolve()
    except OSError:
        left = Path(expected)
        right = Path(actual)
    return os_path_norm(left) == os_path_norm(right)


def os_path_norm(path: Path) -> str:
    import os

    return os.path.normcase(os.path.normpath(str(path)))


__all__ = ["Kernel", "OpContext"]


def schema_json(spec: ToolSpec) -> str:
    """Stable schema serialization for MCP tools/list and snapshot tests."""
    return json.dumps(
        {"name": spec.name, "description": spec.description, "inputSchema": spec.input_schema},
        ensure_ascii=False,
        sort_keys=True,
    )
