"""Sheet metal and Hole Wizard sequences."""
from __future__ import annotations

from cadmcp.consistency._types import SequenceStep

# F19: pure BA estimate (mm). thickness=2, radius=10, k=0.5, 90° → SI BA = π/2×0.011 m.
_BEND_ALLOWANCE_ARGS = {
    "thickness": 2.0,
    "k_factor": 0.5,
    "bends": [{"angle_deg": 90.0, "radius": 10.0}],
    "unit": "mm",
}

SEQUENCES: dict[str, list[SequenceStep]] = {
    # F19: explicit-parameter BA; no model / unfold / bend table.
    "bend_allowance_calc": [
        ("calc_bend_allowance", _BEND_ALLOWANCE_ARGS),
    ],

    # Stage SM: closed rectangle base flange, edge flange, unfold; invalid edge / no sheet metal / thickness 0 fail.
    "sheet_metal": [
        ("new_part", {}),
        ("start_sketch", {"plane": "Front Plane"}),
        ("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 80, "y2": 40}),
        ("end_sketch", {}),
        ("base_flange", {"thickness": 1}),
        ("get_geometry", {}),
        ("get_edges", {}),
        ("edge_flange", {"edge": 8, "length": 20}),
        ("get_geometry", {}),
        ("sheet_metal_unfold", {}),
        ("get_geometry", {}),
        ("edge_flange", {"edge": 99, "length": 10}),
        ("base_flange", {"thickness": 1}),
        ("close_document", {"discard": True}),
        ("new_part", {}),
        ("sheet_metal_unfold", {}),
        ("edge_flange", {"edge": 0, "length": 10}),
        ("close_document", {"discard": True}),
        ("new_part", {}),
        ("start_sketch", {"plane": "Front Plane"}),
        ("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 10, "y2": 10}),
        ("end_sketch", {}),
        ("base_flange", {"thickness": 0}),
        ("close_document", {"discard": True}),
    ],

    # Stage HW: ISO Ø6 through hole; invalid face / missing depth / no solid fail.
    "hole_wizard": [
        ("new_part", {}),
        ("start_sketch", {"plane": "Front Plane"}),
        ("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 50, "y2": 50}),
        ("end_sketch", {}),
        ("extrude", {"depth": 20}),
        ("get_faces", {"kind": "plane", "query": "max_z"}),
        ("hole_wizard", {"face": 4, "diameter": 6, "end": "through_all"}),
        ("get_geometry", {}),
        ("hole_wizard", {"face": 99, "diameter": 6, "end": "through_all"}),
        ("hole_wizard", {"face": 4, "diameter": 6, "end": "blind"}),
        ("close_document", {"discard": True}),
        ("new_part", {}),
        ("hole_wizard", {"face": 0, "diameter": 6, "end": "through_all"}),
        ("close_document", {"discard": True}),
    ],
}
