"""Engineering Drawing View and Partial Detail Sequence."""
from __future__ import annotations

from cadmcp.consistency._types import SequenceStep

SEQUENCES: dict[str, list[SequenceStep]] = {
    # Stage N2: Engineering Drawing + Standard Model View (BOM in N3)
    "drawing_views": [
        ("new_part", {}),
        ("start_sketch", {"plane": "Front Plane"}),
        ("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 20, "y2": 20}),
        ("end_sketch", {}),
        ("extrude", {"depth": 10}),
        ("save_document", {"path": "cube.sldprt"}),
        ("create_drawing_view", {"path": "cube.sldprt", "view": "front"}),
        ("new_drawing", {}),
        ("create_drawing_view", {"path": "cube.sldprt", "view": "front"}),
        ("create_drawing_view", {"path": "cube.sldprt", "view": "nope"}),
        ("get_material", {}),
        ("close_document", {"discard": True}),
    ],

    # Phase DRW2: section/model size/ball marker/PDF (without insert_bom)
    "drawing_detail": [
        ("new_part", {}),
        ("start_sketch", {"plane": "Front Plane"}),
        ("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 50, "y2": 50}),
        ("end_sketch", {}),
        ("extrude", {"depth": 20}),
        ("save_document", {"path": "cube.sldprt"}),
        ("new_drawing", {}),
        ("create_section_view", {}),
        ("insert_model_items", {}),
        ("insert_balloons", {}),
        ("export", {"path": "sheet.pdf"}),
        ("create_drawing_view", {"path": "cube.sldprt", "view": "front"}),
        ("insert_model_items", {}),
        ("create_section_view", {"label": "A"}),
        ("export", {"path": "cube.pdf"}),
        ("new_assembly", {}),
        ("insert_component", {"path": "cube.sldprt"}),
        ("insert_component", {"path": "cube.sldprt", "x": 80}),
        ("save_document", {"path": "asm.sldasm"}),
        ("new_drawing", {}),
        ("create_drawing_view", {"path": "asm.sldasm", "view": "front"}),
        ("insert_balloons", {}),
        ("export", {"path": "asm.pdf"}),
        ("new_part", {}),
        ("create_section_view", {}),
        ("insert_model_items", {}),
        ("insert_balloons", {}),
        ("export", {"path": "part.pdf"}),
        ("close_document", {"discard": True}),
    ],

    # DRW3 L3: multiple pages/title bar/GD&T (native; note pocket back)/PDF; insert_bom See assembly drawing for smoke
    # Do not write Sheet1: The front page of the real machine is often "Drawing 1". Create a view + callout on the homepage, and then add Sheet2.
    "drawing_l3": [
        ("new_part", {}),
        ("start_sketch", {"plane": "Front Plane"}),
        ("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 40, "y2": 30}),
        ("end_sketch", {}),
        ("extrude", {"depth": 10}),
        ("save_document", {"path": "plate.sldprt"}),
        ("new_drawing", {}),
        ("create_drawing_view", {"path": "plate.sldprt", "view": "front"}),
        (
            "set_title_block",
            {
                "entries": [
                    {"key": "PartNo", "value": "P-L3"},
                    {"key": "Description", "value": "plate"},
                ]
            },
        ),
        ("insert_datum", {"label": "A", "x": 50, "y": 40}),
        (
            "insert_gdt",
            {
                "symbol": "position",
                "tolerance": "0.1",
                "datums": ["A"],
                "x": 60,
                "y": 40,
            },
        ),
        # First, export the PDF on the front page with the view; the SaveAs3 PDF real machine on the empty Sheet2 has been saved_failed
        ("export", {"path": "plate_l3.pdf", "overwrite": True}),
        ("add_drawing_sheet", {"name": "Sheet2", "paper": "A4", "scale_num": 1, "scale_den": 2}),
        ("inspect_drawing", {}),
        ("close_document", {"discard": True}),
    ],

    # DXF Layers: Engineering AddLayer/Toggle Current Layer/Export DXF (Force DontShowMap without custom map)
    "dxf_layers": [
        ("new_part", {}),
        ("start_sketch", {"plane": "Front Plane"}),
        ("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 30, "y2": 20}),
        ("end_sketch", {}),
        ("extrude", {"depth": 8}),
        ("save_document", {"path": "dxf_layer_part.sldprt"}),
        ("new_drawing", {}),
        ("create_drawing_view", {"path": "dxf_layer_part.sldprt", "view": "front"}),
        ("add_drawing_layer", {"name": "CADMCP_VIS", "color": 255}),
        ("add_drawing_layer", {"name": "CADMCP_VIS", "color": 255}),
        ("set_drawing_layer", {"name": "NoSuchLayer"}),
        ("set_drawing_layer", {"name": "CADMCP_VIS"}),
        ("list_drawing_layers", {}),
        ("export", {"path": "with_layers.dxf"}),
        ("close_document", {"discard": True}),
    ],
}
