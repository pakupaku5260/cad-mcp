"""Reference-plane sketch sequences."""
from __future__ import annotations

from cadmcp.consistency._types import SequenceStep

SEQUENCES: dict[str, list[SequenceStep]] = {
    # Stage W: offset front plane 20 mm, circle extrude; missing plane / unknown sketch plane / missing axis params fail.
    "ref_plane_sketch": [
        ("new_part", {}),
        ("create_plane", {"reference": "Front Plane", "offset": 20}),
        ("list_planes", {}),
        ("start_sketch", {"plane": "Plane1"}),
        ("sketch_circle", {"cx": 0, "cy": 0, "r": 10}),
        ("end_sketch", {}),
        ("extrude", {"depth": 10}),
        ("get_geometry", {}),
        ("create_axis", {"planes": ["Front Plane", "Right Plane"]}),
        ("create_plane", {"reference": "NoSuch", "offset": 10}),
        ("start_sketch", {"plane": "Ghost"}),
        ("create_axis", {}),
        ("create_axis", {"planes": ["Front Plane", "NoSuch"]}),
        ("close_document", {"discard": True}),
    ],

    # Stage W2: angled plane from front about intersection axis, extrude; three-point plane; missing axis / colinear fail.
    "ref_plane_angle": [
        ("new_part", {}),
        ("create_axis", {"planes": ["Front Plane", "Right Plane"]}),
        ("create_plane", {"mode": "angle", "reference": "Front Plane", "axis": "Axis1", "angle_deg": 30}),
        ("list_planes", {}),
        ("start_sketch", {"plane": "Plane1"}),
        ("sketch_circle", {"cx": 0, "cy": 0, "r": 10}),
        ("end_sketch", {}),
        ("extrude", {"depth": 10}),
        ("get_geometry", {}),
        ("create_plane", {"mode": "points", "points": [[0, 0, 0], [20, 0, 0], [0, 30, 10]]}),
        ("create_plane", {"mode": "angle", "reference": "NoSuch", "axis": "Axis1", "angle_deg": 30}),
        ("create_plane", {"mode": "angle", "reference": "Front Plane", "angle_deg": 30}),
        ("create_plane", {"mode": "points", "points": [[0, 0, 0], [10, 0, 0], [20, 0, 0]]}),
        ("close_document", {"discard": True}),
    ],
}
