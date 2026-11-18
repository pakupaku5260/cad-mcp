"""Diagnostics consistency sequences (F20)."""
from __future__ import annotations

from cadmcp.consistency._types import SequenceStep

# Fixed healthy doctor-shaped report (no live probe). All 14 matrix rows pass.
_HEALTHY_DOCTOR_REPORT = {
    "ok": True,
    "cadmcp_version": "0.3.0",
    "python": "3.12.0",
    "platform": "Windows-AMD64",
    "workspace": "C:/workspace",
    "backend": {
        "kind": "fake",
        "available": True,
        "revision": "33.0",
        "error": None,
        "mbd_step242": True,
    },
    "executor": {
        "state": "IDLE",
        "tool": None,
        "elapsed_s": None,
        "queue_depth": 0,
        "pending_mutating": 0,
        "thread_alive": True,
        "backend_ready": True,
        "stuck_reason": None,
        "late_results": 0,
        "jobs_total": 0,
        "windows": None,
        "detector_error": None,
        "blocker": None,
    },
    "registry": {
        "tools": 158,
        "toolsets": {"core": 48, "diagnostics": 1},
    },
    "notes": [
        "fixture report for doctor_matrix_check",
    ],
}

SEQUENCES: dict[str, list[SequenceStep]] = {
    "doctor_matrix_check": [
        ("check_doctor_matrix", {"report": _HEALTHY_DOCTOR_REPORT}),
    ],
}

__all__ = ["SEQUENCES"]
