"""Real SW: face index drift after geometry change; dual-handle/query still resolve.

Verifies on COM that through-cut reassigns index while coordinates recover the face.

Run: CADMCP_REAL_SW=1 pytest -m sw tests/test_sw_handle_drift.py
"""

from __future__ import annotations

import math
import os
from collections.abc import Callable
from pathlib import Path

import pytest

from cadmcp.backend.protocol.protocol import CADBackend
from cadmcp.kernel import Kernel
from cadmcp.toolsets.core import core_registry


def _com_factory_or_skip() -> Callable[[], CADBackend]:
    if os.environ.get("CADMCP_REAL_SW") != "1":
        pytest.skip(
            "Real SW tests close all open documents without saving;"
            "Set CADMCP_REAL_SW=1 when OK to proceed"
        )
    try:
        from cadmcp.backend.solidworks.backend import ComBackend
    except (ImportError, AttributeError) as exc:
        pytest.skip(f"com_backend unavailable (Windows + pywin32): {exc}")

    if not getattr(ComBackend, "MODELING_DOMAIN_READY", False):
        pytest.skip("com_backend modeling not ready")

    def factory() -> CADBackend:
        backend = ComBackend.attach()
        for _ in range(20):
            if backend.active_document() is None:
                return backend
            backend.close_document(discard=True)
        pytest.fail("Could not close all SW documents (20 tries)")

    return factory


def _dist(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


@pytest.mark.sw
def test_real_face_index_drifts_after_cut_and_dual_handle_resolves(tmp_path: Path):
    """Through-cut drifts index; stale index+coords resolve via proximity."""
    k = Kernel(core_registry(), _com_factory_or_skip()(), workspace=tmp_path)

    assert k.dispatch("new_part", {}).ok
    assert k.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert k.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 60, "y2": 40}).ok
    assert k.dispatch("end_sketch", {}).ok
    assert k.dispatch("extrude", {"depth": 20}).ok

    before = k.dispatch("get_faces", {})
    assert before.ok and len(before.result["faces"]) == 6
    # left face; index may drift
    left = next(f for f in before.result["faces"] if abs(f["centroid"][0]) < 1e-6)
    remembered = left["index"]
    cx, cy, cz = left["centroid"]

    assert k.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert k.dispatch("sketch_rectangle", {"x1": 10, "y1": -5, "x2": 50, "y2": 45}).ok
    assert k.dispatch("end_sketch", {}).ok
    cut = k.dispatch("extrude_cut", {"direction": "through_all"})
    assert cut.ok, cut.error

    after = k.dispatch("get_faces", {})
    assert after.ok
    assert len(after.result["faces"]) > 6
    at_old = next(f for f in after.result["faces"] if f["index"] == remembered)
    assert _dist(at_old["centroid"], [cx, cy, cz]) > 2.0, (
        f"expected index {remembered} to drift, still {at_old['centroid']}"
    )

    # dual handle resolves
    resolved = k.dispatch(
        "select_face",
        {"index": remembered, "x": cx, "y": cy, "z": cz},
    )
    assert resolved.ok, resolved.error
    assert resolved.result["quality"] in {"exact", "proximity"}
    hit = resolved.result["selected_face"]
    hit_face = next(f for f in after.result["faces"] if f["index"] == hit)
    assert _dist(hit_face["centroid"], [cx, cy, cz]) <= 2.0

    # reject bogus coords
    miss = k.dispatch(
        "select_face",
        {"index": remembered, "x": 200, "y": 200, "z": 200},
    )
    assert not miss.ok and miss.error.code == "REF_NOT_FOUND"

    k.dispatch("close_document", {"discard": True})


@pytest.mark.sw
def test_real_fillet_grows_faces_requery_max_z(tmp_path: Path):
    """Fillet grows faces; max_z query and dual-handle still work."""
    k = Kernel(core_registry(), _com_factory_or_skip()(), workspace=tmp_path)

    assert k.dispatch("new_part", {}).ok
    assert k.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert k.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 50, "y2": 50}).ok
    assert k.dispatch("end_sketch", {}).ok
    assert k.dispatch("extrude", {"depth": 50}).ok

    top0 = k.dispatch("get_faces", {"kind": "plane", "query": "max_z"}).result["faces"][0]
    n0 = k.dispatch("get_geometry", {}).result["face_count"]
    assert k.dispatch("fillet", {"radius": 2}).ok
    n1 = k.dispatch("get_geometry", {}).result["face_count"]
    assert n1 > n0

    top1 = k.dispatch("get_faces", {"kind": "plane", "query": "max_z"}).result["faces"][0]
    assert _dist(top1["centroid"], top0["centroid"]) <= 1e-3

    resolved = k.dispatch(
        "select_face",
        {
            "index": top0["index"] + 50,
            "x": top0["centroid"][0],
            "y": top0["centroid"][1],
            "z": top0["centroid"][2],
        },
    )
    assert resolved.ok, resolved.error
    assert resolved.result["selected_face"] == top1["index"]

    k.dispatch("close_document", {"discard": True})
