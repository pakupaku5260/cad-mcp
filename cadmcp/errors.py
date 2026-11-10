"""Error system: SCREAMING_SNAKE catalog, unified constructor, side-effect levels (v4 §10, §17 W1-1).

Conventions:
- Each error = code (stable, machine-readable) + message (why) + hint (concrete next step).
  Hints are written for the model as "errors as instructions" and are required — error
  quality caps how well the model can self-correct.
- side_effect separates "operation did not occur (safe to retry)" from "operation occurred (do not blindly retry)".
- New codes must be registered in CATALOG first (validated at construction); the catalog is the doc;
  contract tests enforce catalog rules.
"""
from __future__ import annotations

import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class SideEffect(StrEnum):
    """Side-effect level: required on error responses (v4 §10)."""

    NONE = "none"  # Operation did not occur — safe to retry
    APPLIED = "applied"  # Operation occurred — do not blindly retry; known state is in context


CATALOG: dict[str, str] = {
    # --- General ---
    "INTERNAL_ERROR": "Unexpected server error",
    "INVALID_ARGUMENT": "Invalid argument",
    "NOT_IMPLEMENTED": "Feature not yet implemented",
    # --- Executor ---
    "EXECUTOR_BUSY": "Executor busy; new task rejected (no queueing)",
    "QUEUE_FULL": "Task queue is full",
    "EXEC_TIMEOUT": "Single task exceeded tiered timeout",
    "EXEC_STUCK": "Executor stuck (STUCK); manual intervention required",
    "EXEC_BLOCKED": "Executor blocked by modal dialog; COM call cannot return",
    # --- Connection ---
    "SW_NOT_RUNNING": "SolidWorks is not running or cannot be attached",
    "COM_ATTACH_FAILED": "COM attach failed",
    "COM_CALL_FAILED": "COM call raised an exception",
    # --- Document ---
    "NO_ACTIVE_DOCUMENT": "No active document",
    "OPEN_FAILED": "Failed to open document",
    "SAVE_FAILED": "Save or Save As failed",
    "UNSUPPORTED_DOC_TYPE": "Unsupported document type",
    # --- Sketch ---
    "SKETCH_NOT_FOUND": "Sketch not found",
    "NO_ACTIVE_SKETCH": "No sketch is open",
    "SKETCH_OP_FAILED": "Sketch operation failed",
    # --- Feature ---
    "FEATURE_NOT_FOUND": "Feature not found",
    "FEATURE_CREATE_FAILED": "Feature creation failed",
    "REBUILD_FAILED": "Rebuild failed or features have errors",
    # --- Selection & references ---
    "SELECT_FAILED": "COM selection call failed",
    "REF_NOT_FOUND": "Reference could not be resolved (0 matches)",
    "REF_AMBIGUOUS": "Ambiguous reference (multiple matches)",
    "REF_UNSUPPORTED": "Reference type not supported yet",
    # --- State ---
    "STATE_VERSION_MISMATCH": "State version mismatch (out of order or replay)",
    "DOCUMENT_CHANGED_EXTERNALLY": "Geometry fingerprint mismatch; document changed externally",
    # --- Units ---
    "UNIT_UNSUPPORTED": "Unsupported unit",
    "UNIT_PARSE_FAILED": "Failed to parse number or unit",
    # --- Safety (path sandbox & HTTP) ---
    "PATH_INVALID": "Invalid path shape (colon, reserved name, trailing chars, etc.)",
    "PATH_OUTSIDE_SANDBOX": "Path outside sandbox",
    "PATH_SYMLINK_DENIED": "Path contains symbolic link",
    "PATH_EXTENSION_DENIED": "Extension not on allowlist",
    "PATH_OVERWRITE_DENIED": "Refused to overwrite existing file",
    "PATH_NOT_FOUND": "File not found",
    "UNAUTHENTICATED": "Missing or invalid token",
    "INSECURE_BIND_REJECTED": "Insecure bind refused at startup",
    # --- Spec layer ---
    "SPEC_VALIDATION_FAILED": "Spec structure validation failed",
    "SPEC_UNSUPPORTED_TYPE": "Unsupported spec type",
    # --- Batch ---
    "BATCH_PARTIAL_FAILURE": "Batch failed mid-run (some steps already executed)",
    # --- Toolbox visibility ---
    "TOOLSET_CLOSED": "Tool's toolset is not open (call open_toolbox first)",
}


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
