"""F4 transaction consistency sequences (§4.5 + extras)."""
from __future__ import annotations

from cadmcp.consistency._types import SequenceStep

SEQUENCES: dict[str, list[SequenceStep]] = {
    # §4.5: extrude → fillet → bad param → rollback(compensate)
    "tx_compensate_fingerprint_restore": [
        ("new_part", {}),
        ("start_sketch", {"plane": "Front Plane"}),
        ("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 40, "y2": 40}),
        ("end_sketch", {}),
        ("extrude", {"depth": 20}),
        ("tx_begin", {"name": "compensate_restore", "mode": "journal-only"}),
        ("fillet", {"radius": 2}),
        ("fillet", {"radius": -1}),  # INVALID_ARGUMENT; no mutation
        ("tx_rollback", {"mode": "compensate"}),
        ("close_document", {"discard": True}),
    ],
    # §4.5: repeat rollback → NO_ACTIVE_TRANSACTION
    "tx_rollback_twice_no_active": [
        ("new_part", {}),
        ("start_sketch", {"plane": "Front Plane"}),
        ("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 20, "y2": 20}),
        ("end_sketch", {}),
        ("extrude", {"depth": 10}),
        ("tx_begin", {"name": "twice", "mode": "journal-only"}),
        ("tx_rollback", {"mode": "compensate"}),
        ("tx_rollback", {"mode": "compensate"}),
        ("close_document", {"discard": True}),
    ],
    # §4.5: save during tx → ROLLBACK_UNSAFE
    "tx_save_then_rollback_unsafe": [
        ("new_part", {}),
        ("start_sketch", {"plane": "Front Plane"}),
        ("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 30, "y2": 30}),
        ("end_sketch", {}),
        ("extrude", {"depth": 15}),
        ("tx_begin", {"name": "save_block", "mode": "journal-only"}),
        ("save_document", {"path": "tx_saved.sldprt", "overwrite": True}),
        ("tx_rollback", {"mode": "compensate"}),
        ("close_document", {"discard": True}),
    ],
}
