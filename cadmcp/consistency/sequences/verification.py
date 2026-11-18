"""F2 verify_model consistency sequences (counterexamples + healthy path)."""
from __future__ import annotations

from cadmcp.consistency._types import SequenceStep

SEQUENCES: dict[str, list[SequenceStep]] = {
    # Empty part → geometry group fails with VERIFY_EMPTY_BODY
    "verify_empty_body": [
        ("new_part", {}),
        ("verify_model", {"groups": ["geometry"]}),
        ("close_document", {"discard": True}),
    ],

    # Cylinder boss + far hole threshold → VERIFY_HOLE_POSITION
    "verify_hole_position": [
        ("new_part", {}),
        ("start_sketch", {"plane": "Front Plane"}),
        ("sketch_circle", {"cx": 0, "cy": 0, "r": 5}),
        ("end_sketch", {}),
        ("extrude", {"depth": 10}),
        (
            "verify_model",
            {
                "groups": ["mass_bbox"],
                "thresholds": {"holes": [{"x": 200, "y": 200, "z": 200, "tol_mm": 0.1}]},
            },
        ),
        ("close_document", {"discard": True}),
    ],

    # Healthy box: applicable groups pass; assembly/drawing skipped
    "verify_healthy_part": [
        ("new_part", {}),
        ("start_sketch", {"plane": "Front Plane"}),
        ("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 40, "y2": 40}),
        ("end_sketch", {}),
        ("extrude", {"depth": 20}),
        ("verify_model", {}),
        ("close_document", {"discard": True}),
    ],
}
