"""F13/F14 task/batch consistency sequences."""
from __future__ import annotations

from pathlib import Path

from cadmcp.consistency._types import SequenceStep
from cadmcp.task_ledger import reset_for_tests

_BATCH_THREE = {
    "steps": [
        {"tool": "new_part", "args": {}},
        {"tool": "start_sketch", "args": {"plane": "Front Plane"}},
        {
            "tool": "sketch_rectangle",
            "args": {"x1": 0, "y1": 0, "x2": 20, "y2": 10},
        },
    ],
    "stop_on_error": True,
}


def seed_task_layer(_workspace: Path) -> None:
    """Reset in-process ledger so job_id=1 is deterministic for this sequence."""
    reset_for_tests()


SEQUENCES: dict[str, list[SequenceStep]] = {
    "batch": [
        ("batch", _BATCH_THREE),
    ],
    "task_layer": [
        ("batch", _BATCH_THREE),
        ("task_status", {"job_id": 1}),
        ("task_list", {"limit": 10, "offset": 0}),
    ],
}

SEEDS: dict = {
    "task_layer": seed_task_layer,
}

__all__ = ["SEEDS", "SEQUENCES", "seed_task_layer"]
