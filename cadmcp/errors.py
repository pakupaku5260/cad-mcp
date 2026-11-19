"""Error system: SCREAMING_SNAKE catalog, unified constructor, side-effect levels (v4 §10, §17 W1-1).

Conventions:
- Each error = code (stable, machine-readable) + message (why) + hint (concrete next step).
  Hints are written for the model as "errors as instructions" and are required — error
  quality caps how well the model can self-correct.
- side_effect separates "operation did not occur (safe to retry)" from "operation occurred (do not blindly retry)".
- New codes must be registered in CATALOG first (validated at construction); the catalog is the doc;
  contract tests enforce catalog rules.

F3: CATALOG entries are ErrorDef records with optional remediation metadata
({auto, action, requires_confirmation}). Metadata is catalog/resource-layer only —
it does **not** enter ErrorInfo / OpResult (extra="forbid" unchanged).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class SideEffect(StrEnum):
    """Side-effect level: required on error responses (v4 §10)."""

    NONE = "none"  # Operation did not occur — safe to retry
    APPLIED = "applied"  # Operation occurred — do not blindly retry; known state is in context
    UNKNOWN = "unknown"  # Mutation may have partially applied (e.g. failed rollback) — inspect before retry


@dataclass(frozen=True, slots=True)
class ErrorDef:
    """Catalog entry: default description + optional remediation (F3).

    Non-first-batch codes keep auto=False, action="", requires_confirmation=False.
    """

    message: str
    auto: bool = False
    action: str = ""
    requires_confirmation: bool = False


# Plan aliases (documentation only; actual CATALOG keys below):
#   SKETCH_NOT_OPEN → NO_ACTIVE_SKETCH
#   FEATURE_FAILED  → FEATURE_CREATE_FAILED
# PATH_* = six codes; REBUILD_FAILED is out of this batch.
FIRST_BATCH_ERROR_CODES: frozenset[str] = frozenset({
    "REF_STALE",
    "REF_AMBIGUOUS",
    "EXECUTOR_BUSY",
    "EXEC_TIMEOUT",
    "COM_LOST",
    "WRONG_DOCUMENT",
    "NO_ACTIVE_SKETCH",
    "FEATURE_CREATE_FAILED",
    "PATH_INVALID",
    "PATH_OUTSIDE_SANDBOX",
    "PATH_SYMLINK_DENIED",
    "PATH_EXTENSION_DENIED",
    "PATH_OVERWRITE_DENIED",
    "PATH_NOT_FOUND",
})


def _def(
    message: str,
    *,
    auto: bool = False,
    action: str = "",
    requires_confirmation: bool = False,
) -> ErrorDef:
    return ErrorDef(
        message=message,
        auto=auto,
        action=action,
        requires_confirmation=requires_confirmation,
    )


CATALOG: dict[str, ErrorDef] = {
    # --- General ---
    "INTERNAL_ERROR": _def("Unexpected server error"),
    "INVALID_ARGUMENT": _def("Invalid argument"),
    "NOT_IMPLEMENTED": _def("Feature not yet implemented"),
    # --- Executor ---
    "EXECUTOR_BUSY": _def(
        "Executor busy; new task rejected (no queueing)",
        auto=True,
        action=(
            "Wait briefly, then retry a read-only or idempotent query "
            "(e.g. get_active_document / list_features). Do not start concurrent writes."
        ),
    ),
    "QUEUE_FULL": _def("Task queue is full"),
    "EXEC_TIMEOUT": _def(
        "Single task exceeded tiered timeout",
        auto=False,
        requires_confirmation=True,
        action=(
            "Check for SolidWorks modal dialogs or oversized work; shrink the operation. "
            "Retry only when the prior call had side_effect=none — never blindly retry "
            "mutating / applied / unknown results."
        ),
    ),
    "EXEC_STUCK": _def("Executor stuck (STUCK); manual intervention required"),
    "EXEC_BLOCKED": _def("Executor blocked by modal dialog; COM call cannot return"),
    # --- Connection ---
    "SW_NOT_RUNNING": _def("SolidWorks is not running or cannot be attached"),
    "COM_ATTACH_FAILED": _def("COM attach failed"),
    "COM_CALL_FAILED": _def("COM call raised an exception"),
    "COM_LOST": _def(
        "SolidWorks COM connection lost after a working session (RPC/process exit)",
        auto=False,
        requires_confirmation=True,
        action=(
            "Confirm SolidWorks is running (restart if needed); the server will reattach. "
            "After reattach, explicitly call open_document or new_part/new_assembly — "
            "documents are not auto-reopened. For prior writes, re-read model/document "
            "state before retrying; do not assume success or blindly retry mutating calls."
        ),
    ),
    # --- Document ---
    "NO_ACTIVE_DOCUMENT": _def("No active document"),
    "WRONG_DOCUMENT": _def(
        "Active document does not match expect_title/expect_path",
        auto=True,
        action=(
            "Call list_open_documents or get_active_document; activate the intended "
            "document or correct expect_title/expect_path, then retry."
        ),
    ),
    "OPEN_FAILED": _def("Failed to open document"),
    "SAVE_FAILED": _def("Save or Save As failed"),
    "UNSUPPORTED_DOC_TYPE": _def("Unsupported document type"),
    # --- Sketch ---
    "SKETCH_NOT_FOUND": _def("Sketch not found"),
    "NO_ACTIVE_SKETCH": _def(
        "No sketch is open",
        auto=True,
        action=(
            "Call start_sketch(plane=...) (or edit_sketch with an existing sketch name) "
            "before sketch entity tools, then retry."
        ),
    ),
    "SKETCH_OP_FAILED": _def("Sketch operation failed"),
    "SKETCH_PROFILE_CONFLICT": _def(
        "Closed sketch profiles overlap or share edges (rect/circle)",
        auto=False,
        action=(
            "Split conflicting contours into separate sketches/features; "
            "inspect error.context.conflicts for entity kinds and coordinates."
        ),
    ),
    # --- Feature ---
    "FEATURE_NOT_FOUND": _def("Feature not found"),
    "FEATURE_NOT_AVAILABLE": _def(
        "Required SolidWorks feature or add-in is not available",
        auto=False,
        action=(
            "Install/enable the required add-in (e.g. SOLIDWORKS MBD for AP242), "
            "confirm with cadmcp doctor, then retry."
        ),
    ),
    "FEATURE_CREATE_FAILED": _def(
        "Feature creation failed",
        auto=False,
        requires_confirmation=True,
        action=(
            "Inspect with list_features, get_geometry, and/or sketch_status; fix "
            "preconditions (active sketch/profile, solid body, parameters) then retry "
            "once. Do not blindly repeat feature creation after applied/unknown results."
        ),
    ),
    "REBUILD_FAILED": _def("Rebuild failed or features have errors"),
    # --- Selection & references ---
    "SELECT_FAILED": _def("COM selection call failed"),
    "REF_NOT_FOUND": _def("Reference could not be resolved (0 matches)"),
    "REF_AMBIGUOUS": _def(
        "Ambiguous reference (multiple matches)",
        auto=True,
        action=(
            "Call get_entities or get_faces(kind=...)/get_edges to narrow candidates; "
            "retry with current index plus coordinates (or a kind-relative ref)."
        ),
    ),
    "REF_STALE": _def(
        "Persistent reference is stale or invalid",
        auto=True,
        action=(
            "Re-query with get_entities / get_faces / get_edges (or get_component_faces) "
            "and retry using the fresh handle; do not reuse a pre-mutation index alone."
        ),
    ),
    "REF_UNSUPPORTED": _def("Persistent references are not supported by this backend"),
    # --- State ---
    "STATE_VERSION_MISMATCH": _def("State version mismatch (out of order or replay)"),
    "DOCUMENT_CHANGED_EXTERNALLY": _def("Geometry fingerprint mismatch; document changed externally"),
    # --- Units ---
    "UNIT_UNSUPPORTED": _def("Unsupported unit"),
    "UNIT_PARSE_FAILED": _def("Failed to parse number or unit"),
    # --- Safety (path sandbox & HTTP) ---
    "PATH_INVALID": _def(
        "Invalid path shape (colon, reserved name, trailing chars, etc.)",
        auto=True,
        action=(
            "Use a workspace-relative path without drive letters, reserved names, "
            "or illegal characters; then retry."
        ),
    ),
    "PATH_OUTSIDE_SANDBOX": _def(
        "Path outside sandbox",
        auto=True,
        action="Move the path under the workspace root and retry.",
    ),
    "PATH_SYMLINK_DENIED": _def(
        "Path contains symbolic link",
        auto=True,
        action="Replace symlink segments with a real path inside the workspace and retry.",
    ),
    "PATH_EXTENSION_DENIED": _def(
        "Extension not on allowlist",
        auto=True,
        action=(
            "Use an allowed extension for the tool (e.g. .sldprt/.sldasm/.slddrw or "
            "image/export allowlist) and retry."
        ),
    ),
    "PATH_OVERWRITE_DENIED": _def(
        "Refused to overwrite existing file",
        auto=True,
        action="Choose a new filename, or pass overwrite=true explicitly, then retry.",
    ),
    "PATH_NOT_FOUND": _def(
        "File not found",
        auto=True,
        action=(
            "Verify spelling and directory listing; save_document first if the file "
            "must exist, then retry."
        ),
    ),
    "UNAUTHENTICATED": _def("Missing or invalid token"),
    "INSECURE_BIND_REJECTED": _def("Insecure bind refused at startup"),
    # --- Spec layer ---
    "SPEC_VALIDATION_FAILED": _def("Spec structure validation failed"),
    "SPEC_UNSUPPORTED_TYPE": _def("Unsupported spec type"),
    # --- Batch ---
    "BATCH_PARTIAL_FAILURE": _def("Batch failed mid-run (some steps already executed)"),
    "BATCH_LIMIT_EXCEEDED": _def(
        "Batch refused or stopped: step count or duration limit exceeded"
    ),
    # --- Toolbox visibility ---
    "TOOLSET_CLOSED": _def("Tool's toolset is not open (call open_toolbox first)"),
    # --- Model verification (verify_model check codes; also usable via fail) ---
    "VERIFY_EMPTY_BODY": _def("Model has no solid geometry (empty body)"),
    "VERIFY_INVALID_BODY": _def("Model has invalid or corrupted solid geometry"),
    "VERIFY_FEATURE_ERROR": _def("Feature tree has failed or errored features"),
    "VERIFY_MASS_OUT_OF_RANGE": _def("Mass or volume outside verify_model thresholds"),
    "VERIFY_BBOX_OUT_OF_RANGE": _def("Bounding-box size outside verify_model thresholds"),
    "VERIFY_HOLE_POSITION": _def("Cylindrical hole axis outside thresholds.holes tolerance"),
    "VERIFY_INTERFERENCE": _def("Assembly has interfering component pairs"),
    "VERIFY_MATE_ERROR": _def("Assembly mate has a non-zero SolidWorks error status"),
    "VERIFY_DRAWING_INCOMPLETE": _def("Drawing missing views, annotations, or BOM"),
    # --- Transactions (F4) ---
    "NO_ACTIVE_TRANSACTION": _def("No active transaction for the given tx_id"),
    "ROLLBACK_UNSAFE": _def("Rollback refused: unsafe preconditions (model unchanged)"),
    "ROLLBACK_FAILED": _def("Rollback execution failed (partial compensation possible)"),
    "TX_UNSUPPORTED_STEP": _def("Transaction step has no compensator (warned; compensate may refuse)"),
}


def catalog_message(code: str) -> str:
    """Default catalog description for a registered code."""
    return CATALOG[code].message


def catalog_remediation(code: str) -> ErrorDef | None:
    """Return ErrorDef for a registered code, else None."""
    return CATALOG.get(code)


_ERRORS_HELP_PREAMBLE = """# Result and error envelope

Every tool answers one JSON envelope; a domain error is a normal result carrying
`isError=true` and `ok=false` (not a protocol failure).

- `ok=true` -> `result` holds the payload; the envelope may also carry `delta`,
  `rebuild`, `state_version`, `warnings`.
- `ok=false` -> `error = {code, message, hint, side_effect, context}`:
  - `message` explains why; `hint` is the next action, written to be actionable
    (it often names the exact tool or argument to change) - follow it.
  - `side_effect`: `none` = nothing happened, safe to retry as-is;
    `applied` = the change happened but a complete result was not read back - do NOT
    retry blindly, re-read state (`get_geometry` / `list_features`) first.
  - `context` = machine-readable detail (nearest distance, candidate indexes, ...).

Frequent codes: `INVALID_ARGUMENT` (fix the argument per hint), `NO_ACTIVE_DOCUMENT`
(call `new_part` or `open_document` first), `NO_ACTIVE_SKETCH`, `EXECUTOR_BUSY`
(one operation runs at a time; wait briefly, then retry), `REF_NOT_FOUND` /
`REF_AMBIGUOUS` (refresh handles via `get_entities`), `PATH_OUTSIDE_SANDBOX` /
`PATH_OVERWRITE_DENIED` (workspace sandbox: file paths stay inside the workspace,
overwrite only with explicit `overwrite=true`).

## Tool timeouts (`EXEC_TIMEOUT`)

Default tiers: `fast` 10s / `normal` 60s / `slow` 300s (per-tool `timeout_class`).
Optional env `CADMCP_TOOL_TIMEOUTS` is a JSON object that overrides named tools at
executor start, e.g. `{"list_components": 60}`. Values must be in `[1, 300]` seconds;
invalid JSON/entries are ignored with a warning. When unset, behavior matches the
tiers above. Prefer `list_components_lite` for large assemblies before raising timeouts.
`verify_model(partial_on_timeout=true, max_retries=0..2)` may continue after a group
`COM_CALL_FAILED`/`EXEC_TIMEOUT`; **`partial=true` is not verified**. See help
`verify_model` / `limits`. See also help topic `limits`.

## Remediation catalog (F3)

Stable per-code repair metadata from the server catalog. Prefer the runtime
`hint` on a specific failure when present; use this table when planning recovery.

Columns: `auto` = safe for the agent to attempt without asking the user;
`requires_confirmation` = ask the user before acting; `action` = executable next step.
Codes with an empty action are registered but not in the first remediation batch.
"""


def render_errors_help() -> str:
    """Markdown body for cadmcp://help/errors and help(topic='errors') (same source)."""
    lines = [_ERRORS_HELP_PREAMBLE.rstrip(), "", "| code | auto | requires_confirmation | action |", "|---|---|---|---|"]
    for code in sorted(CATALOG):
        entry = CATALOG[code]
        action = entry.action.replace("|", "\\|").replace("\n", " ") if entry.action else "—"
        lines.append(
            f"| `{code}` | {str(entry.auto).lower()} | {str(entry.requires_confirmation).lower()} | {action} |"
        )
    return "\n".join(lines) + "\n"


class ErrorInfo(BaseModel):
    """Error payload (in OpResult.error, serialized to MCP clients)."""

    model_config = ConfigDict(extra="forbid")

    # code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    code: str = Field(pattern=_CODE_RE.pattern)
    message: str = Field(min_length=1)  # why
    hint: str = Field(min_length=1)  # concrete next step (required)
    side_effect: SideEffect
    context: dict[str, Any] = {}

    @classmethod
    def from_error(cls, err: CadMcpError) -> ErrorInfo:
        return cls(
            code=err.code,
            message=err.message,
            hint=err.hint,
            side_effect=err.side_effect,
            context=dict(err.context),
        )


class CadMcpError(Exception):
    """Single exception type for the project; code must be registered in CATALOG."""

    def __init__(
        self,
        code: str,
        message: str,
        hint: str,
        *,
        side_effect: SideEffect = SideEffect.NONE,
        context: dict[str, Any] | None = None,
    ) -> None:
        if code not in CATALOG:
            raise ValueError(f"Unknown error code {code!r}: register it in errors.CATALOG first")
        if not message or not hint:
            raise ValueError(
                f"{code}: message and hint must not be empty (errors must include a next-step hint)"
            )
        self.code = code
        self.message = message
        self.hint = hint
        self.side_effect = side_effect
        self.context = dict(context or {})
        super().__init__(f"{code}: {message}")

    def to_info(self) -> ErrorInfo:
        return ErrorInfo.from_error(self)


def fail(
    code: str,
    message: str,
    hint: str,
    *,
    side_effect: SideEffect = SideEffect.NONE,
    **context: Any,
) -> CadMcpError:
    """Unified constructor: `raise fail(...)`; extra keywords go into context."""
    return CadMcpError(code, message, hint, side_effect=side_effect, context=context)


def is_valid_code(code: str) -> bool:
    return bool(_CODE_RE.match(code))
