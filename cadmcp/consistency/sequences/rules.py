"""Consistency sequence for check_rules (F16). Fake-only structural lock."""
from __future__ import annotations

from cadmcp.consistency._types import SequenceStep

SEQUENCES: dict[str, list[SequenceStep]] = {
    # new_part → model a plate → check_rules (locks payload shape, not pass/fail)
    "rules_check": [
        ("new_part", {}),
        ("start_sketch", {"plane": "Front Plane"}),
        ("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 40, "y2": 20}),
        ("end_sketch", {}),
        ("extrude", {"depth": 10}),
        ("check_rules", {}),
    ],
}

__all__ = ["SEQUENCES"]
