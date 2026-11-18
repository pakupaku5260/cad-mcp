"""Diagnostics toolset (F20): interpret cadmcp doctor JSON via check_doctor_matrix."""
from __future__ import annotations

from typing import Any

from cadmcp.doctor_matrix import assess as assess_doctor_matrix
from cadmcp.errors import fail
from cadmcp.kernel import OpContext
from cadmcp.registry import ToolSpec, make_schema

_CHECK_DESCRIPTION = (
    "Interpret an existing cadmcp doctor JSON report as a structured check matrix. "
    "Does not run doctor, Executor, or backend; missing fields are skipped. "
    "Not a live /health or status check. Returns verification + matrix rows; "
    "risk=unverified. Read cadmcp://help/doctor_matrix before interpreting."
)


def check_doctor_matrix(ctx: OpContext, report: dict[str, Any]) -> dict:
    """Readonly matrix over a caller-supplied doctor report dict."""
    if not isinstance(report, dict):
        raise fail(
            "INVALID_ARGUMENT",
            "report must be an object",
            "Pass the JSON object printed by `cadmcp doctor`",
        )
    return assess_doctor_matrix(report)


DIAGNOSTICS_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="check_doctor_matrix",
        toolset="diagnostics",
        description=_CHECK_DESCRIPTION,
        input_schema=make_schema(
            {
                "report": {
                    "type": "object",
                    "additionalProperties": False,
                    "description": "Existing cadmcp doctor JSON object (not a file path).",
                    "properties": {
                        "ok": {"type": "boolean"},
                        "cadmcp_version": {"type": "string"},
                        "python": {"type": "string"},
                        "platform": {"type": "string"},
                        "workspace": {"type": "string"},
                        "backend": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "kind": {"type": "string"},
                                "available": {"type": "boolean"},
                                "revision": {"type": ["string", "null"]},
                                "error": {"type": ["string", "null"]},
                                "mbd_step242": {"type": "boolean"},
                            },
                        },
                        # Free-form HealthReport dump (empty schema = any); not walked as typed object.
                        "executor": {},
                        "registry": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "tools": {"type": "integer"},
                                # Dynamic toolset→count map.
                                "toolsets": {},
                            },
                        },
                        "notes": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            ["report"],
        ),
        handler=check_doctor_matrix,
        mutating=False,
        bypass_queue=True,
        timeout_class="fast",
        layer="domain",
    ),
]

__all__ = ["DIAGNOSTICS_SPECS", "check_doctor_matrix"]
