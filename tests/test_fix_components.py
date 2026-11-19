"""fix_components task-layer mate helper (P4-2)."""

from __future__ import annotations

from pathlib import Path


def _two_parts(kernel, ws: Path):
    assert kernel.dispatch("new_part", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 10, "y2": 10}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("extrude", {"depth": 5}).ok
    p1 = ws / "fc_a.sldprt"
    assert kernel.dispatch("save_document", {"path": str(p1), "overwrite": True}).ok
    kernel.dispatch("close_document", {"discard": True})

    assert kernel.dispatch("new_part", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 10, "y2": 10}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("extrude", {"depth": 5}).ok
    p2 = ws / "fc_b.sldprt"
    assert kernel.dispatch("save_document", {"path": str(p2), "overwrite": True}).ok
    kernel.dispatch("close_document", {"discard": True})
    return p1, p2


def test_fix_components_preview_and_apply(kernel, tmp_path: Path):
    p1, p2 = _two_parts(kernel, tmp_path)
    assert kernel.dispatch("new_assembly", {}).ok
    a = kernel.dispatch("insert_component", {"path": str(p1), "x": 0, "y": 0, "z": 0})
    b = kernel.dispatch("insert_component", {"path": str(p2), "x": 40, "y": 10, "z": 5})
    assert a.ok and b.ok
    names = [a.result["name"], b.result["name"]]

    preview = kernel.dispatch(
        "fix_components",
        {"components": names, "preview_only": True},
    )
    assert preview.ok, preview.error
    assert preview.result["preview_only"] is True
    assert preview.result["mate_count"] == 3  # plan: 3 planes × 1 floater
    assert len(kernel.dispatch("list_mates", {}).result["mates"]) == 0

    applied = kernel.dispatch(
        "fix_components",
        {
            "components": names,
            "preview_only": False,
            "verify_pose": True,
            "tolerance_mm": 0.05,
        },
    )
    assert applied.ok, applied.error
    # Apply keeps at most one pose-preserving mate per floating instance.
    assert applied.result["mate_count"] == 1
    assert len(applied.result["applied"]) == 1
    mates = kernel.dispatch("list_mates", {})
    assert mates.ok and len(mates.result["mates"]) >= 1
