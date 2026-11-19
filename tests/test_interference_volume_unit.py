"""P5-2: check_interference volume_unit conversion."""
from __future__ import annotations

from pathlib import Path

from cadmcp.backend.fake.backend import FakeBackend
from cadmcp.kernel import Kernel
from cadmcp.toolsets.core import core_registry


def _two_overlapping(k: Kernel, ws: Path) -> tuple[str, str]:
    assert k.dispatch("new_part", {}).ok
    assert k.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert k.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 20, "y2": 20}).ok
    assert k.dispatch("end_sketch", {}).ok
    assert k.dispatch("extrude", {"depth": 10}).ok
    p1 = ws / "iv_a.sldprt"
    assert k.dispatch("save_document", {"path": str(p1), "overwrite": True}).ok
    k.dispatch("close_document", {"discard": True})

    assert k.dispatch("new_part", {}).ok
    assert k.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert k.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 20, "y2": 20}).ok
    assert k.dispatch("end_sketch", {}).ok
    assert k.dispatch("extrude", {"depth": 10}).ok
    p2 = ws / "iv_b.sldprt"
    assert k.dispatch("save_document", {"path": str(p2), "overwrite": True}).ok
    k.dispatch("close_document", {"discard": True})

    assert k.dispatch("new_assembly", {}).ok
    a = k.dispatch("insert_component", {"path": str(p1), "x": 0, "y": 0, "z": 0})
    b = k.dispatch("insert_component", {"path": str(p2), "x": 5, "y": 5, "z": 0})
    assert a.ok and b.ok
    return a.result["name"], b.result["name"]


def test_interference_volume_mm3(tmp_path: Path):
    k = Kernel(
        core_registry(),
        FakeBackend(interference_volume_m3=0.000257),
        workspace=tmp_path,
    )
    _two_overlapping(k, tmp_path)
    r = k.dispatch("check_interference", {"unit": "mm"})
    assert r.ok, r.error
    assert r.result["unit"] == "mm"
    assert r.result["count"] >= 1
    pair = r.result["pairs"][0]
    assert pair["volume_unit"] == "mm3"
    assert pair["volume"] == 257000.0


def test_interference_volume_cm3(tmp_path: Path):
    k = Kernel(
        core_registry(),
        FakeBackend(interference_volume_m3=0.000257),
        workspace=tmp_path,
    )
    _two_overlapping(k, tmp_path)
    r = k.dispatch("check_interference", {"unit": "cm"})
    assert r.ok, r.error
    assert r.result["unit"] == "cm"
    pair = r.result["pairs"][0]
    assert pair["volume_unit"] == "cm3"
    # 0.000257 m³ = 257 cm³
    assert abs(pair["volume"] - 257.0) < 1e-6


def test_interference_null_volume_still_has_unit(tmp_path: Path):
    k = Kernel(core_registry(), FakeBackend(), workspace=tmp_path)
    _two_overlapping(k, tmp_path)
    r = k.dispatch("check_interference", {})
    assert r.ok, r.error
    pair = r.result["pairs"][0]
    assert pair["volume"] is None
    assert pair["volume_unit"] == "mm3"
