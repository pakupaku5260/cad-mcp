"""Engineering Drawing View and Partial Detail Sequence."""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from cadmcp.consistency._types import SequenceStep

PREFLIGHT_SPEC_FILENAME = "preflight_ok.json"

PREFLIGHT_OK_SPEC: dict = {
    "model": "plate.sldprt",
    "sheets": [
        {
            "name": "Sheet1",
            "paper": "A4",
            "scale": [1, 1],
            "views": [{"orient": "front"}, {"orient": "isometric"}],
        }
    ],
    "title_block": {"PartNo": "P-001", "Description": "preflight"},
    "gdts": [
        {"kind": "datum", "label": "A", "x": 100, "y": 80},
        {
            "kind": "gdt",
            "symbol": "position",
            "tolerance": "0.1",
            "datums": ["A"],
            "x": 120,
            "y": 60,
        },
    ],
    "bom": {"type": "top"},
}


def seed_drawing_spec_preflight(workspace: Path) -> None:
    path = workspace / PREFLIGHT_SPEC_FILENAME
    path.write_text(
        json.dumps(PREFLIGHT_OK_SPEC, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


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

    # Drawing release checklist: inspect gaps + verify_model drawing thresholds (part skips BOM).
    "drawing_release": [
        ("new_part", {}),
        ("start_sketch", {"plane": "Front Plane"}),
        ("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 30, "y2": 20}),
        ("end_sketch", {}),
        ("extrude", {"depth": 8}),
        ("save_document", {"path": "rel_plate.sldprt"}),
        ("new_drawing", {}),
        ("create_drawing_view", {"path": "rel_plate.sldprt", "view": "front"}),
        ("insert_model_items", {}),
        ("inspect_drawing", {}),
        (
            "verify_model",
            {
                "groups": ["drawing"],
                "thresholds": {"required_title_keys": [], "require_bom": False},
            },
        ),
        (
            "set_title_block",
            {
                "entries": [
                    {"key": "PartNo", "value": "REL-1"},
                    {"key": "Description", "value": "plate"},
                    {"key": "DrawnBy", "value": "AI"},
                    {"key": "Date", "value": "2026-11-16"},
                    {"key": "Material", "value": "Al"},
                    {"key": "Revision", "value": "A"},
                    {"key": "Title", "value": "plate"},
                ]
            },
        ),
        ("insert_datum", {"label": "A"}),
        (
            "verify_model",
            {
                "groups": ["drawing"],
                "thresholds": {"min_datums": 1, "require_bom": False},
            },
        ),
        ("close_document", {"discard": True}),
    ],

    # Weld: insert (create) + get_weld_annotations (enum) + inspect_weld_symbol (GetText semantics).
    "drawing_weld": [
        ("new_part", {}),
        ("start_sketch", {"plane": "Front Plane"}),
        ("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 30, "y2": 20}),
        ("end_sketch", {}),
        ("extrude", {"depth": 8}),
        ("save_document", {"path": "weld_plate.sldprt"}),
        ("new_drawing", {}),
        ("create_drawing_view", {"path": "weld_plate.sldprt", "view": "front"}),
        ("insert_weld_symbol", {"symbol": "FILL", "x": 100, "y": 80}),
        ("get_weld_annotations", {}),
        ("inspect_weld_symbol", {"index": 0}),
        ("verify_weld_symbol", {"symbol": "FILL", "index": 0}),
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

    # F18: DrawingSpec text preflight (no COM drawing build)
    "drawing_spec_preflight": [
        ("check_drawing_spec", {"spec_path": PREFLIGHT_SPEC_FILENAME}),
    ],
}

SEEDS: dict[str, Callable[[Path], None]] = {
    "drawing_spec_preflight": seed_drawing_spec_preflight,
}

__all__ = [
    "PREFLIGHT_OK_SPEC",
    "PREFLIGHT_SPEC_FILENAME",
    "SEEDS",
    "SEQUENCES",
    "seed_drawing_spec_preflight",
]
