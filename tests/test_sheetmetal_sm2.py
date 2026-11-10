"""Wave 7 SM2: miter/hems/unfold DXF/bend table (fake)."""
from __future__ import annotations

from pathlib import Path

from cadmcp.backend.fake.backend import FakeBackend
from cadmcp.kernel import Kernel
from cadmcp.toolsets.core import core_registry


def _k(tmp_path: Path) -> Kernel:
    return Kernel(core_registry(), FakeBackend(), workspace=tmp_path, verify_mutations=True)


def _base(k: Kernel) -> None:
    assert k.dispatch("new_part").ok
    assert k.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert k.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 40, "y2": 20}).ok
    assert k.dispatch("end_sketch").ok
    assert k.dispatch("base_flange", {"thickness": 1}).ok


def test_sm2_tools(tmp_path: Path):
    k = _k(tmp_path)
    _base(k)
    edges = k.dispatch("get_edges")
    assert edges.ok and edges.result["edges"]
    idx = int(edges.result["edges"][0]["index"])
    m = k.dispatch("miter_flange", {"edges": [idx], "length": 10})
    assert m.ok, m.error
    h = k.dispatch("hem_flange", {"edge": idx, "length": 5})
    assert h.ok, h.error
    table = k.dispatch("sheet_metal_bend_table")
    assert table.ok and table.result["count"] >= 1
    dxf = k.dispatch("export_flat_dxf", {"path": "flat.dxf", "overwrite": True})
    assert dxf.ok and Path(dxf.result["path"]).is_file()
