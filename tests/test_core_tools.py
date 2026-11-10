"""Core toolset E2E (Kernel + fake): golden values, units, sandbox, discard confirm, pedagogical errors."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from cadmcp.backend.protocol.models import FaceRef
from cadmcp.kernel import Kernel


def _build_cube(kernel: Kernel, size_mm: float = 50.0) -> None:
    """Minimal cube ops (spec macro shape): origin 0..size."""
    assert kernel.dispatch("new_part", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch("sketch_rectangle",
                           {"x1": 0, "y1": 0, "x2": size_mm, "y2": size_mm}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("extrude", {"depth": size_mm}).ok


# ---------- Golden path ----------


def test_golden_50mm_cube_volume_125000(kernel: Kernel):
    _build_cube(kernel)
    mp = kernel.dispatch("get_mass_properties", {})
    assert mp.ok
    assert mp.result["volume"] == pytest.approx(125000.0, rel=1e-9)
    assert mp.result["volume_unit"] == "mm3"
    assert mp.result["mass_kg"] == pytest.approx(0.125, rel=1e-9)
    assert mp.result["center_of_mass"] == pytest.approx([25.0, 25.0, 25.0], abs=1e-6)
    # read: no state_version bump
    assert mp.state_version == 5

    geo = kernel.dispatch("get_geometry", {})
    assert geo.ok
    assert geo.result["face_count"] == 6
    assert geo.result["edge_count"] == 12
    assert geo.result["bbox"] == pytest.approx([0.0, 0.0, 0.0, 50.0, 50.0, 50.0], abs=1e-6)

    feats = kernel.dispatch("list_features", {})
    assert [f["name"] for f in feats.result["features"]] == ["Boss-Extrude1"]


def test_set_extrude_depth_dimension(kernel: Kernel):
    _build_cube(kernel)
    listed = kernel.dispatch("list_dimensions", {})
    assert listed.ok, listed.error
    names = [d["name"] for d in listed.result["dimensions"]]
    assert "D1@Boss-Extrude1" in names
    row = next(d for d in listed.result["dimensions"] if d["name"] == "D1@Boss-Extrude1")
    assert row["value"] == pytest.approx(50.0, abs=1e-6)
    changed = kernel.dispatch("set_dimension", {"name": "D1@Boss-Extrude1", "value": 80})
    assert changed.ok, changed.error
    assert changed.result["value"] == pytest.approx(80.0, abs=1e-6)
    geo = kernel.dispatch("get_geometry", {})
    assert geo.result["bbox"] == pytest.approx([0.0, 0.0, 0.0, 50.0, 50.0, 80.0], abs=1e-6)
    mp = kernel.dispatch("get_mass_properties", {})
    assert mp.result["volume"] == pytest.approx(200_000.0, rel=1e-9)
    missing = kernel.dispatch("set_dimension", {"name": "D9@NoSuch", "value": 10})
    assert not missing.ok and missing.error.code == "FEATURE_NOT_FOUND"
    bad = kernel.dispatch("set_dimension", {"name": "D1@Boss-Extrude1", "value": 0})
    assert not bad.ok and bad.error.code == "INVALID_ARGUMENT"
    kernel.dispatch("new_assembly", {})
    asm = kernel.dispatch("list_dimensions", {})
    assert not asm.ok and asm.error.code == "INVALID_ARGUMENT"


def test_sketch_dimension_drives_extrude_volume(kernel: Kernel):
    assert kernel.dispatch("new_part", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 10}).ok
    assert kernel.dispatch("add_sketch_dimension", {"entity1": 0, "value": 40}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("extrude", {"depth": 10}).ok
    listed = kernel.dispatch("list_dimensions", {})
    names = [d["name"] for d in listed.result["dimensions"]]
    assert "D1@Sketch1" in names
    changed = kernel.dispatch("set_dimension", {"name": "D1@Sketch1", "value": 20})
    assert changed.ok, changed.error
    mp = kernel.dispatch("get_mass_properties", {})
    assert mp.result["volume"] == pytest.approx(math.pi * 100.0 * 10.0, rel=1e-6)


def test_sketch_without_driving_dimension_cannot_param_profile(kernel: Kernel):
    """No driving sketch dimension by default; PARAM cannot change profile depth only.

    See test_sketch_dimension_drives_extrude_volume.
    """
    assert kernel.dispatch("new_part", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 10}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("extrude", {"depth": 10}).ok
    listed = kernel.dispatch("list_dimensions", {})
    assert listed.ok, listed.error
    names = [d["name"] for d in listed.result["dimensions"]]
    assert "D1@Boss-Extrude1" in names
    assert not any("@Sketch" in n for n in names)
    missing = kernel.dispatch("set_dimension", {"name": "D1@Sketch1", "value": 20})
    assert not missing.ok and missing.error.code == "FEATURE_NOT_FOUND"


def test_revolve_angle_dimension(kernel: Kernel):
    _revolve_setup(kernel)
    r = kernel.dispatch("revolve", {"axis": "+x", "angle_deg": 180})
    assert r.ok, r.error
    listed = kernel.dispatch("list_dimensions", {})
    row = next(d for d in listed.result["dimensions"] if d["kind"] == "angle")
    assert row["value"] == pytest.approx(180.0, abs=1e-6)
    half_vol = kernel.dispatch("get_mass_properties", {}).result["volume"]
    changed = kernel.dispatch("set_dimension", {"name": row["name"], "value": 360})
    assert changed.ok, changed.error
    assert changed.result["unit"] == "deg"
    full = kernel.dispatch("get_mass_properties", {}).result["volume"]
    assert full == pytest.approx(2 * half_vol, rel=1e-6)


def test_mirror_right_plane_doubles_volume(kernel: Kernel):
    assert kernel.dispatch("new_part", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch("sketch_rectangle", {"x1": 10, "y1": 0, "x2": 30, "y2": 20}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("extrude", {"depth": 10}).ok
    before = kernel.dispatch("get_mass_properties", {}).result["volume"]
    assert before == pytest.approx(4000.0, rel=1e-6)
    r = kernel.dispatch("mirror", {"feature": "Boss-Extrude1", "plane": "Right Plane"})
    assert r.ok, r.error
    assert r.result["name"] == "Mirror1"
    mp = kernel.dispatch("get_mass_properties", {})
    assert mp.result["volume"] == pytest.approx(8000.0, rel=1e-6)
    geo = kernel.dispatch("get_geometry", {})
    assert geo.result["bbox"] == pytest.approx([-30.0, 0.0, 0.0, 30.0, 20.0, 10.0], abs=1e-6)
    missing_plane = kernel.dispatch("mirror", {"feature": "Boss-Extrude1", "plane": "NoSuch"})
    assert not missing_plane.ok and missing_plane.error.code == "INVALID_ARGUMENT"
    missing_feat = kernel.dispatch("mirror", {"feature": "Nope", "plane": "Right Plane"})
    assert not missing_feat.ok and missing_feat.error.code == "FEATURE_NOT_FOUND"


def test_offset_plane_sketch_bbox_and_volume(kernel: Kernel):
    assert kernel.dispatch("new_part", {}).ok
    created = kernel.dispatch("create_plane", {"reference": "Front Plane", "offset": 20})
    assert created.ok, created.error
    assert created.result["name"] == "Plane1"
    planes = kernel.dispatch("list_planes", {}).result["planes"]
    assert planes[:3] == ["Front Plane", "Top Plane", "Right Plane"]
    assert "Plane1" in planes
    zh = kernel.dispatch("start_sketch", {"plane": "前视基准面"})
    assert zh.ok
    kernel.dispatch("end_sketch", {})
    assert kernel.dispatch("start_sketch", {"plane": "Plane1"}).ok
    assert kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 10}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("extrude", {"depth": 10}).ok
    geo = kernel.dispatch("get_geometry", {})
    assert geo.result["bbox"] == pytest.approx([-10.0, -10.0, 20.0, 10.0, 10.0, 30.0], abs=1e-6)
    mp = kernel.dispatch("get_mass_properties", {})
    assert mp.result["volume"] == pytest.approx(math.pi * 100.0 * 10.0, rel=1e-6)
    missing = kernel.dispatch("create_plane", {"reference": "NoSuch", "offset": 10})
    assert not missing.ok and missing.error.code == "FEATURE_NOT_FOUND"
    axis = kernel.dispatch("create_axis", {"planes": ["Front Plane", "Right Plane"]})
    assert axis.ok and axis.result["name"] == "Axis1"
    parallel = kernel.dispatch("create_axis", {"planes": ["Front Plane", "Plane1"]})
    assert not parallel.ok and parallel.error.code == "FEATURE_CREATE_FAILED"
    empty = kernel.dispatch("create_axis", {})
    assert not empty.ok and empty.error.code == "INVALID_ARGUMENT"


def test_angle_and_points_planes(kernel: Kernel):
    assert kernel.dispatch("new_part", {}).ok
    axis = kernel.dispatch("create_axis", {"planes": ["Front Plane", "Right Plane"]})
    assert axis.ok, axis.error
    missing_axis = kernel.dispatch(
        "create_plane", {"mode": "angle", "reference": "Front Plane", "angle_deg": 30}
    )
    assert not missing_axis.ok and missing_axis.error.code == "INVALID_ARGUMENT"
    plane = kernel.dispatch(
        "create_plane",
        {"mode": "angle", "reference": "Front Plane", "axis": "Axis1", "angle_deg": 30},
    )
    assert plane.ok, plane.error
    assert plane.result["name"] == "Plane1" and plane.result["mode"] == "angle"
    assert kernel.dispatch("start_sketch", {"plane": "Plane1"}).ok
    assert kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 10}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("extrude", {"depth": 10}).ok
    geo = kernel.dispatch("get_geometry", {})
    c, s = math.cos(math.radians(30)), math.sin(math.radians(30))
    r, d = 10.0, 10.0
    assert geo.result["bbox"] == pytest.approx(
        [-r * c, -r, -r * s, r * c + d * s, r, r * s + d * c], abs=1e-5
    )
    mp = kernel.dispatch("get_mass_properties", {})
    assert mp.result["volume"] == pytest.approx(math.pi * r * r * d, rel=1e-6)
    pts = kernel.dispatch(
        "create_plane",
        {"mode": "points", "points": [[0, 0, 0], [20, 0, 0], [0, 30, 10]]},
    )
    assert pts.ok, pts.error
    assert pts.result["name"] == "Plane2"
    collinear = kernel.dispatch(
        "create_plane",
        {"mode": "points", "points": [[0, 0, 0], [10, 0, 0], [20, 0, 0]]},
    )
    assert not collinear.ok and collinear.error.code == "FEATURE_CREATE_FAILED"
    missing = kernel.dispatch(
        "create_plane",
        {"mode": "angle", "reference": "NoSuch", "axis": "Axis1", "angle_deg": 30},
    )
    assert not missing.ok and missing.error.code == "FEATURE_NOT_FOUND"


def test_equation_drives_extrude_depth(kernel: Kernel):
    _build_cube(kernel)
    empty = kernel.dispatch("list_equations", {})
    assert empty.ok and empty.result["count"] == 0
    g = kernel.dispatch("set_equation", {"name": "D", "expression": "80"})
    assert g.ok, g.error
    bind = kernel.dispatch("set_equation", {"name": "D1@Boss-Extrude1", "expression": "D"})
    assert bind.ok, bind.error
    mp = kernel.dispatch("get_mass_properties", {})
    assert mp.result["volume"] == pytest.approx(200_000.0, rel=1e-6)
    again = kernel.dispatch("set_equation", {"name": "D", "expression": "100"})
    assert again.ok
    mp2 = kernel.dispatch("get_mass_properties", {})
    assert mp2.result["volume"] == pytest.approx(250_000.0, rel=1e-6)
    listed = kernel.dispatch("list_equations", {})
    names = [e["name"] for e in listed.result["equations"]]
    assert "D" in names and "D1@Boss-Extrude1" in names
    bad = kernel.dispatch("set_equation", {"name": "D", "expression": "MsgBox(1)"})
    assert not bad.ok and bad.error.code == "INVALID_ARGUMENT"
    missing = kernel.dispatch("set_equation", {"name": "D1@NoSuch", "expression": "1"})
    assert not missing.ok and missing.error.code == "FEATURE_NOT_FOUND"
    kernel.dispatch("new_assembly", {})
    asm = kernel.dispatch("list_equations", {})
    assert not asm.ok and asm.error.code == "INVALID_ARGUMENT"


def test_unit_parameter_cm_flow(kernel: Kernel):
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {})
    kernel.dispatch("sketch_rectangle",
                    {"x1": 0, "y1": 0, "x2": 5, "y2": 5, "unit": "cm"})
    kernel.dispatch("end_sketch", {})
    r = kernel.dispatch("extrude", {"depth": 2, "unit": "cm"})
    assert r.ok and r.result["unit"] == "cm"
    mp = kernel.dispatch("get_mass_properties", {})
    assert mp.result["volume"] == pytest.approx(50_000.0, rel=1e-9)  # 50 cm³ → mm³


def test_invalid_unit_rejected_by_schema(kernel: Kernel):
    r = kernel.dispatch("extrude", {"depth": 5, "unit": "furlong"})
    assert not r.ok
    assert r.error.code == "INVALID_ARGUMENT"
    assert "furlong" in r.error.message


# ---------- Sandbox gates ----------


def test_save_rejects_escape_path(kernel: Kernel):
    kernel.dispatch("new_part", {})
    r = kernel.dispatch("save_document", {"path": "../escape.sldprt"})
    assert not r.ok
    assert r.error.code == "PATH_OUTSIDE_SANDBOX"


def test_save_overwrite_protection(kernel: Kernel, workspace):
    kernel.dispatch("new_part", {})
    assert kernel.dispatch("save_document", {"path": "parts/bracket.sldprt"}).ok
    assert (workspace / "parts" / "bracket.sldprt").exists()

    again = kernel.dispatch("save_document", {"path": "parts/bracket.sldprt"})
    assert not again.ok
    assert again.error.code == "PATH_OVERWRITE_DENIED"
    assert "overwrite" in again.error.hint

    forced = kernel.dispatch("save_document", {"path": "parts/bracket.sldprt", "overwrite": True})
    assert forced.ok


def test_open_missing_and_wrong_extension(kernel: Kernel):
    miss = kernel.dispatch("open_document", {"path": "nope.sldprt"})
    assert not miss.ok
    assert miss.error.code == "PATH_NOT_FOUND"

    bad = kernel.dispatch("open_document", {"path": "notes.txt"})
    assert not bad.ok
    assert bad.error.code == "PATH_EXTENSION_DENIED"


# ---------- Discard confirm ----------


def test_close_unsaved_requires_discard(kernel: Kernel):
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {})  # modified=True
    kernel.dispatch("end_sketch", {})

    refused = kernel.dispatch("close_document", {})
    assert not refused.ok
    assert refused.error.code == "INVALID_ARGUMENT"
    assert "discard" in refused.error.hint

    ok = kernel.dispatch("close_document", {"discard": True})
    assert ok.ok and ok.result["discarded"] is True
    after = kernel.dispatch("get_active_document", {})
    assert after.error.code == "NO_ACTIVE_DOCUMENT"


# ---------- Pedagogical errors ----------


def test_bad_plane_lists_candidates_in_hint(kernel: Kernel):
    kernel.dispatch("new_part", {})
    r = kernel.dispatch("start_sketch", {"plane": "侧视"})
    assert not r.ok
    assert r.error.code == "SKETCH_NOT_FOUND"
    assert "Front Plane" in r.error.hint


def test_extrude_without_sketch_points_to_sequence(kernel: Kernel):
    kernel.dispatch("new_part", {})
    r = kernel.dispatch("extrude", {"depth": 5})
    assert not r.ok
    assert r.error.code == "SKETCH_NOT_FOUND"
    assert "end_sketch" in r.error.hint


def test_screenshot_writes_and_protects(kernel: Kernel, workspace):
    kernel.dispatch("new_part", {})
    r = kernel.dispatch("screenshot", {"path": "out/iso.png", "view": "isometric"})
    assert r.ok
    assert (workspace / "out" / "iso.png").read_bytes().startswith(b"\x89PNG")

    again = kernel.dispatch("screenshot", {"path": "out/iso.png"})
    assert not again.ok
    assert again.error.code == "PATH_OVERWRITE_DENIED"

    forced = kernel.dispatch("screenshot", {"path": "out/iso.png", "overwrite": True})
    assert forced.ok


def test_material_and_configuration(kernel: Kernel):
    kernel.dispatch("new_part", {})
    empty = kernel.dispatch("get_material", {})
    assert empty.ok and empty.result["name"] == ""
    bad = kernel.dispatch("set_material", {"name": ""})
    assert not bad.ok and bad.error.code == "INVALID_ARGUMENT"
    setm = kernel.dispatch("set_material", {"name": "AISI 1020"})
    assert setm.ok, setm.error
    assert setm.result["name"] == "AISI 1020"
    got = kernel.dispatch("get_material", {})
    assert got.ok and got.result["name"] == "AISI 1020"
    listed = kernel.dispatch("list_configurations", {})
    assert listed.ok and listed.result["active"] in listed.result["names"]
    missing = kernel.dispatch("set_configuration", {"name": "NoSuchConfig"})
    assert not missing.ok and missing.error.code == "FEATURE_NOT_FOUND"
    created = kernel.dispatch("set_configuration", {"name": "machined", "create": True})
    assert created.ok and created.result["created"] is True
    again = kernel.dispatch("set_configuration", {"name": "machined", "create": True})
    assert again.ok and again.result["created"] is False
    after = kernel.dispatch("list_configurations", {})
    assert "machined" in after.result["names"] and after.result["active"] == "machined"
    kernel.dispatch("new_assembly", {})
    asm_mat = kernel.dispatch("get_material", {})
    assert not asm_mat.ok and asm_mat.error.code == "INVALID_ARGUMENT"


def test_drawing_views(kernel: Kernel):
    _build_cube(kernel)
    saved = kernel.dispatch("save_document", {"path": "cube.sldprt"})
    assert saved.ok, saved.error
    too_soon = kernel.dispatch("create_drawing_view", {"path": "cube.sldprt", "view": "front"})
    assert not too_soon.ok and too_soon.error.code == "INVALID_ARGUMENT"
    drw = kernel.dispatch("new_drawing", {})
    assert drw.ok and drw.result["doc_type"] == "drawing"
    view = kernel.dispatch("create_drawing_view", {"path": "cube.sldprt", "view": "front"})
    assert view.ok, view.error
    assert view.result["view"] == "front"
    bad = kernel.dispatch("create_drawing_view", {"path": "cube.sldprt", "view": "nope"})
    assert not bad.ok and bad.error.code == "INVALID_ARGUMENT"
    mat = kernel.dispatch("get_material", {})
    assert not mat.ok and mat.error.code == "INVALID_ARGUMENT"


def test_drawing_detail_section_items_balloons_pdf(kernel: Kernel):
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    assert kernel.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 50, "y2": 50}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("extrude", {"depth": 20}).ok
    assert kernel.dispatch("save_document", {"path": "cube.sldprt"}).ok
    too_soon = kernel.dispatch("create_section_view", {})
    assert not too_soon.ok and too_soon.error.code == "INVALID_ARGUMENT"
    assert kernel.dispatch("new_drawing", {}).ok
    no_view = kernel.dispatch("create_section_view", {})
    assert not no_view.ok and no_view.error.code == "INVALID_ARGUMENT"
    assert kernel.dispatch("create_drawing_view", {"path": "cube.sldprt", "view": "front"}).ok
    items = kernel.dispatch("insert_model_items", {})
    assert items.ok, items.error
    assert items.result["count"] >= 0
    sec = kernel.dispatch("create_section_view", {"label": "A"})
    assert sec.ok, sec.error
    assert sec.result["label"] == "A"
    pdf = kernel.dispatch("export", {"path": "cube.pdf"})
    assert pdf.ok, pdf.error
    assert pdf.result["saved"] is True
    kernel.dispatch("new_assembly", {})
    assert kernel.dispatch("insert_component", {"path": "cube.sldprt"}).ok
    assert kernel.dispatch("insert_component", {"path": "cube.sldprt", "x": 80}).ok
    assert kernel.dispatch("save_document", {"path": "asm.sldasm"}).ok
    assert kernel.dispatch("new_drawing", {}).ok
    assert kernel.dispatch("create_drawing_view", {"path": "asm.sldasm", "view": "front"}).ok
    balloons = kernel.dispatch("insert_balloons", {})
    assert balloons.ok, balloons.error
    assert balloons.result["count"] >= 1
    kernel.dispatch("new_part", {})
    on_part = kernel.dispatch("export", {"path": "part.pdf"})
    assert not on_part.ok and on_part.error.code == "INVALID_ARGUMENT"


def test_export_formats_follow_extension(kernel: Kernel, workspace: Path):
    _build_cube(kernel, 20.0)
    before = kernel.dispatch("get_active_document", {}).result
    step = kernel.dispatch("export", {"path": "cube.step"})
    assert step.ok, step.error
    assert (workspace / "cube.step").read_text(encoding="utf-8") == (
        f"FAKE-EXPORT:step:{before['title']}"
    )
    assert kernel.dispatch("export", {"path": "cube.stl"}).ok
    after = kernel.dispatch("get_active_document", {}).result
    assert after["path"] == before["path"] and after["title"] == before["title"]
    assert after["modified"] == before["modified"]
    again = kernel.dispatch("export", {"path": "cube.step"})
    assert not again.ok and again.error.code == "PATH_OVERWRITE_DENIED"
    assert kernel.dispatch("export", {"path": "cube.step", "overwrite": True}).ok
    unknown = kernel.dispatch("export", {"path": "cube.xyz"})
    assert not unknown.ok and unknown.error.code == "INVALID_ARGUMENT"

    assert kernel.dispatch("new_assembly", {}).ok
    assert kernel.dispatch("export", {"path": "asm.stp"}).ok
    assert kernel.dispatch("new_drawing", {}).ok
    assert kernel.dispatch("export", {"path": "sheet.dxf"}).ok
    as_step = kernel.dispatch("export", {"path": "sheet.step"})
    assert not as_step.ok and as_step.error.code == "INVALID_ARGUMENT"


def test_export_options_step_ap_and_stl_quality(kernel: Kernel, workspace: Path):
    _build_cube(kernel, 20.0)
    before = kernel.dispatch("get_active_document", {}).result
    ap214 = kernel.dispatch("export", {"path": "a.step", "step_ap": 214})
    assert ap214.ok and ap214.result.get("step_ap") == 214
    assert (workspace / "a.step").read_text(encoding="utf-8") == (
        f"FAKE-EXPORT:step:{before['title']}:ap=214"
    )
    fine = kernel.dispatch("export", {"path": "b.stl", "stl_quality": "fine"})
    assert fine.ok and fine.result.get("stl_quality") == "fine"
    assert (workspace / "b.stl").read_text(encoding="utf-8").endswith(":quality=fine")
    bad_ap = kernel.dispatch("export", {"path": "c.stl", "step_ap": 214})
    assert not bad_ap.ok and bad_ap.error.code == "INVALID_ARGUMENT"
    bad_q = kernel.dispatch("export", {"path": "d.step", "stl_quality": "coarse"})
    assert not bad_q.ok and bad_q.error.code == "INVALID_ARGUMENT"
    bad_242 = kernel.dispatch("export", {"path": "e.step", "step_ap": 242})
    assert not bad_242.ok and bad_242.error.code == "INVALID_ARGUMENT"


def test_subassembly_insert_lists_nested_children(kernel: Kernel):
    _build_cube(kernel, 20.0)
    assert kernel.dispatch("save_document", {"path": "p1.sldprt"}).ok
    kernel.dispatch("close_document", {"discard": True})
    _build_cube(kernel, 20.0)
    assert kernel.dispatch("save_document", {"path": "p2.sldprt"}).ok
    kernel.dispatch("close_document", {"discard": True})
    assert kernel.dispatch("new_assembly", {}).ok
    assert kernel.dispatch("insert_component", {"path": "p1.sldprt"}).ok
    assert kernel.dispatch("insert_component", {"path": "p2.sldprt", "x": 30}).ok
    assert kernel.dispatch("save_document", {"path": "sub.sldasm"}).ok
    kernel.dispatch("close_document", {"discard": True})
    assert kernel.dispatch("new_assembly", {}).ok
    first = kernel.dispatch("insert_component", {"path": "sub.sldasm"})
    assert first.ok, first.error
    assert first.result["name"] == "sub-1"
    second = kernel.dispatch("insert_component", {"path": "sub.sldasm", "x": 80})
    assert second.ok and second.result["name"] == "sub-2"
    top = kernel.dispatch("list_components", {})
    assert top.ok and top.result["count"] == 2
    names = [c["name"] for c in top.result["components"]]
    assert names == ["sub-1", "sub-2"]
    flat = kernel.dispatch("list_components", {"children": True})
    assert flat.ok and flat.result["count"] == 6
    flat_names = [c["name"] for c in flat.result["components"]]
    assert "p1-1@sub-1" in flat_names and "p2-1@sub-1" in flat_names
    child = kernel.dispatch("get_component", {"component": "p1-1@sub-1"})
    assert child.ok, child.error
    missing_asm = kernel.dispatch("insert_component", {"path": "nope.sldasm"})
    assert not missing_asm.ok and missing_asm.error.code == "PATH_NOT_FOUND"
    kernel.dispatch("new_part", {})
    on_part = kernel.dispatch("insert_component", {"path": "sub.sldasm"})
    assert not on_part.ok and on_part.error.code == "INVALID_ARGUMENT"


def test_in_context_edit_subassembly(kernel: Kernel):
    _build_cube(kernel, 20.0)
    assert kernel.dispatch("save_document", {"path": "p1.sldprt"}).ok
    kernel.dispatch("close_document", {"discard": True})
    _build_cube(kernel, 20.0)
    assert kernel.dispatch("save_document", {"path": "p2.sldprt"}).ok
    kernel.dispatch("close_document", {"discard": True})
    assert kernel.dispatch("new_assembly", {}).ok
    assert kernel.dispatch("insert_component", {"path": "p1.sldprt"}).ok
    assert kernel.dispatch("insert_component", {"path": "p2.sldprt", "x": 30}).ok
    assert kernel.dispatch("save_document", {"path": "sub.sldasm"}).ok
    kernel.dispatch("close_document", {"discard": True})
    assert kernel.dispatch("new_assembly", {}).ok
    assert kernel.dispatch("insert_component", {"path": "sub.sldasm"}).ok
    assert kernel.dispatch("insert_component", {"path": "p1.sldprt", "x": 80}).ok
    idle = kernel.dispatch("get_edit_target", {})
    assert idle.ok and idle.result["editing"] is False and idle.result["component"] is None
    too_soon = kernel.dispatch("end_edit", {})
    assert not too_soon.ok and too_soon.error.code == "INVALID_ARGUMENT"
    empty = kernel.dispatch("edit_component", {"component": ""})
    assert not empty.ok and empty.error.code == "INVALID_ARGUMENT"
    missing = kernel.dispatch("edit_component", {"component": "nope"})
    assert not missing.ok and missing.error.code == "INVALID_ARGUMENT"
    on_part = kernel.dispatch("edit_component", {"component": "p1-1"})
    assert not on_part.ok and on_part.error.code == "INVALID_ARGUMENT"
    entered = kernel.dispatch("edit_component", {"component": "sub-1"})
    assert entered.ok, entered.error
    assert entered.result["editing"] is True and entered.result["component"] == "sub-1"
    target = kernel.dispatch("get_edit_target", {})
    assert target.ok and target.result["editing"] is True and target.result["component"] == "sub-1"
    mate = kernel.dispatch(
        "mate",
        {"type": "coincident", "entity1": "Front Plane@p1-1@sub-1", "entity2": "Front Plane@p2-1@sub-1"},
    )
    assert mate.ok, mate.error
    listed = kernel.dispatch("list_mates", {})
    assert listed.ok and listed.result["mates"]
    assert kernel.dispatch("end_edit", {}).ok
    after = kernel.dispatch("get_edit_target", {})
    assert after.ok and after.result["editing"] is False and after.result["component"] is None
    kernel.dispatch("new_part", {})
    not_asm = kernel.dispatch("edit_component", {"component": "sub-1"})
    assert not not_asm.ok and not_asm.error.code == "INVALID_ARGUMENT"


def test_set_lightweight_component(kernel: Kernel):
    _build_cube(kernel, 20.0)
    assert kernel.dispatch("save_document", {"path": "cube.sldprt"}).ok
    kernel.dispatch("close_document", {"discard": True})
    assert kernel.dispatch("new_assembly", {}).ok
    assert kernel.dispatch("insert_component", {"path": "cube.sldprt"}).ok
    before = kernel.dispatch("get_component", {"component": "cube-1"})
    assert before.ok and before.result["lightweight"] is False
    lw = kernel.dispatch("set_lightweight", {"component": "cube-1", "lightweight": True})
    assert lw.ok, lw.error
    assert lw.result["lightweight"] is True
    mid = kernel.dispatch("get_component", {"component": "cube-1"})
    assert mid.ok and mid.result["lightweight"] is True
    again = kernel.dispatch("set_lightweight", {"component": "cube-1", "lightweight": True})
    assert again.ok
    resolved = kernel.dispatch("set_lightweight", {"component": "cube-1", "lightweight": False})
    assert resolved.ok and resolved.result["lightweight"] is False
    after = kernel.dispatch("get_component", {"component": "cube-1"})
    assert after.ok and after.result["lightweight"] is False
    empty = kernel.dispatch("set_lightweight", {"component": "", "lightweight": True})
    assert not empty.ok and empty.error.code == "INVALID_ARGUMENT"
    missing = kernel.dispatch("set_lightweight", {"component": "nope", "lightweight": True})
    assert not missing.ok and missing.error.code == "INVALID_ARGUMENT"
    kernel.dispatch("new_part", {})
    on_part = kernel.dispatch("set_lightweight", {"component": "cube-1", "lightweight": True})
    assert not on_part.ok and on_part.error.code == "INVALID_ARGUMENT"


def test_explode_view_show_and_list(kernel: Kernel):
    _build_cube(kernel, 20.0)
    assert kernel.dispatch("save_document", {"path": "cube.sldprt"}).ok
    kernel.dispatch("close_document", {"discard": True})
    assert kernel.dispatch("new_assembly", {}).ok
    empty = kernel.dispatch("list_exploded_views", {})
    assert empty.ok and empty.result["count"] == 0 and empty.result["exploded"] is False
    too_soon = kernel.dispatch("show_exploded", {"show": True})
    assert not too_soon.ok and too_soon.error.code == "FEATURE_NOT_FOUND"
    assert kernel.dispatch("insert_component", {"path": "cube.sldprt"}).ok
    assert kernel.dispatch("insert_component", {"path": "cube.sldprt", "x": 40}).ok
    created = kernel.dispatch("explode_view", {})
    assert created.ok, created.error
    assert created.result["count"] >= 1 and created.result["exploded"] is True
    assert created.result["name"]
    listed = kernel.dispatch("list_exploded_views", {})
    assert listed.ok and listed.result["count"] >= 1 and listed.result["exploded"] is True
    collapsed = kernel.dispatch("show_exploded", {"show": False})
    assert collapsed.ok and collapsed.result["exploded"] is False
    shown = kernel.dispatch("show_exploded", {"show": True})
    assert shown.ok and shown.result["exploded"] is True
    missing = kernel.dispatch("show_exploded", {"show": True, "name": "nope"})
    assert not missing.ok and missing.error.code == "FEATURE_NOT_FOUND"
    kernel.dispatch("new_part", {})
    on_part = kernel.dispatch("explode_view", {})
    assert not on_part.ok and on_part.error.code == "INVALID_ARGUMENT"


def test_assembly_bom_rollup(kernel: Kernel):
    _build_cube(kernel)
    kernel.dispatch("set_material", {"name": "AISI 1020"})
    assert kernel.dispatch("save_document", {"path": "cube.sldprt"}).ok
    assert kernel.dispatch("new_assembly", {}).ok
    empty = kernel.dispatch("get_bom", {})
    assert empty.ok and empty.result["source"] == "assembly" and empty.result["count"] == 0
    assert kernel.dispatch("insert_component", {"path": "cube.sldprt"}).ok
    assert kernel.dispatch("insert_component", {"path": "cube.sldprt", "x": 40}).ok
    bom = kernel.dispatch("get_bom", {})
    assert bom.ok, bom.error
    assert bom.result["count"] == 1 and bom.result["rows"][0]["qty"] == 2
    assert bom.result["rows"][0]["part_number"] == "cube"
    assert bom.result["rows"][0]["material"] == "AISI 1020"
    assert kernel.dispatch("save_document", {"path": "asm.sldasm"}).ok
    assert kernel.dispatch("new_drawing", {}).ok
    missing = kernel.dispatch("get_bom", {})
    assert not missing.ok and missing.error.code == "FEATURE_NOT_FOUND"
    assert kernel.dispatch("create_drawing_view", {"path": "asm.sldasm", "view": "front"}).ok
    inserted = kernel.dispatch("insert_bom", {"bom_type": "top"})
    assert inserted.ok, inserted.error
    assert inserted.result["row_count"] >= 2
    drawn = kernel.dispatch("get_bom", {})
    assert drawn.ok, drawn.error
    assert drawn.result["source"] == "drawing"
    assert drawn.result["count"] >= 1


# ---------- Feature batch 1: revolve/cut (W6) ----------


def _revolve_setup(kernel: Kernel, x2: float = 10.0, y2: float = 20.0) -> None:
    """Rectangle profile; revolve +x → centroid radius y2/2."""
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    kernel.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": x2, "y2": y2})
    kernel.dispatch("end_sketch", {})


def test_top_plane_revolve_positive_z(kernel: Kernel):
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {"plane": "Top Plane"})
    kernel.dispatch("sketch_rectangle", {"x1": 10, "y1": 0, "x2": 20, "y2": 30})
    kernel.dispatch("end_sketch", {})
    r = kernel.dispatch("revolve", {"axis": "+z"})
    assert r.ok, r.error
    geo = kernel.dispatch("get_geometry", {})
    assert geo.ok
    xmin, ymin, zmin, xmax, ymax, zmax = geo.result["bbox"]
    assert zmin == pytest.approx(0.0, abs=1e-6)
    assert zmax == pytest.approx(30.0, abs=1e-6)
    assert xmax == pytest.approx(20.0, abs=1e-6)
    assert xmin == pytest.approx(-20.0, abs=1e-6)


def test_assembly_geometry_bbox(kernel: Kernel):
    _build_cube(kernel)
    assert kernel.dispatch("save_document", {"path": "cube.sldprt"}).ok
    assert kernel.dispatch("new_assembly", {}).ok
    assert kernel.dispatch("insert_component", {"path": "cube.sldprt"}).ok
    assert kernel.dispatch("insert_component", {"path": "cube.sldprt", "x": 40}).ok
    geo = kernel.dispatch("get_geometry", {})
    assert geo.ok, geo.error
    xmin, ymin, zmin, xmax, ymax, zmax = geo.result["bbox"]
    assert [xmin, ymin, zmin, xmax, ymax, zmax] == pytest.approx(
        [0.0, 0.0, 0.0, 90.0, 50.0, 50.0], abs=1e-6
    )


def test_move_and_rotate_component_pose(kernel: Kernel):
    _build_cube(kernel)
    assert kernel.dispatch("save_document", {"path": "cube.sldprt"}).ok
    assert kernel.dispatch("new_assembly", {}).ok
    ins = kernel.dispatch("insert_component", {"path": "cube.sldprt"})
    assert ins.ok, ins.error
    rot = kernel.dispatch(
        "rotate_component", {"component": ins.result["name"], "axis": "+z", "angle_deg": 90}
    )
    assert rot.ok, rot.error
    assert rot.result["origin"] == pytest.approx([0.0, 0.0, 0.0], abs=1e-6)
    geo = kernel.dispatch("get_geometry", {})
    assert geo.result["bbox"] == pytest.approx([-50.0, 0.0, 0.0, 0.0, 50.0, 50.0], abs=1e-6)
    moved = kernel.dispatch(
        "move_component", {"component": ins.result["name"], "x": 40, "y": 0, "z": 0}
    )
    assert moved.ok, moved.error
    assert moved.result["origin"] == pytest.approx([40.0, 0.0, 0.0], abs=1e-6)
    geo2 = kernel.dispatch("get_geometry", {})
    assert geo2.result["bbox"] == pytest.approx([-10.0, 0.0, 0.0, 40.0, 50.0, 50.0], abs=1e-6)
    missing = kernel.dispatch(
        "rotate_component", {"component": "nope-1", "axis": "+z", "angle_deg": 90}
    )
    assert not missing.ok and missing.error.code == "INVALID_ARGUMENT"
    bad_axis = kernel.dispatch(
        "rotate_component", {"component": ins.result["name"], "axis": "sideways", "angle_deg": 90}
    )
    assert not bad_axis.ok and bad_axis.error.code == "INVALID_ARGUMENT"

    rel = kernel.dispatch(
        "move_component",
        {"component": ins.result["name"], "x": 10, "y": 0, "z": 0, "relative": True},
    )
    assert rel.ok, rel.error
    assert rel.result["origin"] == pytest.approx([50.0, 0.0, 0.0], abs=1e-6)
    assert rel.result["relative"] is True

    ins2 = kernel.dispatch("insert_component", {"path": "cube.sldprt", "x": 80})
    assert ins2.ok, ins2.error
    spun = kernel.dispatch(
        "rotate_component",
        {
            "component": ins2.result["name"],
            "axis": "+z",
            "angle_deg": 90,
            "about": "world",
        },
    )
    assert spun.ok, spun.error
    assert spun.result["origin"] == pytest.approx([0.0, 80.0, 0.0], abs=1e-6)
    assert spun.result["about"] == "world"

    mate = kernel.dispatch(
        "mate",
        {"type": "coincident", "entity1": "Front Plane@cube-1", "entity2": "Front Plane@cube-2"},
    )
    assert mate.ok, mate.error
    locked = kernel.dispatch(
        "rotate_component",
        {"component": ins2.result["name"], "axis": "+z", "angle_deg": 45},
    )
    assert not locked.ok and locked.error.code == "FEATURE_CREATE_FAILED"
    locked_move = kernel.dispatch(
        "move_component",
        {"component": ins.result["name"], "x": 0, "y": 0, "z": 0},
    )
    assert not locked_move.ok and locked_move.error.code == "FEATURE_CREATE_FAILED"
    assert kernel.dispatch("delete_mate", {"name": mate.result["name"]}).ok
    unlocked = kernel.dispatch(
        "move_component",
        {"component": ins.result["name"], "x": 0, "y": 0, "z": 0},
    )
    assert unlocked.ok, unlocked.error


def test_mate_planes_solve_component_origin(kernel: Kernel):
    _build_cube(kernel)
    assert kernel.dispatch("save_document", {"path": "cube.sldprt"}).ok
    assert kernel.dispatch("new_assembly", {}).ok
    a = kernel.dispatch("insert_component", {"path": "cube.sldprt"})
    b = kernel.dispatch("insert_component", {"path": "cube.sldprt", "x": 80, "y": 10, "z": 20})
    assert a.ok and b.ok
    before = kernel.dispatch("get_component", {"component": b.result["name"]})
    assert before.result["origin"] == pytest.approx([80.0, 10.0, 20.0], abs=1e-6)
    assert kernel.dispatch(
        "mate",
        {"type": "coincident", "entity1": "Front Plane@cube-1", "entity2": "Front Plane@cube-2"},
    ).ok
    assert kernel.dispatch(
        "mate",
        {"type": "coincident", "entity1": "Top Plane@cube-1", "entity2": "Top Plane@cube-2"},
    ).ok
    assert kernel.dispatch(
        "mate",
        {"type": "coincident", "entity1": "Right Plane@cube-1", "entity2": "Right Plane@cube-2"},
    ).ok
    fixed = kernel.dispatch("get_component", {"component": "cube-1"})
    moved = kernel.dispatch("get_component", {"component": "cube-2"})
    assert fixed.result["origin"] == pytest.approx([0.0, 0.0, 0.0], abs=1e-6)
    assert moved.result["origin"] == pytest.approx([0.0, 0.0, 0.0], abs=1e-6)
    locked = kernel.dispatch(
        "move_component", {"component": "cube-2", "x": 5, "y": 0, "z": 0}
    )
    assert not locked.ok and locked.error.code == "FEATURE_CREATE_FAILED"


def test_mate_concentric_aligns_axes(kernel: Kernel):
    assert kernel.dispatch("new_part", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 10}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("extrude", {"depth": 30}).ok
    assert kernel.dispatch("save_document", {"path": "cyl.sldprt"}).ok
    assert kernel.dispatch("new_assembly", {}).ok
    assert kernel.dispatch("insert_component", {"path": "cyl.sldprt"}).ok
    ins = kernel.dispatch("insert_component", {"path": "cyl.sldprt", "x": 50, "y": 0, "z": 0})
    assert ins.ok
    mate = kernel.dispatch(
        "mate",
        {"type": "concentric", "entity1": "cyl-1#cylinder:0", "entity2": "cyl-2#cylinder:0"},
    )
    assert mate.ok, mate.error
    moved = kernel.dispatch("get_component", {"component": "cyl-2"})
    assert moved.result["origin"] == pytest.approx([0.0, 0.0, 0.0], abs=1e-5)


def test_extrude_cut_through_all(kernel: Kernel):
    _build_cube(kernel)
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch("sketch_circle", {"cx": 25, "cy": 25, "r": 5}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    cut = kernel.dispatch("extrude_cut", {"direction": "through_all"})
    assert cut.ok, cut.error
    assert cut.result["direction"] == "through_all"
    mp = kernel.dispatch("get_mass_properties", {})
    expected = 50.0 * 50.0 * 50.0 - math.pi * 25.0 * 50.0
    assert mp.result["volume"] == pytest.approx(expected, rel=1e-6)
    empty = kernel.dispatch("new_part", {})
    assert empty.ok
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 10, "y2": 10}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    missing = kernel.dispatch("extrude", {"direction": "through_all"})
    assert not missing.ok and missing.error.code == "FEATURE_CREATE_FAILED"


def test_extrude_up_to_next_and_surface(kernel: Kernel):
    assert kernel.dispatch("new_part", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 50, "y2": 20}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("extrude", {"depth": 10}).ok
    assert kernel.dispatch("create_plane", {"reference": "Front Plane", "offset": 40}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Plane1"}).ok
    assert kernel.dispatch("sketch_rectangle", {"x1": 10, "y1": 5, "x2": 20, "y2": 15}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    missing = kernel.dispatch("extrude", {"direction": "up_to_surface"})
    assert not missing.ok and missing.error.code == "INVALID_ARGUMENT"
    faces = kernel.dispatch("get_faces", {})
    assert faces.ok
    planes = [f for f in faces.result["faces"] if f["kind"] == "plane" and "normal" in f]
    end = max(planes, key=lambda f: f["centroid"][2])
    boss = kernel.dispatch("extrude", {"direction": "up_to_surface", "end_face": end["index"]})
    assert boss.ok, boss.error
    assert boss.result["direction"] == "up_to_surface"
    mp = kernel.dispatch("get_mass_properties", {})
    assert mp.result["volume"] == pytest.approx(13_000.0, rel=1e-6)
    empty = kernel.dispatch("new_part", {})
    assert empty.ok
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 10, "y2": 10}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    nxt = kernel.dispatch("extrude", {"direction": "up_to_next"})
    assert not nxt.ok and nxt.error.code == "FEATURE_CREATE_FAILED"


def test_extrude_up_to_vertex(kernel: Kernel):
    assert kernel.dispatch("new_part", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 40, "y2": 20}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("extrude", {"depth": 10}).ok
    assert kernel.dispatch("create_plane", {"reference": "Front Plane", "offset": 40}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Plane1"}).ok
    assert kernel.dispatch("sketch_rectangle", {"x1": 5, "y1": 5, "x2": 15, "y2": 15}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    missing = kernel.dispatch("extrude", {"direction": "up_to_vertex"})
    assert not missing.ok and missing.error.code == "INVALID_ARGUMENT"
    verts = kernel.dispatch("get_vertices", {})
    assert verts.ok and len(verts.result["vertices"]) >= 8
    top = max(verts.result["vertices"], key=lambda v: v["position"][2])
    boss = kernel.dispatch(
        "extrude", {"direction": "up_to_vertex", "end_vertex": top["index"]}
    )
    assert boss.ok, boss.error
    assert boss.result["direction"] == "up_to_vertex"
    assert boss.result["end_vertex"] == top["index"]
    mp = kernel.dispatch("get_mass_properties", {})
    # up_to_vertex volume
    assert mp.result["volume"] == pytest.approx(11000.0, rel=1e-6)
    assert kernel.dispatch("new_part", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 10, "y2": 10}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    empty = kernel.dispatch("extrude", {"direction": "up_to_vertex", "end_vertex": 0})
    assert not empty.ok and empty.error.code == "FEATURE_CREATE_FAILED"


def test_extrude_up_to_body(kernel: Kernel):
    """T5: up_to_body auto body plane; volume like up_to_surface."""
    assert kernel.dispatch("new_part", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 50, "y2": 20}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("extrude", {"depth": 10}).ok
    assert kernel.dispatch("create_plane", {"reference": "Front Plane", "offset": 40}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Plane1"}).ok
    assert kernel.dispatch("sketch_rectangle", {"x1": 10, "y1": 5, "x2": 20, "y2": 15}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    missing = kernel.dispatch("extrude", {"direction": "up_to_body"})
    assert not missing.ok and missing.error.code == "INVALID_ARGUMENT"
    bad = kernel.dispatch("extrude", {"direction": "up_to_body", "end_body": 999})
    assert not bad.ok and bad.error.code == "INVALID_ARGUMENT"
    boss = kernel.dispatch("extrude", {"direction": "up_to_body", "end_body": 0})
    assert boss.ok, boss.error
    assert boss.result["direction"] == "up_to_body"
    assert boss.result["end_body"] == 0
    mp = kernel.dispatch("get_mass_properties", {})
    assert mp.result["volume"] == pytest.approx(13_000.0, rel=1e-6)
    empty = kernel.dispatch("new_part", {})
    assert empty.ok
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 10, "y2": 10}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    no_body = kernel.dispatch("extrude", {"direction": "up_to_body", "end_body": 0})
    assert not no_body.ok and no_body.error.code == "FEATURE_CREATE_FAILED"


def test_revolve_about_edge(kernel: Kernel):
    _build_cube(kernel)
    edges = kernel.dispatch("get_edges", {})
    assert edges.ok
    lines = [e for e in edges.result["edges"] if e["kind"] == "line"]
    assert lines
    line = min(lines, key=lambda e: abs(e["midpoint"][2]))
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch("sketch_rectangle", {"x1": 60, "y1": 10, "x2": 80, "y2": 20}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    bad = kernel.dispatch("revolve", {"edge": 999, "angle_deg": 360})
    assert not bad.ok and bad.error.code == "INVALID_ARGUMENT"
    rev = kernel.dispatch("revolve", {"edge": line["index"], "angle_deg": 360})
    assert rev.ok, rev.error
    assert rev.result["edge"] == line["index"]
    mp = kernel.dispatch("get_mass_properties", {})
    assert mp.result["volume"] > 125_000.0


def test_list_and_pattern_components_and_color(kernel: Kernel):
    _build_cube(kernel)
    unset = kernel.dispatch("get_color", {})
    assert unset.ok and unset.result["color"] is None
    painted = kernel.dispatch("set_color", {"r": 0.2, "g": 0.4, "b": 0.6})
    assert painted.ok, painted.error
    assert painted.result["r"] == pytest.approx(0.2)
    got = kernel.dispatch("get_color", {})
    assert got.result["color"] == pytest.approx([0.2, 0.4, 0.6])
    bad_rgb = kernel.dispatch("set_color", {"r": 1.5, "g": 0, "b": 0})
    assert not bad_rgb.ok and bad_rgb.error.code == "INVALID_ARGUMENT"
    assert kernel.dispatch("save_document", {"path": "cube.sldprt"}).ok
    assert kernel.dispatch("new_assembly", {}).ok
    on_asm = kernel.dispatch("set_color", {"r": 1, "g": 0, "b": 0})
    assert not on_asm.ok and on_asm.error.code == "INVALID_ARGUMENT"
    ins = kernel.dispatch("insert_component", {"path": "cube.sldprt", "x": 40})
    assert ins.ok, ins.error
    listed = kernel.dispatch("list_components", {})
    assert listed.ok and listed.result["count"] == 1
    assert listed.result["components"][0]["name"] == ins.result["name"]
    one = kernel.dispatch("get_component", {"component": ins.result["name"]})
    assert one.ok and one.result["origin"] == pytest.approx([40.0, 0.0, 0.0], abs=1e-6)
    missing = kernel.dispatch("get_component", {"component": "nope-1"})
    assert not missing.ok and missing.error.code == "INVALID_ARGUMENT"
    pat = kernel.dispatch(
        "pattern_component",
        {"component": ins.result["name"], "count": 4, "axis": "+z"},
    )
    assert pat.ok, pat.error
    assert pat.result["count"] == 4
    names = [c["name"] for c in pat.result["components"]]
    assert names[0] == ins.result["name"]
    origins = [c["origin"] for c in pat.result["components"]]
    assert origins[0] == pytest.approx([40.0, 0.0, 0.0], abs=1e-6)
    assert origins[1] == pytest.approx([0.0, 40.0, 0.0], abs=1e-6)
    assert origins[2] == pytest.approx([-40.0, 0.0, 0.0], abs=1e-6)
    assert origins[3] == pytest.approx([0.0, -40.0, 0.0], abs=1e-6)
    too_few = kernel.dispatch(
        "pattern_component",
        {"component": ins.result["name"], "count": 1, "axis": "+z"},
    )
    assert not too_few.ok and too_few.error.code == "INVALID_ARGUMENT"
    assert pat.result["name"] == "LocalCirPattern1"

    mate = kernel.dispatch(
        "mate",
        {"type": "coincident", "entity1": "Front Plane@cube-1", "entity2": "Front Plane@cube-2"},
    )
    assert mate.ok, mate.error
    forced = kernel.dispatch(
        "move_component",
        {"component": "cube-1", "x": 45, "y": 0, "z": 0, "force": True},
    )
    assert forced.ok, forced.error
    assert forced.result["origin"] == pytest.approx([45.0, 0.0, 0.0], abs=1e-6)
    abs_rot = kernel.dispatch(
        "rotate_component",
        {
            "component": "cube-1",
            "axis": "+z",
            "angle_deg": 90,
            "absolute": True,
            "force": True,
        },
    )
    assert abs_rot.ok, abs_rot.error
    assert abs_rot.result["absolute"] is True
    custom = kernel.dispatch(
        "rotate_component",
        {
            "component": "cube-2",
            "axis": "+z",
            "angle_deg": 90,
            "pivot": [0, 0, 0],
            "force": True,
        },
    )
    assert custom.ok, custom.error
    assert custom.result["origin"] == pytest.approx([-40.0, 0.0, 0.0], abs=1e-6)


def test_pattern_component_feature_deletes_copies(kernel: Kernel):
    _build_cube(kernel)
    assert kernel.dispatch("save_document", {"path": "cube.sldprt"}).ok
    assert kernel.dispatch("new_assembly", {}).ok
    ins = kernel.dispatch("insert_component", {"path": "cube.sldprt", "x": 40})
    assert ins.ok, ins.error
    pat = kernel.dispatch(
        "pattern_component",
        {"component": ins.result["name"], "count": 4, "axis": "+z"},
    )
    assert pat.ok, pat.error
    assert pat.result["name"] == "LocalCirPattern1"
    assert pat.result["kind"] == "local_cir_pattern"
    listed = kernel.dispatch("list_components", {})
    assert listed.ok and listed.result["count"] == 4
    gone = kernel.dispatch("delete_feature", {"name": "LocalCirPattern1"})
    assert gone.ok, gone.error
    after = kernel.dispatch("list_components", {})
    assert after.ok and after.result["count"] == 1
    assert after.result["components"][0]["name"] == ins.result["name"]
    missing = kernel.dispatch("delete_feature", {"name": "LocalCirPattern1"})
    assert not missing.ok and missing.error.code == "FEATURE_NOT_FOUND"


def test_linear_pattern_component_feature(kernel: Kernel):
    _build_cube(kernel)
    assert kernel.dispatch("save_document", {"path": "cube.sldprt"}).ok
    assert kernel.dispatch("new_assembly", {}).ok
    ins = kernel.dispatch("insert_component", {"path": "cube.sldprt", "x": 40})
    assert ins.ok, ins.error
    missing = kernel.dispatch("pattern_component", {"component": ins.result["name"], "count": 4})
    assert not missing.ok and missing.error.code == "INVALID_ARGUMENT"
    mixed = kernel.dispatch(
        "pattern_component",
        {"component": ins.result["name"], "count": 4, "axis": "+z", "dx": 30},
    )
    assert not mixed.ok and mixed.error.code == "INVALID_ARGUMENT"
    pat = kernel.dispatch(
        "pattern_component",
        {"component": ins.result["name"], "count": 4, "dx": 30},
    )
    assert pat.ok, pat.error
    assert pat.result["name"] == "LocalLPattern1"
    assert pat.result["kind"] == "local_l_pattern"
    assert pat.result["count"] == 4
    xs = sorted(c["origin"][0] for c in pat.result["components"])
    assert xs == pytest.approx([40.0, 70.0, 100.0, 130.0], abs=1e-6)
    gone = kernel.dispatch("delete_feature", {"name": "LocalLPattern1"})
    assert gone.ok, gone.error
    after = kernel.dispatch("list_components", {})
    assert after.ok and after.result["count"] == 1


def test_revolve_full_pappus_volume(kernel: Kernel):
    _revolve_setup(kernel)  # Pappus area setup
    r = kernel.dispatch("revolve", {"axis": "+x"})
    assert r.ok
    assert r.result["name"] == "Revolve1" and r.result["kind"] == "revolve"
    assert r.rebuild.ok and "volume_mm3" in r.delta.changed

    mp = kernel.dispatch("get_mass_properties", {})
    expected = 200.0 * math.radians(360.0) * 10.0  # Pappus
    assert mp.result["volume"] == pytest.approx(expected, rel=1e-9)
    assert mp.state_version == 5

    geo = kernel.dispatch("get_geometry", {})
    assert geo.result["face_count"] == 3 and geo.result["edge_count"] == 2  # canned full rev
    assert geo.result["bbox"] == pytest.approx([0, -20, -20, 10, 20, 20], abs=1e-6)


def test_revolve_partial_quarter(kernel: Kernel):
    _revolve_setup(kernel)
    r = kernel.dispatch("revolve", {"axis": "+x", "angle_deg": 90})
    assert r.ok and r.result["angle_deg"] == 90

    mp = kernel.dispatch("get_mass_properties", {})
    full = 200.0 * math.radians(360.0) * 10.0
    assert mp.result["volume"] == pytest.approx(full / 4, rel=1e-9)

    geo = kernel.dispatch("get_geometry", {})
    assert geo.result["face_count"] == 6 and geo.result["edge_count"] == 8  # canned wedge


def test_revolve_profile_straddling_axis_fails(kernel: Kernel):
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {})
    kernel.dispatch("sketch_rectangle", {"x1": -10, "y1": -5, "x2": 10, "y2": 5})
    kernel.dispatch("end_sketch", {})
    r = kernel.dispatch("revolve", {"axis": "+x"})
    assert not r.ok
    assert r.error.code == "FEATURE_CREATE_FAILED"
    assert "crosses" in r.error.message and r.error.side_effect.value == "none"


def test_revolve_axis_through_centroid_fails(kernel: Kernel):
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {})
    kernel.dispatch("sketch_rectangle", {"x1": 0, "y1": -10, "x2": 20, "y2": 10})
    kernel.dispatch("end_sketch", {})
    r = kernel.dispatch("revolve", {"axis": "+x"})  # centroid radius 0
    assert not r.ok and r.error.code == "FEATURE_CREATE_FAILED"


def test_revolve_axis_enum_rejected_by_schema(kernel: Kernel):
    r = kernel.dispatch("revolve", {"axis": "w"})
    assert not r.ok and r.error.code == "INVALID_ARGUMENT"
    assert "+x" in r.error.message  # enum lists values


def test_extrude_cut_reduces_volume(kernel: Kernel):
    _build_cube(kernel, 50.0)
    r = kernel.dispatch("extrude_cut", {"depth": 5})
    # profile consumed
    assert not r.ok and r.error.code == "SKETCH_NOT_FOUND"

    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    kernel.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 10, "y2": 10})
    kernel.dispatch("end_sketch", {})
    r = kernel.dispatch("extrude_cut", {"depth": 5})
    assert r.ok and r.result["name"] == "Cut-Extrude1"
    assert r.rebuild.ok and "volume_mm3" in r.delta.changed

    mp = kernel.dispatch("get_mass_properties", {})
    assert mp.result["volume"] == pytest.approx(125000.0 - 500.0, rel=1e-9)
    geo = kernel.dispatch("get_geometry", {})
    assert geo.result["face_count"] == 8  # 6 + pocket faces
    feats = kernel.dispatch("list_features", {})
    assert [f["name"] for f in feats.result["features"]] == ["Boss-Extrude1", "Cut-Extrude1"]


def test_extrude_cut_requires_material(kernel: Kernel):
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {})
    kernel.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 10, "y2": 10})
    kernel.dispatch("end_sketch", {})
    r = kernel.dispatch("extrude_cut", {"depth": 5})
    assert not r.ok and r.error.code == "FEATURE_CREATE_FAILED"
    assert "extrude" in r.error.hint
    assert r.state_version == 4  # failed mutating no bump


def test_extrude_midplane_symmetric(kernel: Kernel):
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    kernel.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 10, "y2": 10})
    kernel.dispatch("end_sketch", {})
    r = kernel.dispatch("extrude", {"depth": 20, "direction": "midplane"})
    assert r.ok and r.result["direction"] == "midplane"
    geo = kernel.dispatch("get_geometry", {})
    assert geo.result["bbox"] == pytest.approx([0, 0, -10, 10, 10, 10], abs=1e-6)
    mp = kernel.dispatch("get_mass_properties", {})
    assert mp.result["volume"] == pytest.approx(2000.0, rel=1e-9)
    assert mp.result["center_of_mass"][2] == pytest.approx(0.0, abs=1e-9)


def test_extrude_both_directions(kernel: Kernel):
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    kernel.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 10, "y2": 10})
    kernel.dispatch("end_sketch", {})
    r = kernel.dispatch("extrude", {"depth": 10, "direction": "both", "depth2": 30})
    assert r.ok and r.result["depth2"] == 30
    geo = kernel.dispatch("get_geometry", {})
    assert geo.result["bbox"] == pytest.approx([0, 0, -30, 10, 10, 10], abs=1e-6)
    mp = kernel.dispatch("get_mass_properties", {})
    assert mp.result["volume"] == pytest.approx(4000.0, rel=1e-9)


def test_extrude_thin_wall(kernel: Kernel):
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    kernel.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 40, "y2": 20})
    kernel.dispatch("end_sketch", {})
    missing = kernel.dispatch("extrude", {"depth": 10, "thin": True})
    assert not missing.ok and missing.error.code == "INVALID_ARGUMENT"
    zero = kernel.dispatch("extrude", {"depth": 10, "thin": True, "thickness": 0})
    assert not zero.ok and zero.error.code == "INVALID_ARGUMENT"
    r = kernel.dispatch("extrude", {"depth": 10, "thin": True, "thickness": 2})
    assert r.ok, r.error
    assert r.result["thin"] is True and r.result["thickness"] == 2
    mp = kernel.dispatch("get_mass_properties", {})
    assert mp.result["volume"] == pytest.approx(2240.0, rel=1e-6)
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    kernel.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 10, "y2": 10})
    kernel.dispatch("end_sketch", {})
    mixed = kernel.dispatch(
        "extrude",
        {"depth": 10, "thin": True, "thickness": 2, "direction": "up_to_surface", "end_face": 0},
    )
    assert not mixed.ok and mixed.error.code == "INVALID_ARGUMENT"


def test_extrude_both_requires_depth2(kernel: Kernel):
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    kernel.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 10, "y2": 10})
    kernel.dispatch("end_sketch", {})
    r = kernel.dispatch("extrude", {"depth": 10, "direction": "both"})
    assert not r.ok and r.error.code == "INVALID_ARGUMENT"


def test_extrude_reverse_bbox(kernel: Kernel):
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    kernel.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 10, "y2": 10})
    kernel.dispatch("end_sketch", {})
    r = kernel.dispatch("extrude", {"depth": 20, "reverse": True})
    assert r.ok and r.result.get("reverse") is True
    geo = kernel.dispatch("get_geometry", {})
    assert geo.result["bbox"] == pytest.approx([0, 0, -20, 10, 10, 0], abs=1e-6)


def test_circular_hole_cut_on_front_boss(kernel: Kernel):
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    kernel.dispatch("sketch_rectangle", {"x1": -20, "y1": -20, "x2": 20, "y2": 20})
    kernel.dispatch("end_sketch", {})
    assert kernel.dispatch("extrude", {"depth": 20}).ok
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    assert kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 5}).ok
    kernel.dispatch("end_sketch", {})
    r = kernel.dispatch("extrude_cut", {"depth": 30})
    assert r.ok, r.error
    mp = kernel.dispatch("get_mass_properties", {})
    # fake cut volume
    boss = 40.0 * 40.0 * 20.0
    hole = math.pi * 5.0 * 5.0 * 30.0
    assert mp.result["volume"] == pytest.approx(boss - hole, rel=1e-9)


def test_revolve_backend_call_recorded(fake, kernel: Kernel):
    _revolve_setup(kernel)
    kernel.dispatch("revolve", {"axis": "+z", "angle_deg": 180})
    assert "revolve_blind" in fake.call_names()
    entry = fake.calls_named("revolve_blind")[-1]
    assert entry["axis"] == "+z" and entry["angle"] == pytest.approx(math.pi, rel=1e-12)


# ---------- Feature batch 2: fillet/chamfer (W6) ----------


def test_fillet_all_edges_on_cube(kernel: Kernel):
    _build_cube(kernel, 50.0)
    r = kernel.dispatch("fillet", {"radius": 2})
    assert r.ok and r.result["name"] == "Fillet1"
    assert r.rebuild.ok and "volume_mm3" in r.delta.changed

    mp = kernel.dispatch("get_mass_properties", {})
    l_eff = 4.0 * (50 + 50 + 50)  # prism edge length
    expected = 125000.0 - (1.0 - math.pi / 4) * 2.0**2 * l_eff
    assert mp.result["volume"] == pytest.approx(expected, rel=1e-9)

    geo = kernel.dispatch("get_geometry", {})
    assert geo.result["face_count"] == 6 + 12  # fillet faces per edge
    assert geo.result["edge_count"] == 24


def test_chamfer_with_target_feature(kernel: Kernel):
    _revolve_setup(kernel)  # Revolve1 bbox
    assert kernel.dispatch("revolve", {"axis": "+x"}).ok
    r = kernel.dispatch("chamfer", {"distance": 1, "target": "Revolve1"})
    assert r.ok and r.result["name"] == "Chamfer1" and r.result["distance"] == 1

    mp = kernel.dispatch("get_mass_properties", {})
    full = 200.0 * math.radians(360.0) * 10.0
    expected = full - 0.5 * 1.0 * (4.0 * (10 + 40 + 40))
    assert mp.result["volume"] == pytest.approx(expected, rel=1e-9)


def test_chamfer_angle_scales_volume(kernel: Kernel):
    _build_cube(kernel, 50.0)
    r = kernel.dispatch("chamfer", {"distance": 1, "angle_deg": 30})
    assert r.ok
    mp = kernel.dispatch("get_mass_properties", {})
    l_eff = 4.0 * (50 + 50 + 50)
    k = 0.5 * math.tan(math.radians(30))
    assert mp.result["volume"] == pytest.approx(125000.0 - k * 1.0**2 * l_eff, rel=1e-9)


def test_chamfer_by_edge_indexes(kernel: Kernel):
    _build_cube(kernel)
    edges = kernel.dispatch("get_edges", {})
    assert edges.ok
    idx = edges.result["edges"][0]["index"]
    r = kernel.dispatch("chamfer", {"distance": 1, "edges": [idx]})
    assert r.ok and r.result["kind"] == "chamfer" and r.result["angle_deg"] == 45.0
    angled = kernel.dispatch("chamfer", {"distance": 1, "edges": [idx], "angle_deg": 30})
    assert angled.ok and angled.result["angle_deg"] == 30
    zero = kernel.dispatch("chamfer", {"distance": 1, "angle_deg": 0})
    assert not zero.ok and zero.error.code == "INVALID_ARGUMENT"
    right = kernel.dispatch("chamfer", {"distance": 1, "angle_deg": 90})
    assert not right.ok and right.error.code == "INVALID_ARGUMENT"
    bad = kernel.dispatch("chamfer", {"distance": 1, "edges": [999]})
    assert not bad.ok and bad.error.code == "INVALID_ARGUMENT"


def test_fillet_target_not_found(kernel: Kernel):
    _build_cube(kernel)
    r = kernel.dispatch("fillet", {"radius": 1, "target": "Nope"})
    assert not r.ok and r.error.code == "FEATURE_NOT_FOUND"
    assert "list_features" in r.error.hint


def test_fillet_by_edge_indexes(kernel: Kernel):
    _build_cube(kernel, 50.0)
    edges = kernel.dispatch("get_edges", {})
    assert edges.ok
    idx = edges.result["edges"][0]["index"]
    r = kernel.dispatch("fillet", {"radius": 2, "edges": [idx]})
    assert r.ok and r.result["kind"] == "fillet"
    mp = kernel.dispatch("get_mass_properties", {})
    expected = 125000.0 - (1.0 - math.pi / 4) * 2.0**2 * 50.0
    assert mp.result["volume"] == pytest.approx(expected, rel=1e-9)
    geo = kernel.dispatch("get_geometry", {})
    assert geo.result["face_count"] == 6 + 1
    bad = kernel.dispatch("fillet", {"radius": 2, "edges": [999]})
    assert not bad.ok and bad.error.code == "INVALID_ARGUMENT"


def test_fillet_radius_too_large(kernel: Kernel):
    _build_cube(kernel)
    r = kernel.dispatch("fillet", {"radius": 25})  # ≥ half min extent
    assert not r.ok and r.error.code == "FEATURE_CREATE_FAILED"
    assert "extent" in r.error.message


def test_detail_features_require_material_and_positive(kernel: Kernel):
    kernel.dispatch("new_part", {})
    r = kernel.dispatch("fillet", {"radius": 1})
    assert not r.ok and r.error.code == "FEATURE_CREATE_FAILED"
    assert r.state_version == 1  # no increment on failure
    r2 = kernel.dispatch("chamfer", {"distance": -1})
    assert not r2.ok and r2.error.code == "INVALID_ARGUMENT"  # schema exclusiveMinimum


# ---------- Feature batch 3: shell and patterns (W6) ----------


def test_shell_hollows_cube(kernel: Kernel):
    _build_cube(kernel, 50.0)
    r = kernel.dispatch("shell", {"thickness": 2})
    assert r.ok and r.result["name"] == "Shell1"
    assert r.rebuild.ok and "volume_mm3" in r.delta.changed

    mp = kernel.dispatch("get_mass_properties", {})
    expected = 125000.0 - 46.0**3  # shell cavity
    assert mp.result["volume"] == pytest.approx(expected, rel=1e-9)

    geo = kernel.dispatch("get_geometry", {})
    assert geo.result["face_count"] == 12 and geo.result["edge_count"] == 24
    assert geo.result["bbox"] == pytest.approx([0, 0, 0, 50, 50, 50], abs=1e-6)  # bbox unchanged


def test_shell_open_face_volume(kernel: Kernel):
    _build_cube(kernel, 50.0)
    faces = kernel.dispatch("get_faces", {})
    assert faces.ok
    top = max(faces.result["faces"], key=lambda f: f["centroid"][2])
    r = kernel.dispatch("shell", {"thickness": 2, "faces": [top["index"]]})
    assert r.ok
    mp = kernel.dispatch("get_mass_properties", {})
    expected = 125000.0 - (46.0**2 * 48.0)
    assert mp.result["volume"] == pytest.approx(expected, rel=1e-9)
    geo = kernel.dispatch("get_geometry", {})
    assert geo.result["face_count"] == 11
    bad = kernel.dispatch("shell", {"thickness": 2, "faces": [99]})
    assert not bad.ok and bad.error.code == "INVALID_ARGUMENT"


def test_shell_thickness_too_large(kernel: Kernel):
    _build_cube(kernel, 50.0)
    r = kernel.dispatch("shell", {"thickness": 25})  # ≥ half extent
    assert not r.ok and r.error.code == "FEATURE_CREATE_FAILED"


# def test_linear_pattern_copies_feature(kernel: Kernel):
#     _build_cube(kernel, 50.0)
#     r = kernel.dispatch("linear_pattern", {"feature": "Boss-Extrude1", "count": 3, "dx": 60})
#     assert r.ok and r.result["name"] == "LPattern1" and r.result["count"] == 3

#     mp = kernel.dispatch("get_mass_properties", {})
#     assert mp.result["volume"] == pytest.approx(3 * 125000.0, rel=1e-9)
#     assert mp.result["center_of_mass"] == pytest.approx([85.0, 25.0, 25.0], abs=1e-6)

#     geo = kernel.dispatch("get_geometry", {})
#     assert geo.result["bbox"] == pytest.approx([0, 0, 0, 170, 50, 50], abs=1e-6)
#     assert geo.result["face_count"] == 18

def test_linear_pattern_copies_feature(kernel: Kernel):
    _build_cube(kernel, 50.0)
    r = kernel.dispatch("linear_pattern", {"feature": "Boss-Extrude1", "count": 3, "dx": 40})
    assert r.ok and r.result["name"] == "LPattern1" and r.result["count"] == 3

    mp = kernel.dispatch("get_mass_properties", {})
    assert mp.result["volume"] == pytest.approx(3 * 125000.0, rel=1e-9)
    assert mp.result["center_of_mass"] == pytest.approx([65.0, 25.0, 25.0], abs=1e-6)

    geo = kernel.dispatch("get_geometry", {})
    assert geo.result["bbox"] == pytest.approx([0, 0, 0, 130, 50, 50], abs=1e-6)
    assert geo.result["face_count"] == 6  # merged instances (real SW)

def test_linear_pattern_zero_direction_rejected(kernel: Kernel):
    _build_cube(kernel, 50.0)
    r = kernel.dispatch("linear_pattern", {"feature": "Boss-Extrude1", "count": 3})
    assert not r.ok and r.error.code == "INVALID_ARGUMENT"
    r2 = kernel.dispatch(
        "linear_pattern", {"feature": "Boss-Extrude1", "count": 1, "dx": 10}
    )
    assert not r2.ok and r2.error.code == "INVALID_ARGUMENT"  # schema minimum 2


def test_circular_pattern_copies_around_z(kernel: Kernel):
    assert kernel.dispatch("new_part", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch(
        "sketch_rectangle", {"x1": 30, "y1": -5, "x2": 40, "y2": 5}
    ).ok
    assert kernel.dispatch("end_sketch", {}).ok
    boss = kernel.dispatch("extrude", {"depth": 10})
    assert boss.ok
    r = kernel.dispatch(
        "circular_pattern", {"feature": boss.result["name"], "count": 4, "axis": "+z"}
    )
    assert r.ok and r.result["count"] == 4 and r.result["axis"] == "+z"
    mp = kernel.dispatch("get_mass_properties", {})
    assert mp.result["volume"] == pytest.approx(4 * 1000.0, rel=1e-9)
    bad = kernel.dispatch(
        "circular_pattern", {"feature": boss.result["name"], "count": 4, "axis": "+q"}
    )
    assert not bad.ok and bad.error.code == "INVALID_ARGUMENT"


def test_circular_pattern_holes_around_z(kernel: Kernel):
    assert kernel.dispatch("new_part", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch(
        "sketch_rectangle", {"x1": -50, "y1": -50, "x2": 50, "y2": 50}
    ).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("extrude", {"depth": 10}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch("sketch_circle", {"cx": 30, "cy": 0, "r": 5}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    cut = kernel.dispatch("extrude_cut", {"depth": 10})
    assert cut.ok
    r = kernel.dispatch(
        "circular_pattern", {"feature": cut.result["name"], "count": 4, "axis": "+z"}
    )
    assert r.ok
    hole = math.pi * 5.0 * 5.0 * 10.0
    mp = kernel.dispatch("get_mass_properties", {})
    assert mp.result["volume"] == pytest.approx(100000.0 - 4 * hole, rel=1e-9)
    geo = kernel.dispatch("get_geometry", {})
    assert geo.result["bbox"] == pytest.approx([-50, -50, 0, 50, 50, 10], abs=1e-6)


def test_linear_pattern_feature_not_found(kernel: Kernel):
    _build_cube(kernel, 50.0)
    r = kernel.dispatch("linear_pattern", {"feature": "Nope", "count": 2, "dx": 10})
    assert not r.ok and r.error.code == "FEATURE_NOT_FOUND"
    assert "list_features" in r.error.hint


# ---------- W7: selection tools (dual-handle + GUI pick) ----------


def test_get_entities_handles_for_cube(kernel: Kernel):
    _build_cube(kernel, 50.0)
    r = kernel.dispatch("get_entities", {})
    assert r.ok and r.result["length_unit"] == "mm"
    faces, edges = r.result["faces"], r.result["edges"]
    assert [f["index"] for f in faces] == [0, 1, 2, 3, 4, 5]
    assert faces[0]["centroid"] == pytest.approx([25, 25, 0])  # bottom
    assert faces[1]["centroid"] == pytest.approx([25, 25, 50])  # top
    assert len(edges) == 12
    assert edges[0]["midpoint"] == pytest.approx([0, 0, 25])  # vertical edge
    assert all(f["kind"] == "plane" for f in faces)
    assert all(e["kind"] == "line" for e in edges)


def test_get_entities_pagination_is_opt_in(kernel: Kernel):
    _build_cube(kernel, 50.0)
    full = kernel.dispatch("get_entities", {})
    assert "total" not in full.result and "offset" not in full.result
    page = kernel.dispatch("get_entities", {"limit": 2, "offset": 1})
    assert page.ok
    assert [f["index"] for f in page.result["faces"]] == [1, 2]
    assert len(page.result["edges"]) == 2
    assert page.result["total"] == {"faces": 6, "edges": 12}
    assert page.result["offset"] == 1


def test_select_face_resolves_coordinate_handle(kernel: Kernel):
    _build_cube(kernel, 50.0)
    exact = kernel.dispatch("select_face", {"index": 0, "x": 25, "y": 25, "z": 0})
    assert exact.ok and exact.result["quality"] == "exact"
    stale = kernel.dispatch("select_face", {"index": 99, "x": 25, "y": 25, "z": 50})
    assert stale.ok and stale.result["quality"] == "proximity" and stale.result["selected_face"] == 1
    miss = kernel.dispatch("select_face", {"index": 0, "x": 200, "y": 200, "z": 200})
    assert not miss.ok and miss.error.code == "REF_NOT_FOUND"
    partial = kernel.dispatch("select_face", {"index": 0, "x": 25})
    assert not partial.ok and partial.error.code == "INVALID_ARGUMENT"


def test_after_geometry_change_requery_face_handles(kernel: Kernel):
    """After geometry change, re-resolve via query/coords, not bare index."""
    _build_cube(kernel, 50.0)
    before = kernel.dispatch("get_faces", {"kind": "plane", "query": "max_z"})
    assert before.ok and len(before.result["faces"]) == 1
    top = before.result["faces"][0]
    remembered = top["index"]
    cx, cy, cz = top["centroid"]

    assert kernel.dispatch("fillet", {"radius": 2}).ok
    geo = kernel.dispatch("get_geometry", {})
    assert geo.result["face_count"] > 6  # topology changed (canned face count)

    # semantic query finds top without old index
    after = kernel.dispatch("get_faces", {"kind": "plane", "query": "max_z"})
    assert after.ok and len(after.result["faces"]) == 1
    fresh = after.result["faces"][0]
    assert fresh["centroid"] == pytest.approx([cx, cy, cz], abs=1e-6)

    # dual-handle: stale index + coords → current top
    resolved = kernel.dispatch(
        "select_face",
        {"index": remembered + 50, "x": cx, "y": cy, "z": cz},
    )
    assert resolved.ok
    assert resolved.result["quality"] in {"exact", "proximity"}
    assert resolved.result["selected_face"] == fresh["index"]

    # stale index + wrong coords → reject
    stale_wrong = kernel.dispatch(
        "select_face",
        {"index": remembered, "x": 200, "y": 200, "z": 200},
    )
    assert not stale_wrong.ok and stale_wrong.error.code == "REF_NOT_FOUND"


def test_get_entities_empty_part_has_no_entities(kernel: Kernel):
    kernel.dispatch("new_part", {})
    r = kernel.dispatch("get_entities", {})
    assert r.ok and r.result["faces"] == [] and r.result["edges"] == []


def test_loft_two_circles_frustum_volume(kernel: Kernel):
    assert kernel.dispatch("new_part", {}).ok
    plane = kernel.dispatch("create_plane", {"reference": "Front Plane", "offset": 40})
    assert plane.ok, plane.error
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 10}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": plane.result["name"]}).ok
    assert kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 5}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    too_few = kernel.dispatch("loft", {"profiles": ["Sketch1"]})
    assert not too_few.ok and too_few.error.code == "INVALID_ARGUMENT"
    feat = kernel.dispatch("loft", {})
    assert feat.ok, feat.error
    assert feat.result["kind"] == "loft"
    mp = kernel.dispatch("get_mass_properties", {})
    assert mp.ok
    r0, r1, h = 10.0, 5.0, 40.0
    expect = math.pi * h / 3.0 * (r0 * r0 + r0 * r1 + r1 * r1)
    assert mp.result["volume"] == pytest.approx(expect, rel=1e-9)
    geo = kernel.dispatch("get_geometry", {})
    assert geo.result["face_count"] == 3 and geo.result["edge_count"] == 2
    listed = kernel.dispatch("list_features", {})
    assert any(f["kind"] == "loft" for f in listed.result["features"])
    kernel.dispatch("new_part", {})
    empty = kernel.dispatch("loft", {})
    assert not empty.ok and empty.error.code == "INVALID_ARGUMENT"


def test_loft_guides_open_curve(kernel: Kernel):
    assert kernel.dispatch("new_part", {}).ok
    plane = kernel.dispatch("create_plane", {"reference": "Front Plane", "offset": 40})
    assert plane.ok, plane.error
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 10}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": plane.result["name"]}).ok
    assert kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 5}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Top Plane"}).ok
    assert kernel.dispatch("sketch_line", {"x1": 10, "y1": 0, "x2": 5, "y2": 40}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    missing = kernel.dispatch("loft", {"profiles": ["Sketch1", "Sketch2"], "guides": ["NoSuch"]})
    assert not missing.ok and missing.error.code == "SKETCH_NOT_FOUND"
    as_profile = kernel.dispatch("loft", {"profiles": ["Sketch1", "Sketch2"], "guides": ["Sketch1"]})
    assert not as_profile.ok and as_profile.error.code == "FEATURE_CREATE_FAILED"
    feat = kernel.dispatch("loft", {"profiles": ["Sketch1", "Sketch2"], "guides": ["Sketch3"]})
    assert feat.ok, feat.error
    assert feat.result["guides"] == ["Sketch3"]
    mp = kernel.dispatch("get_mass_properties", {})
    r0, r1, h = 10.0, 5.0, 40.0
    expect = math.pi * h / 3.0 * (r0 * r0 + r0 * r1 + r1 * r1)
    assert mp.result["volume"] == pytest.approx(expect, rel=1e-9)


def test_loft_centerline_open_curve(kernel: Kernel):
    assert kernel.dispatch("new_part", {}).ok
    plane = kernel.dispatch("create_plane", {"reference": "Front Plane", "offset": 40})
    assert plane.ok, plane.error
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 10}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": plane.result["name"]}).ok
    assert kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 6}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "3D"}).ok
    arc = kernel.dispatch(
        "sketch_arc",
        {"x1": 0, "y1": 0, "x2": 5, "y2": 0, "x3": 0, "y3": 0, "z2": 20, "z3": 40},
    )
    assert arc.ok, arc.error
    assert kernel.dispatch("end_sketch", {}).ok
    missing = kernel.dispatch(
        "loft", {"profiles": ["Sketch1", "Sketch2"], "centerline": "NoSuch"},
    )
    assert not missing.ok and missing.error.code == "SKETCH_NOT_FOUND"
    both = kernel.dispatch(
        "loft",
        {"profiles": ["Sketch1", "Sketch2"], "guides": ["Sketch3"], "centerline": "Sketch3"},
    )
    assert not both.ok and both.error.code == "INVALID_ARGUMENT"
    as_profile = kernel.dispatch(
        "loft", {"profiles": ["Sketch1", "Sketch2"], "centerline": "Sketch1"},
    )
    assert not as_profile.ok and as_profile.error.code == "FEATURE_CREATE_FAILED"
    feat = kernel.dispatch(
        "loft", {"profiles": ["Sketch1", "Sketch2"], "centerline": "Sketch3"},
    )
    assert feat.ok, feat.error
    assert feat.result["kind"] == "loft"
    assert feat.result["centerline"] == "Sketch3"
    mp = kernel.dispatch("get_mass_properties", {})
    r0, r1, h = 10.0, 6.0, 40.0
    expect = math.pi * h / 3.0 * (r0 * r0 + r0 * r1 + r1 * r1)
    assert mp.result["volume"] == pytest.approx(expect, rel=1e-9)


def test_loft_centerline_rejects_closed_circle(kernel: Kernel):
    assert kernel.dispatch("new_part", {}).ok
    assert kernel.dispatch("create_plane", {"reference": "Front Plane", "offset": 40}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 10}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Plane1"}).ok
    assert kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 6}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Top Plane"}).ok
    assert kernel.dispatch("sketch_circle", {"cx": 0, "cy": 20, "r": 5}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    closed = kernel.dispatch(
        "loft", {"profiles": ["Sketch1", "Sketch2"], "centerline": "Sketch3"},
    )
    assert not closed.ok and closed.error.code == "FEATURE_CREATE_FAILED"


def test_surface_thicken_closed_contour(kernel: Kernel):
    assert kernel.dispatch("new_part", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 20, "y2": 10}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    surf = kernel.dispatch("extrude_surface", {"depth": 10})
    assert surf.ok, surf.error
    assert surf.result["kind"] == "extrude_surface"
    empty = kernel.dispatch("thicken", {"thickness": 0})
    assert not empty.ok and empty.error.code == "INVALID_ARGUMENT"
    th = kernel.dispatch("thicken", {"thickness": 2})
    assert th.ok, th.error
    assert th.result["kind"] == "thicken"
    mp = kernel.dispatch("get_mass_properties", {})
    assert mp.result["volume"] == pytest.approx(2000.0, rel=1e-9)
    listed = kernel.dispatch("list_features", {})
    kinds = {f["kind"] for f in listed.result["features"]}
    assert "extrude_surface" in kinds and "thicken" in kinds
    kernel.dispatch("new_part", {})
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 10, "y2": 10}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("extrude_surface", {"depth": 10}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch("sketch_rectangle", {"x1": 10, "y1": 0, "x2": 20, "y2": 10}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("extrude_surface", {"depth": 10}).ok
    missing = kernel.dispatch("knit", {"surfaces": ["NoSuch"]})
    assert not missing.ok and missing.error.code == "FEATURE_NOT_FOUND"
    kn = kernel.dispatch("knit", {})
    assert kn.ok, kn.error
    assert kn.result["kind"] == "knit"
    open_th = kernel.dispatch("thicken", {"thickness": 2})
    assert not open_th.ok and open_th.error.code == "FEATURE_CREATE_FAILED"
    kernel.dispatch("new_part", {})
    none = kernel.dispatch("thicken", {"thickness": 2})
    assert not none.ok and none.error.code == "FEATURE_CREATE_FAILED"


def test_trim_surface(kernel: Kernel):
    assert kernel.dispatch("new_part", {}).ok
    empty = kernel.dispatch("trim_surface", {})
    assert not empty.ok and empty.error.code == "FEATURE_CREATE_FAILED"
    assert kernel.dispatch("start_sketch", {"plane": "Right Plane"}).ok
    assert kernel.dispatch("sketch_line", {"x1": -40, "y1": -20, "x2": 40, "y2": 20}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("extrude_surface", {"depth": 60}).ok
    alone = kernel.dispatch("trim_surface", {})
    assert not alone.ok and alone.error.code == "FEATURE_CREATE_FAILED"
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch("sketch_line", {"x1": -30, "y1": 30, "x2": 30, "y2": -50}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("extrude_surface", {"depth": 80}).ok
    missing = kernel.dispatch("trim_surface", {"tool": "NoSuch"})
    assert not missing.ok and missing.error.code == "FEATURE_NOT_FOUND"
    bad_keep = kernel.dispatch("trim_surface", {"keep": 9})
    assert not bad_keep.ok and bad_keep.error.code == "INVALID_ARGUMENT"
    trimmed = kernel.dispatch("trim_surface", {})
    assert trimmed.ok, trimmed.error
    assert trimmed.result["kind"] == "trim_surface"
    kinds = {f["kind"] for f in kernel.dispatch("list_features", {}).result["features"]}
    assert "trim_surface" in kinds


def test_extend_surface(kernel: Kernel):
    assert kernel.dispatch("new_part", {}).ok
    empty = kernel.dispatch("extend_surface", {"distance": 5})
    assert not empty.ok and empty.error.code == "FEATURE_CREATE_FAILED"
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 10}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("extrude_surface", {"depth": 20}).ok
    missing = kernel.dispatch("extend_surface", {"distance": 5, "surface": "NoSuch"})
    assert not missing.ok and missing.error.code == "FEATURE_NOT_FOUND"
    bad_dist = kernel.dispatch("extend_surface", {"distance": 0})
    assert not bad_dist.ok and bad_dist.error.code == "INVALID_ARGUMENT"
    bad_edge = kernel.dispatch("extend_surface", {"distance": 5, "edge": 9})
    assert not bad_edge.ok and bad_edge.error.code == "INVALID_ARGUMENT"
    extended = kernel.dispatch("extend_surface", {"distance": 5})
    assert extended.ok, extended.error
    assert extended.result["kind"] == "extend_surface"
    kinds = {f["kind"] for f in kernel.dispatch("list_features", {}).result["features"]}
    assert "extend_surface" in kinds


def test_fillet_surface(kernel: Kernel):
    assert kernel.dispatch("new_part", {}).ok
    empty = kernel.dispatch("fillet_surface", {"radius": 2})
    assert not empty.ok and empty.error.code == "FEATURE_CREATE_FAILED"
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 10}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("extrude_surface", {"depth": 20}).ok
    missing = kernel.dispatch("fillet_surface", {"radius": 2, "surface": "NoSuch"})
    assert not missing.ok and missing.error.code == "FEATURE_NOT_FOUND"
    bad_r = kernel.dispatch("fillet_surface", {"radius": 0})
    assert not bad_r.ok and bad_r.error.code == "INVALID_ARGUMENT"
    bad_edge = kernel.dispatch("fillet_surface", {"radius": 2, "edge": 9})
    assert not bad_edge.ok and bad_edge.error.code == "INVALID_ARGUMENT"
    filleted = kernel.dispatch("fillet_surface", {"radius": 2})
    assert filleted.ok, filleted.error
    assert filleted.result["kind"] == "fillet_surface"
    kinds = {f["kind"] for f in kernel.dispatch("list_features", {}).result["features"]}
    # COM kind Fillet; fake records fillet_surface
    assert "fillet_surface" in kinds or "fillet" in kinds


def test_untrim_surface(kernel: Kernel):
    assert kernel.dispatch("new_part", {}).ok
    empty = kernel.dispatch("untrim_surface", {})
    assert not empty.ok and empty.error.code == "FEATURE_CREATE_FAILED"
    assert kernel.dispatch("start_sketch", {"plane": "Right Plane"}).ok
    assert kernel.dispatch("sketch_line", {"x1": -40, "y1": -20, "x2": 40, "y2": 20}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("extrude_surface", {"depth": 60}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch("sketch_line", {"x1": -30, "y1": 30, "x2": 30, "y2": -50}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("extrude_surface", {"depth": 80}).ok
    assert kernel.dispatch("trim_surface", {}).ok
    missing = kernel.dispatch("untrim_surface", {"surface": "NoSuch"})
    assert not missing.ok and missing.error.code == "FEATURE_NOT_FOUND"
    unt = kernel.dispatch("untrim_surface", {})
    assert unt.ok, unt.error
    assert unt.result["kind"] == "untrim_surface"
    kinds = {f["kind"] for f in kernel.dispatch("list_features", {}).result["features"]}
    assert "untrim_surface" in kinds


def test_fill_and_boundary_surface(kernel: Kernel):
    assert kernel.dispatch("new_part", {}).ok
    empty = kernel.dispatch("fill_surface", {})
    assert not empty.ok and empty.error.code == "FEATURE_CREATE_FAILED"
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 10}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("extrude_surface", {"depth": 20}).ok
    missing = kernel.dispatch("fill_surface", {"surface": "NoSuch"})
    assert not missing.ok and missing.error.code == "FEATURE_NOT_FOUND"
    bad_edge = kernel.dispatch("fill_surface", {"edge": 9})
    assert not bad_edge.ok and bad_edge.error.code == "INVALID_ARGUMENT"
    cap = kernel.dispatch("fill_surface", {})
    assert cap.ok, cap.error
    assert cap.result["kind"] == "fill_surface"
    kinds = {f["kind"] for f in kernel.dispatch("list_features", {}).result["features"]}
    assert "fill_surface" in kinds

    assert kernel.dispatch("new_part", {}).ok
    one = kernel.dispatch("boundary_surface", {})
    assert not one.ok and one.error.code == "INVALID_ARGUMENT"
    assert kernel.dispatch("create_plane", {"reference": "Front Plane", "offset": 30}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 10}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Plane1"}).ok
    assert kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 6}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    bound = kernel.dispatch("boundary_surface", {})
    assert bound.ok, bound.error
    assert bound.result["kind"] == "boundary_surface"


def test_loft_cut_needs_solid(kernel: Kernel):
    assert kernel.dispatch("new_part", {}).ok
    assert kernel.dispatch("create_plane", {"reference": "Front Plane", "offset": 40}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 8}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Plane1"}).ok
    assert kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 4}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    missing = kernel.dispatch("loft_cut", {})
    assert not missing.ok and missing.error.code == "FEATURE_CREATE_FAILED"


def test_get_selection_empty_without_gui_pick(fake, kernel: Kernel):
    _build_cube(kernel, 50.0)
    r = kernel.dispatch("get_selection", {})
    assert r.ok and r.result["entities"] == []


def test_get_selection_maps_gui_pick_with_quality(fake, kernel: Kernel):
    _build_cube(kernel, 50.0)
    fake.gui_selection = fake.list_faces()[:1]  # simulated GUI pick
    r = kernel.dispatch("get_selection", {})
    assert r.ok
    item = r.result["entities"][0]
    assert item["type"] == "face" and item["index"] == 0 and item["kind"] == "plane"
    assert item["quality"] == "exact"
    assert item["coords"] == pytest.approx([25, 25, 0])


def test_get_selection_stale_index_reports_proximity(fake, kernel: Kernel):
    _build_cube(kernel, 50.0)
    pool = fake.list_faces()
    # pick index stale; coords still on top face
    fake.gui_selection = [FaceRef(index=99, kind="plane", centroid_m=pool[1].centroid_m)]
    r = kernel.dispatch("get_selection", {})
    item = r.result["entities"][0]
    assert item["quality"] == "proximity"
    assert item["index"] == 1  # current pool handle


def test_get_selection_requires_document(kernel: Kernel):
    r = kernel.dispatch("get_selection", {})
    assert not r.ok and r.error.code == "NO_ACTIVE_DOCUMENT"


# ---------- W2: sketch_circle cylinder golden value ----------


def test_sketch_circle_builds_cylinder_golden(kernel: Kernel):
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    sk = kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 25})
    assert sk.ok and sk.result["entity_count"] == 1
    kernel.dispatch("end_sketch", {})
    assert kernel.dispatch("extrude", {"depth": 40}).ok

    mp = kernel.dispatch("get_mass_properties", {})
    expected = math.pi * 25.0**2 * 40.0  # πr²h ≈ 78539.816 mm³
    assert mp.result["volume"] == pytest.approx(expected, rel=1e-9)

    geo = kernel.dispatch("get_geometry", {})
    assert geo.result["face_count"] == 3 and geo.result["edge_count"] == 2  # canned cylinder


def test_sketch_circle_rejects_non_positive_radius(kernel: Kernel):
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {})
    r = kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": -1})
    assert not r.ok and r.error.code == "INVALID_ARGUMENT"  # schema exclusiveMinimum
