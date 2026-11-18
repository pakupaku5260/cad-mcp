"""Offline Fake tests for insert_weld_symbol + DrawingSpec welds."""
from __future__ import annotations

from pathlib import Path

from cadmcp.backend.fake.backend import FakeBackend
from cadmcp.kernel import Kernel
from cadmcp.toolsets.core import core_registry


def _k(tmp_path: Path) -> Kernel:
    return Kernel(core_registry(), FakeBackend(), workspace=tmp_path)


def _plate_drawing(k: Kernel) -> None:
    assert k.dispatch("new_part", {}).ok
    assert k.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert k.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 40, "y2": 30}).ok
    assert k.dispatch("end_sketch", {}).ok
    assert k.dispatch("extrude", {"depth": 10}).ok
    assert k.dispatch("save_document", {"path": "weld_p.sldprt", "overwrite": True}).ok
    assert k.dispatch("new_drawing", {}).ok
    assert k.dispatch("create_drawing_view", {"path": "weld_p.sldprt", "view": "front"}).ok


def test_insert_weld_symbol_and_inspect(tmp_path: Path) -> None:
    k = _k(tmp_path)
    _plate_drawing(k)
    r = k.dispatch("insert_weld_symbol", {"symbol": "FILL", "x": 90, "y": 70})
    assert r.ok, r.error
    assert r.result["symbol"] == "FILL"
    assert str(r.result["name"]).startswith("weld_FILL_")
    insp = k.dispatch("inspect_drawing", {})
    assert insp.ok, insp.error
    assert insp.result["weld_count"] == 1
    assert insp.result["welds"][0]["symbol"] == "FILL"
    assert insp.result["welds"][0]["mode"] == "native"


def test_insert_weld_symbol_rejects_unknown(tmp_path: Path) -> None:
    k = _k(tmp_path)
    _plate_drawing(k)
    r = k.dispatch("insert_weld_symbol", {"symbol": "NOPE"})
    assert not r.ok
    assert r.error and r.error.code == "INVALID_ARGUMENT"


def test_get_and_inspect_weld_symbol(tmp_path: Path) -> None:
    k = _k(tmp_path)
    _plate_drawing(k)
    assert k.dispatch("insert_weld_symbol", {"symbol": "FILL"}).ok
    g = k.dispatch("get_weld_annotations", {})
    assert g.ok, g.error
    assert g.result["count"] == 1
    assert g.result["annotations"][0]["index"] == 0
    insp = k.dispatch("inspect_weld_symbol", {"index": 0})
    assert insp.ok, insp.error
    assert insp.result["symbol"] == "FILL"
    assert insp.result["text_above_symbol"] == "FILL"
    missing = k.dispatch("inspect_weld_symbol", {"index": 9})
    assert not missing.ok
    assert missing.error and missing.error.code == "FEATURE_NOT_FOUND"


def test_verify_weld_symbol(tmp_path: Path) -> None:
    k = _k(tmp_path)
    _plate_drawing(k)
    assert k.dispatch("insert_weld_symbol", {"symbol": "FILL"}).ok
    ok = k.dispatch("verify_weld_symbol", {"symbol": "FILL", "index": 0})
    assert ok.ok, ok.error
    assert ok.result["ok"] is True
    assert ok.result["actual_symbol"] == "FILL"
    assert all(c["ok"] for c in ok.result["checks"])

    bad = k.dispatch("verify_weld_symbol", {"symbol": "BUTT", "index": 0})
    assert bad.ok, bad.error  # dispatch succeeds; payload ok=false
    assert bad.result["ok"] is False
    assert any(c["name"] == "weld.symbol_match" and not c["ok"] for c in bad.result["checks"])

    missing = k.dispatch("verify_weld_symbol", {"symbol": "FILL", "index": 3})
    assert missing.ok
    assert missing.result["ok"] is False


def test_drawing_spec_welds(tmp_path: Path) -> None:
    k = _k(tmp_path)
    assert k.dispatch("new_part", {}).ok
    assert k.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert k.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 20, "y2": 20}).ok
    assert k.dispatch("end_sketch", {}).ok
    assert k.dispatch("extrude", {"depth": 5}).ok
    assert k.dispatch("save_document", {"path": "spec_weld.sldprt", "overwrite": True}).ok
    spec = tmp_path / "weld_spec.json"
    spec.write_text(
        """
{
  "model": "spec_weld.sldprt",
  "views": [{"orient": "front"}],
  "import_dimensions": false,
  "welds": [{"symbol": "BUTT", "x": 110, "y": 90}]
}
""".strip(),
        encoding="utf-8",
    )
    r = k.dispatch("create_drawing", {"spec_path": "weld_spec.json"})
    assert r.ok, r.error
    assert r.result.get("welds")
    insp = k.dispatch("inspect_drawing", {})
    assert insp.ok
    assert insp.result["weld_count"] >= 1
