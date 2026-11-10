"""DRW3 L2/L3：create_drawing / inspect_drawing（fake）。"""
from __future__ import annotations

import json
from pathlib import Path

from cadmcp.backend.fake.backend import FakeBackend
from cadmcp.kernel import Kernel
from cadmcp.toolsets.core import core_registry


def _k(tmp_path: Path) -> Kernel:
    return Kernel(core_registry(), FakeBackend(), workspace=tmp_path, verify_mutations=True)


def _make_part(k: Kernel, name: str = "plate.sldprt") -> None:
    assert k.dispatch("new_part").ok
    assert k.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert k.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 30, "y2": 20}).ok
    assert k.dispatch("end_sketch").ok
    assert k.dispatch("extrude", {"depth": 8}).ok
    assert k.dispatch("save_document", {"path": name, "overwrite": True}).ok


def test_create_drawing_and_inspect(tmp_path: Path):
    k = _k(tmp_path)
    _make_part(k)

    spec = {
        "model": "plate.sldprt",
        "paper": "A4",
        "scale": [1, 2],
        "views": [{"orient": "front"}, {"orient": "isometric"}],
        "section": {"label": "A", "x": 0.22, "y": 0.15},
        "detail": {"label": "B", "x": 0, "y": 0, "radius": 5},
        "tolerances": [{"dimension": "D1@Sketch1", "type": 1, "values": [0.1, 0.05]}],
        "output_pdf": "plate.pdf",
        "import_dimensions": True,
    }
    (tmp_path / "plate_drawing.json").write_text(json.dumps(spec), encoding="utf-8")
    r = k.dispatch("create_drawing", {"spec_path": "plate_drawing.json", "overwrite": True})
    assert r.ok, r.error
    assert r.result["pdf"]
    assert Path(r.result["pdf"]).is_file()
    assert len(r.result["views"]) >= 2
    insp = k.dispatch("inspect_drawing")
    assert insp.ok
    assert insp.result["view_count"] >= 2
    assert insp.result["paper"] == "A4"
    assert insp.result["sheet_count"] >= 1


def test_create_drawing_l3_sheets_title_gdt(tmp_path: Path):
    k = _k(tmp_path)
    _make_part(k)

    spec = {
        "model": "plate.sldprt",
        "sheets": [
            {
                "name": "Sheet1",
                "paper": "A3",
                "scale": [1, 2],
                "views": [{"orient": "front"}],
            },
            {
                "name": "Sheet2",
                "paper": "A4",
                "scale": [1, 1],
                "views": [{"orient": "isometric"}],
            },
        ],
        "title_block": {
            "PartNo": "P-001",
            "Description": "支架",
            "DrawnBy": "AI",
            "Date": "2026-11-09",
        },
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
        "import_dimensions": False,
        "output_pdf": "plate_l3.pdf",
    }
    (tmp_path / "plate_l3.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    r = k.dispatch("create_drawing", {"spec_path": "plate_l3.json", "overwrite": True})
    assert r.ok, r.error
    assert r.result["sheet_count"] == 2
    assert len(r.result["sheets"]) == 2
    assert r.result["sheets"][0]["requested_name"] == "Sheet1"
    assert r.result["sheets"][0]["name"]  # actual name (fake Sheet1; real COM may be localized)
    assert r.result["title_block"].get("PartNo") == "P-001"
    assert len(r.result["datums"]) == 1
    assert len(r.result["gdts"]) == 1
    assert Path(r.result["pdf"]).is_file()
    assert "warnings" in r.result

    insp = k.dispatch("inspect_drawing")
    assert insp.ok, insp.error
    assert insp.result["sheet_count"] == 2
    assert insp.result["title_block"]["PartNo"] == "P-001"
    assert insp.result["title_block"]["Description"] == "支架"
    assert "PartNo" not in insp.result["missing_title_fields"]
    assert insp.result["datum_count"] == 1
    assert insp.result["gdt_count"] == 1
    assert insp.result["datums"][0].get("mode") == "native"
    assert insp.result["gdts"][0].get("mode") == "native"


def test_l3_fine_grained_tools(tmp_path: Path):
    k = _k(tmp_path)
    _make_part(k)
    assert k.dispatch("new_drawing").ok
    assert k.dispatch("create_drawing_view", {"path": "plate.sldprt", "view": "front"}).ok
    add = k.dispatch(
        "add_drawing_sheet",
        {"name": "Sheet2", "paper": "A4", "scale_num": 1, "scale_den": 2},
    )
    assert add.ok, add.error
    act = k.dispatch("activate_drawing_sheet", {"name": "Sheet1"})
    assert act.ok, act.error
    tb = k.dispatch(
        "set_title_block",
        {
            "entries": [
                {"key": "PartNo", "value": "X-1"},
                {"key": "Title", "value": "demo"},
            ]
        },
    )
    assert tb.ok, tb.error
    assert tb.result["count"] == 2
    d = k.dispatch("insert_datum", {"label": "B", "x": 50, "y": 40, "edge": 0})
    assert d.ok, d.error
    assert d.result.get("edge") == 0
    g = k.dispatch(
        "insert_gdt",
        {"symbol": "flatness", "tolerance": "0.05", "datums": [], "x": 60, "y": 40, "edge": 0},
    )
    assert g.ok, g.error
    insp = k.dispatch("inspect_drawing")
    assert insp.ok
    assert insp.result["sheet_count"] == 2
    assert insp.result["gdt_count"] >= 1
    assert insp.result["datums"][0].get("mode") == "native"
    assert insp.result["datums"][0].get("edge_selected") is True


def test_drawing_layers_and_dxf_export(tmp_path: Path):
    k = _k(tmp_path)
    _make_part(k)
    assert k.dispatch("new_drawing").ok
    assert k.dispatch("create_drawing_view", {"path": "plate.sldprt", "view": "front"}).ok

    added = k.dispatch("add_drawing_layer", {"name": "CADMCP_VIS", "color": 255})
    assert added.ok, added.error
    assert added.result["name"] == "CADMCP_VIS"
    assert added.result["color"] == 255

    dup = k.dispatch("add_drawing_layer", {"name": "CADMCP_VIS", "color": 255})
    assert not dup.ok
    assert dup.error and dup.error.code == "INVALID_ARGUMENT"

    missing = k.dispatch("set_drawing_layer", {"name": "NoSuchLayer"})
    assert not missing.ok
    assert missing.error and missing.error.code == "FEATURE_NOT_FOUND"

    set_ok = k.dispatch("set_drawing_layer", {"name": "CADMCP_VIS"})
    assert set_ok.ok, set_ok.error
    assert set_ok.result["name"] == "CADMCP_VIS"

    listed = k.dispatch("list_drawing_layers")
    assert listed.ok, listed.error
    assert listed.result["current"] == "CADMCP_VIS"
    assert "CADMCP_VIS" in listed.result["layers"]
    assert listed.result["count"] >= 1

    out = k.dispatch("export", {"path": "with_layers.dxf"})
    assert out.ok, out.error
    dxf = Path(out.result["path"])
    assert dxf.is_file()
    text = dxf.read_text(encoding="utf-8")
    assert "CADMCP_VIS" in text
    assert "current=CADMCP_VIS" in text
