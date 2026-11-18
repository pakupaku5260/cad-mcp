"""Reference-plane sketch sequences + F1.4 persist-ref selection."""
from __future__ import annotations

from cadmcp.consistency._types import SequenceStep

# Stable fake: signatures for 40×40×20 mm box (same geometry as selector_refs).
_FACE0_REF = "fake:20376d0d7a4c3f79949e87f01a8a5908"
_STALE_REF = "fake:deadbeefdeadbeefdeadbeefdeadbeef"

SEQUENCES: dict[str, list[SequenceStep]] = {
    # F1.4: persist ref_id exact hit (normal path).
    "persist_ref_normal": [
        ("new_part", {}),
        ("start_sketch", {"plane": "Front Plane"}),
        ("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 40, "y2": 40}),
        ("end_sketch", {}),
        ("extrude", {"depth": 20}),
        ("get_entities", {}),
        ("select_face", {"index": 0, "ref_id": _FACE0_REF}),
        ("close_document", {"discard": True}),
    ],

    # F1.4: persist ref_id miss → REF_STALE (side_effect=none) with candidates.
    "persist_ref_stale": [
        ("new_part", {}),
        ("start_sketch", {"plane": "Front Plane"}),
        ("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 40, "y2": 40}),
        ("end_sketch", {}),
        ("extrude", {"depth": 20}),
        ("get_entities", {}),
        ("select_face", {"index": 0, "ref_id": _STALE_REF}),
        ("close_document", {"discard": True}),
    ],

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
