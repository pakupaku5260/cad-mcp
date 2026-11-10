"""Sequence of error paths across the backend."""
from __future__ import annotations

from cadmcp.consistency._types import SequenceStep

SEQUENCES: dict[str, list[SequenceStep]] = {
    # Error side: overlay tool layer and back-end layer two types of error sources (error code semantics is the protocol anchor)
    "error_paths": [
        ("extrude", {"depth": 10}),  # no document → tool layer NO_ACTIVE_DOCUMENT
        ("new_part", {}),
        ("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 10, "y2": 10}),  # no open sketch → backend NO_ACTIVE_SKETCH
        ("end_sketch", {}),  # same as above
        ("start_sketch", {"plane": "Front Plane"}),
        ("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 10, "y2": 10}),
        ("end_sketch", {}),
        ("extrude", {"depth": 10, "sketch": "NoSuchSketch"}),  # backend SKETCH_NOT_FOUND
        ("close_document", {"discard": False}),  # unsaved changes → INVALID_ARGUMENT
    ],
}
