"""Sketch geometry, relations, offset/trim/spline, and 3D sketch sequences."""
from __future__ import annotations

from cadmcp.consistency._types import SequenceStep

SEQUENCES: dict[str, list[SequenceStep]] = {
    # Stage SK4: colinear / fixed / midpoint; symmetric without axis still fails.
    "sketch_relations_ext": [
        ("new_part", {}),
        ("start_sketch", {"plane": "Front Plane"}),
        ("sketch_line", {"x1": 0, "y1": 0, "x2": 40, "y2": 2}),
        ("sketch_line", {"x1": 45, "y1": 0, "x2": 80, "y2": -1}),
        ("add_sketch_relation", {"relation": "colinear", "entity1": 0, "entity2": 1}),
        ("sketch_line", {"x1": 0, "y1": 20, "x2": 20, "y2": 25}),
        ("add_sketch_relation", {"relation": "fixed", "entity1": 2}),
        ("sketch_line", {"x1": 0, "y1": 40, "x2": 40, "y2": 40}),
        ("sketch_line", {"x1": 18, "y1": 50, "x2": 22, "y2": 55}),
        ("add_sketch_relation", {"relation": "midpoint", "entity1": 4, "entity2": 3}),
        ("list_sketch_entities", {}),
        ("add_sketch_relation", {"relation": "symmetric", "entity1": 0, "entity2": 1}),
        ("close_document", {"discard": True}),
    ],

    # Stage SK5: symmetric constraint (two lines + axis); missing entity3 fails.
    "sketch_symmetric": [
        ("new_part", {}),
        ("start_sketch", {"plane": "Front Plane"}),
        ("sketch_line", {"x1": 0, "y1": -30, "x2": 0, "y2": 30}),  # axis
        ("sketch_line", {"x1": -20, "y1": 10, "x2": -10, "y2": 15}),
        ("sketch_line", {"x1": 10, "y1": 12, "x2": 20, "y2": 8}),
        ("add_sketch_relation", {
            "relation": "symmetric", "entity1": 1, "entity2": 2, "entity3": 0,
        }),
        ("list_sketch_entities", {}),
        ("add_sketch_relation", {"relation": "symmetric", "entity1": 1, "entity2": 2}),
        ("close_document", {"discard": True}),
    ],

    # Sketch dimensions and relations (stage E): endpoint-driven dims; relation names via SketchAddConstraints.
    "sketch_dims": [
        ("new_part", {}),
        ("start_sketch", {"plane": "Front Plane"}),
        ("sketch_line", {"x1": 0, "y1": 0, "x2": 10, "y2": 2}),
        ("add_sketch_dimension", {"x1": 0, "y1": 0, "x2": 10, "y2": 2, "value": 20}),
        ("add_sketch_relation", {"relation": "horizontal", "entity1": 0}),
        ("sketch_line", {"x1": 0, "y1": 4, "x2": 10, "y2": 6}),
        ("add_sketch_relation", {"relation": "parallel", "entity1": 0, "entity2": 1}),
        ("add_sketch_dimension", {"x1": 0, "y1": 0, "x2": 10, "y2": 2, "value": 0}),
        ("add_sketch_relation", {"relation": "coincident", "entity1": 0}),
        ("add_sketch_relation", {"relation": "horizontal", "entity1": 9}),
        ("add_sketch_dimension", {"x1": 0, "y1": 0, "x2": 99, "y2": 99, "value": 10}),
        ("sketch_circle", {"cx": 0, "cy": 0, "r": 5}),
        ("add_sketch_dimension", {"x1": 0, "y1": 0, "x2": 5, "y2": 0, "value": 16}),
        ("sketch_line", {"x1": 8, "y1": -2, "x2": 12, "y2": 3}),
        ("add_sketch_relation", {"relation": "tangent", "entity1": 2, "entity2": 3}),
        ("add_sketch_relation", {"relation": "equal", "entity1": 0, "entity2": 1}),
        ("close_document", {"discard": True}),
    ],

    # Stage S: entity list, re-read after constraints, re-edit, solve status.
    "sketch_solve": [
        ("new_part", {}),
        ("start_sketch", {"plane": "Front Plane"}),
        ("sketch_line", {"x1": 0, "y1": 0, "x2": 50, "y2": 10}),
        ("sketch_line", {"x1": 0, "y1": 0, "x2": 10, "y2": 40}),
        ("list_sketch_entities", {}),
        ("sketch_status", {}),
        ("add_sketch_relation", {"relation": "horizontal", "entity1": 0}),
        ("add_sketch_relation", {"relation": "vertical", "entity1": 1}),
        ("list_sketch_entities", {}),
        ("add_sketch_dimension", {"entity1": 0, "value": 80}),
        ("list_sketch_entities", {}),
        ("sketch_status", {}),
        ("end_sketch", {}),
        ("list_sketch_entities", {"sketch": "Sketch1"}),
        ("edit_sketch", {"name": "Sketch1"}),
        ("list_sketch_entities", {}),
        ("end_sketch", {}),
        ("edit_sketch", {"name": "NoSuch"}),
        ("list_sketch_entities", {}),
        ("close_document", {"discard": True}),
    ],

    # Lines and polygon (structure golden; polygon returns sides list — no indexed constraints after to avoid construction-circle edge-count fork on real machine).
    "sketch_basic": [
        ("new_part", {}),
        ("start_sketch", {"plane": "Front Plane"}),
        ("sketch_line", {"x1": 0, "y1": 0, "x2": 10, "y2": 0}),
        ("sketch_polygon", {"sides": 6, "radius": 8}),
        ("sketch_line", {"x1": 0, "y1": 0, "x2": 0, "y2": 0}),
        ("sketch_polygon", {"sides": 2, "radius": 8}),
        ("close_document", {"discard": True}),
    ],

    # Stage K: three-point/center arcs, endpoint coincident, colinear failure
    "sketch_arc": [
        ("new_part", {}),
        ("start_sketch", {"plane": "Front Plane"}),
        ("sketch_arc", {"x1": 0, "y1": 10, "x2": 10, "y2": 0, "x3": 0, "y3": -10}),
        ("sketch_arc", {"cx": 30, "cy": 0, "x1": 40, "y1": 0, "x2": 30, "y2": 10}),
        ("sketch_arc", {"x1": 0, "y1": 0, "x2": 10, "y2": 0}),
        ("sketch_line", {"x1": 0, "y1": 10, "x2": 40, "y2": 10}),
        ("add_sketch_relation", {"relation": "coincident", "entity1": 0, "entity2": 2}),
        ("close_document", {"discard": True}),
    ],

    # Stage K acceptance: slot-profile extrude
    "sketch_slot": [
        ("new_part", {}),
        ("start_sketch", {"plane": "Front Plane"}),
        ("sketch_line", {"x1": 0, "y1": 10, "x2": 40, "y2": 10}),
        ("sketch_arc", {"x1": 40, "y1": 10, "x2": 50, "y2": 0, "x3": 40, "y3": -10}),
        ("sketch_line", {"x1": 40, "y1": -10, "x2": 0, "y2": -10}),
        ("sketch_arc", {"x1": 0, "y1": -10, "x2": -10, "y2": 0, "x3": 0, "y3": 10}),
        ("end_sketch", {}),
        ("extrude", {"depth": 10}),
        ("get_mass_properties", {}),
        ("close_document", {"discard": True}),
    ],

    # Stage SK2: inset offset rectangle extrude; fillet two lines; mirror construction line; invalid distance/index fail.
    "sketch_offset_trim": [
        ("new_part", {}),
        ("start_sketch", {"plane": "Front Plane"}),
        ("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 40, "y2": 20}),
        ("sketch_offset", {"distance": 5, "inward": True}),
        ("list_sketch_entities", {}),
        ("end_sketch", {}),
        ("extrude", {"depth": 10}),
        ("get_geometry", {}),
        ("close_document", {"discard": True}),
        ("new_part", {}),
        ("start_sketch", {"plane": "Front Plane"}),
        ("sketch_line", {"x1": 0, "y1": 0, "x2": 20, "y2": 0}),
        ("sketch_line", {"x1": 20, "y1": 0, "x2": 20, "y2": 20}),
        ("sketch_trim", {"entity1": 0, "entity2": 1, "radius": 4}),
        ("list_sketch_entities", {}),
        ("end_sketch", {}),
        ("close_document", {"discard": True}),
        ("new_part", {}),
        ("start_sketch", {"plane": "Front Plane"}),
        ("sketch_line", {"x1": 0, "y1": 0, "x2": 0, "y2": 20}),
        ("sketch_rectangle", {"x1": 5, "y1": 0, "x2": 25, "y2": 10}),
        ("sketch_mirror", {"axis": 0}),
        ("list_sketch_entities", {}),
        ("end_sketch", {}),
        ("close_document", {"discard": True}),
        ("new_part", {}),
        ("sketch_offset", {"distance": 5}),
        ("start_sketch", {"plane": "Front Plane"}),
        ("sketch_offset", {"distance": 0}),
        ("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 10, "y2": 10}),
        ("sketch_trim", {"entity1": 0, "entity2": 99, "radius": 1}),
        ("sketch_mirror", {"axis": 99}),
        ("close_document", {"discard": True}),
    ],

    # Stage SK3: open spline lists but cannot solidify; closed spline extrude; too few points / no sketch fail.
    "sketch_spline": [
        ("new_part", {}),
        ("start_sketch", {"plane": "Front Plane"}),
        ("sketch_spline", {"points": [[0, 0]]}),
        ("sketch_spline", {"points": [[0, 0], [20, 5]]}),
        ("list_sketch_entities", {}),
        ("end_sketch", {}),
        ("extrude", {"depth": 10}),
        ("close_document", {"discard": True}),
        ("new_part", {}),
        ("start_sketch", {"plane": "Front Plane"}),
        ("sketch_spline", {
            "points": [[0, 0], [40, 5], [35, 25], [5, 20]],
            "closed": True,
        }),
        ("list_sketch_entities", {}),
        ("end_sketch", {}),
        ("extrude", {"depth": 10}),
        ("get_mass_properties", {}),
        ("sketch_spline", {"points": [[0, 0], [10, 0]]}),
        ("close_document", {"discard": True}),
    ],

    # Stage SK3D: 3D sketch line as sweep path; plane z fails.
    "sketch_3d": [
        ("new_part", {}),
        ("start_sketch", {"plane": "3D"}),
        ("sketch_line", {"x1": 0, "y1": 0, "z1": 0, "x2": 40, "y2": 0, "z2": 10}),
        ("end_sketch", {}),
        ("start_sketch", {"plane": "Right Plane"}),
        ("sketch_circle", {"cx": 0, "cy": 0, "r": 5}),
        ("end_sketch", {}),
        ("sweep", {}),
        ("get_geometry", {}),
        ("list_features", {}),
        ("close_document", {"discard": True}),
        ("new_part", {}),
        ("start_sketch", {"plane": "Front Plane"}),
        ("sketch_line", {"x1": 0, "y1": 0, "z1": 5, "x2": 10, "y2": 0, "z2": 0}),
        ("close_document", {"discard": True}),
    ],

    # Stage SK3D2: 3D sketch arc (sketch_arc z extension); plane z fails.
    "sketch_arc_3d": [
        ("new_part", {}),
        ("start_sketch", {"plane": "3D"}),
        ("sketch_arc", {
            "x1": 0, "y1": 0, "z1": 0,
            "x2": 20, "y2": 10, "z2": 5,
            "x3": 40, "y3": 0, "z3": 0,
        }),
        ("end_sketch", {}),
        ("close_document", {"discard": True}),
        ("new_part", {}),
        ("start_sketch", {"plane": "3D"}),
        ("sketch_arc", {
            "cx": 0, "cy": 0, "cz": 0,
            "x1": 10, "y1": 0, "z1": 0,
            "x2": 0, "y2": 10, "z2": 0,
        }),
        ("end_sketch", {}),
        ("close_document", {"discard": True}),
        ("new_part", {}),
        ("start_sketch", {"plane": "Front Plane"}),
        ("sketch_arc", {
            "x1": 0, "y1": 0, "z1": 5,
            "x2": 10, "y2": 10,
            "x3": 20, "y3": 0,
        }),
        ("close_document", {"discard": True}),
    ],

    # Stage SK3D3: 3D sketch spline (sketch_spline [x,y,z]); plane z fails.
    "sketch_spline_3d": [
        ("new_part", {}),
        ("start_sketch", {"plane": "3D"}),
        ("sketch_spline", {
            "points": [[0, 0, 0], [20, 0, 10], [40, 5, 0]],
        }),
        ("end_sketch", {}),
        ("close_document", {"discard": True}),
        ("new_part", {}),
        ("start_sketch", {"plane": "Front Plane"}),
        ("sketch_spline", {
            "points": [[0, 0, 5], [20, 5, 0], [40, 0, 0]],
        }),
        ("close_document", {"discard": True}),
    ],

    # Stage SK3D4: 3D sketch corner rectangle (sketch_rectangle z); plane z fails.
    "sketch_rect_3d": [
        ("new_part", {}),
        ("start_sketch", {"plane": "3D"}),
        ("sketch_rectangle", {
            "x1": 0, "y1": 0, "z1": 0,
            "x2": 40, "y2": 20, "z2": 10,
        }),
        ("end_sketch", {}),
        ("close_document", {"discard": True}),
        ("new_part", {}),
        ("start_sketch", {"plane": "Front Plane"}),
        ("sketch_rectangle", {
            "x1": 0, "y1": 0, "z1": 5,
            "x2": 20, "y2": 10, "z2": 0,
        }),
        ("close_document", {"discard": True}),
    ],

    # Stage SK3D5: 3D sketch center circle (sketch_circle cz); plane cz fails.
    "sketch_circle_3d": [
        ("new_part", {}),
        ("start_sketch", {"plane": "3D"}),
        ("sketch_circle", {"cx": 0, "cy": 0, "cz": 5, "r": 10}),
        ("end_sketch", {}),
        ("close_document", {"discard": True}),
        ("new_part", {}),
        ("start_sketch", {"plane": "Front Plane"}),
        ("sketch_circle", {"cx": 0, "cy": 0, "cz": 5, "r": 10}),
        ("close_document", {"discard": True}),
    ],

    # Stage SK3D6: 3D sketch regular polygon (sketch_polygon cx/cy/cz); plane cz fails.
    "sketch_polygon_3d": [
        ("new_part", {}),
        ("start_sketch", {"plane": "3D"}),
        ("sketch_polygon", {"sides": 6, "radius": 10, "cx": 0, "cy": 0, "cz": 5}),
        ("end_sketch", {}),
        ("close_document", {"discard": True}),
        ("new_part", {}),
        ("start_sketch", {"plane": "Front Plane"}),
        ("sketch_polygon", {"sides": 6, "radius": 10, "cz": 5}),
        ("close_document", {"discard": True}),
    ],
}
