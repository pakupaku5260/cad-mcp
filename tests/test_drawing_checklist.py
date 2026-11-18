"""Drawing release checklist: inspect tolerance gaps + verify_model drawing thresholds."""
from __future__ import annotations

import json
from pathlib import Path

from cadmcp.backend.fake.backend import FakeBackend
from cadmcp.kernel import Kernel
from cadmcp.toolsets.core import core_registry


def _k(tmp_path: Path) -> Kernel:
    return Kernel(core_registry(), FakeBackend(), workspace=tmp_path, verify_mutations=True)


def _part(k: Kernel, name: str = "plate.sldprt") -> None:
    assert k.dispatch("new_part").ok
    assert k.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert k.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 30, "y2": 20}).ok
    assert k.dispatch("end_sketch").ok
    assert k.dispatch("extrude", {"depth": 8}).ok
    assert k.dispatch("save_document", {"path": name, "overwrite": True}).ok
    k.dispatch("close_document", {"discard": True})


def test_inspect_fills_untoleranced_after_import(tmp_path: Path):
    k = _k(tmp_path)
    _part(k)
    assert k.dispatch("new_drawing").ok
    assert k.dispatch("create_drawing_view", {"path": "plate.sldprt", "view": "front"}).ok
    assert k.dispatch("insert_model_items").ok
    insp = k.dispatch("inspect_drawing")
    assert insp.ok, insp.error
    assert insp.result["model_doc_type"] == "part"
    assert insp.result["dimensions"]
    assert insp.result["untoleranced_dimensions"] == insp.result["dimensions"]
    assert insp.result["missing_tolerances"] == []


def test_apply_tolerance_honest_count_and_gaps(tmp_path: Path):
    k = _k(tmp_path)
    _part(k)
    assert k.dispatch("new_drawing").ok
    assert k.dispatch("create_drawing_view", {"path": "plate.sldprt", "view": "front"}).ok
    assert k.dispatch("insert_model_items").ok
    # create_drawing path uses backend.apply; exercise via DrawingSpec
    spec = {
        "model": "plate.sldprt",
        "views": [{"orient": "front"}],
        "import_dimensions": True,
        "tolerances": [
            {"dimension": "D1@Sketch1", "type": 1, "values": [0.1, 0.05]},
            {"dimension": "NOPE@Missing", "type": 1, "values": [0.1, 0.05]},
        ],
        "title_block": {
            "PartNo": "P-1",
            "Description": "plate",
            "DrawnBy": "AI",
            "Date": "2026-11-16",
            "Material": "Al",
            "Revision": "A",
            "Title": "plate",
        },
    }
    (tmp_path / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
    r = k.dispatch("create_drawing", {"spec_path": "spec.json", "overwrite": True})
    assert r.ok, r.error
    assert r.result["tolerance_count"] == 1  # only D1 applied
    insp = k.dispatch("inspect_drawing")
    assert insp.ok
    assert "D1@Sketch1" not in insp.result["untoleranced_dimensions"]
    assert "NOPE@Missing" in insp.result["missing_tolerances"]
    assert "D2@Sketch1" in insp.result["untoleranced_dimensions"]


def test_verify_part_drawing_skips_bom_but_checks_title(tmp_path: Path):
    k = _k(tmp_path)
    _part(k)
    assert k.dispatch("new_drawing").ok
    assert k.dispatch("create_drawing_view", {"path": "plate.sldprt", "view": "front"}).ok
    # Incomplete title → fail
    bad = k.dispatch("verify_model", {"groups": ["drawing"]})
    assert bad.ok and bad.result["verification"]["status"] == "failed"
    # Skip title + no BOM required for part
    ok = k.dispatch(
        "verify_model",
        {"groups": ["drawing"], "thresholds": {"required_title_keys": [], "require_bom": False}},
    )
    assert ok.ok and ok.result["verification"]["status"] == "verified"


def test_verify_assembly_drawing_requires_bom(tmp_path: Path):
    k = _k(tmp_path)
    _part(k, "p1.sldprt")
    _part(k, "p2.sldprt")
    assert k.dispatch("new_assembly").ok
    assert k.dispatch("insert_component", {"path": "p1.sldprt"}).ok
    assert k.dispatch("insert_component", {"path": "p2.sldprt", "x": 40}).ok
    assert k.dispatch("save_document", {"path": "asm.sldasm", "overwrite": True}).ok
    k.dispatch("close_document", {"discard": True})
    assert k.dispatch("new_drawing").ok
    assert k.dispatch("create_drawing_view", {"path": "asm.sldasm", "view": "front"}).ok
    # Fill title so only BOM is the gap
    assert k.dispatch(
        "set_title_block",
        {
            "entries": [
                {"key": "PartNo", "value": "A-1"},
                {"key": "Description", "value": "asm"},
                {"key": "DrawnBy", "value": "AI"},
                {"key": "Date", "value": "2026-11-16"},
                {"key": "Material", "value": "-"},
                {"key": "Revision", "value": "A"},
                {"key": "Title", "value": "asm"},
            ]
        },
    ).ok
    missing = k.dispatch(
        "verify_model",
        {"groups": ["drawing"], "thresholds": {"required_title_keys": []}},
    )
    # auto require_bom for assembly → fail without insert_bom
    assert missing.ok and missing.result["verification"]["status"] == "failed"
    assert k.dispatch("insert_bom", {"bom_type": "top"}).ok
    good = k.dispatch(
        "verify_model",
        {
            "groups": ["drawing"],
            "thresholds": {"required_title_keys": [], "min_datums": 0},
        },
    )
    assert good.ok and good.result["verification"]["status"] == "verified"


def test_verify_min_datums_and_fail_on_untoleranced(tmp_path: Path):
    k = _k(tmp_path)
    _part(k)
    assert k.dispatch("new_drawing").ok
    assert k.dispatch("create_drawing_view", {"path": "plate.sldprt", "view": "front"}).ok
    assert k.dispatch("insert_model_items").ok
    assert k.dispatch("insert_datum", {"label": "A"}).ok
    r = k.dispatch(
        "verify_model",
        {
            "groups": ["drawing"],
            "thresholds": {
                "required_title_keys": [],
                "require_bom": False,
                "min_datums": 2,
            },
        },
    )
    assert r.ok and r.result["verification"]["status"] == "failed"
    r2 = k.dispatch(
        "verify_model",
        {
            "groups": ["drawing"],
            "thresholds": {
                "required_title_keys": [],
                "require_bom": False,
                "min_datums": 1,
                "fail_on_untoleranced": True,
            },
        },
    )
    assert r2.ok and r2.result["verification"]["status"] == "failed"
