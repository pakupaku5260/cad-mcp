"""装配体/高级工具集（fake 后端）：走内核 dispatch 验证签名、单位换算与错误码。"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from cadmcp.backend.protocol.models import MateInfo
from cadmcp.backend.protocol.parsers import parse_mate_ref
from cadmcp.errors import CadMcpError
from cadmcp.toolsets.assembly import _mate_payload


def test_parse_mate_ref_plane_and_face():
    plane = parse_mate_ref("上视基准面@p1-1")
    assert plane.kind == "plane" and plane.plane == "Top Plane" and plane.component == "p1-1"
    nested = parse_mate_ref("Front Plane@p1-1@sub-1")
    assert nested.component == "p1-1@sub-1" and nested.plane == "Front Plane"
    titled = parse_mate_ref("Front Plane@p1-1@装配体1")
    assert titled.component == "p1-1"
    face = parse_mate_ref("Cyl-1#FACE:2")
    assert face.kind == "face" and face.component == "Cyl-1" and face.face_index == 2
    located = parse_mate_ref("Cyl-1#face:0:0.0,0.0,0.015")
    assert located.coord_m == (0.0, 0.0, 0.015)
    edge = parse_mate_ref("Cyl-1#edge:0")
    assert edge.kind == "edge" and edge.component == "Cyl-1" and edge.edge_index == 0
    cyl = parse_mate_ref("Cyl-1#cylinder:0")
    assert cyl.kind == "face" and cyl.filter_kind == "cylinder" and cyl.face_index == 0
    circ = parse_mate_ref("Cyl-1#circle:1:0,0,30")
    assert circ.kind == "edge" and circ.filter_kind == "circle" and circ.edge_index == 1
    cone = parse_mate_ref("Cone-1#cone:0")
    assert cone.kind == "face" and cone.filter_kind == "cone" and cone.face_index == 0
    try:
        parse_mate_ref("p1-1#face:-1")
        raise AssertionError("expected INVALID_ARGUMENT")
    except CadMcpError as exc:
        assert exc.code == "INVALID_ARGUMENT"
    try:
        parse_mate_ref("p1-1#edge:-1")
        raise AssertionError("expected INVALID_ARGUMENT")
    except CadMcpError as exc:
        assert exc.code == "INVALID_ARGUMENT"


def _cube(kernel) -> None:
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    kernel.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 10, "y2": 10})
    kernel.dispatch("end_sketch", {})
    r = kernel.dispatch("extrude", {"depth": 10})
    assert r.ok, r.error


#---------- 装配体 ----------


def _two_instances(kernel, workspace: Path) -> None:
    (workspace / "bolt.sldprt").write_text("", encoding="utf-8")
    assert kernel.dispatch("new_assembly", {}).ok
    first = kernel.dispatch("insert_component", {"path": "bolt.sldprt", "z": 5})
    assert first.ok and first.result["name"] == "bolt-1"
    assert first.result["unit"] == "mm"
    assert first.result["origin"] == [0.0, 0.0, 5.0]
    assert "bbox" in first.result
    second = kernel.dispatch("insert_component", {"path": "bolt.sldprt"})
    assert second.ok and second.result["name"] == "bolt-2"


def test_assembly_insert_and_plane_mates(kernel, workspace: Path):
    _two_instances(kernel, workspace)
    doc = kernel.dispatch("get_active_document", {})
    assert doc.ok and doc.result["doc_type"] == "assembly"

    pairs = {"entity1": "Top Plane@bolt-1", "entity2": "Top Plane@bolt-2"}
    for name, extra, expected in [
        ("mate", {"type": "coincident"}, "Coincident1"),
        ("mate", {"type": "distance", "distance": 2}, "Distance1"),
        ("mate", {"type": "angle", "angle_deg": 90}, "Angle1"),
        ("mate", {"type": "coincident"}, "Coincident2"),
    ]:
        r = kernel.dispatch(name, {**pairs, **extra})
        assert r.ok, (name, r.error)
        assert r.result["name"] == expected


def test_mate_accepts_localized_plane_and_full_name(kernel, workspace: Path):
    _two_instances(kernel, workspace)
    r = kernel.dispatch(
        "mate",
        {"type": "coincident", "entity1": "上视基准面@bolt-1@装配体7", "entity2": "Top Plane@bolt-2"},
    )
    assert r.ok, r.error


def test_plane_only_mates_reject_cylindrical_types(kernel, workspace: Path):
    _two_instances(kernel, workspace)
    pairs = {"entity1": "Top Plane@bolt-1", "entity2": "Top Plane@bolt-2"}
    for name, extra in [
        ("mate", {"type": "concentric"}),
        ("mate", {"type": "tangent"}),
        ("mate", {"type": "screw", "pitch": 1.5}),
    ]:
        r = kernel.dispatch(name, {**pairs, **extra})
        assert not r.ok and r.error.code == "FEATURE_CREATE_FAILED", name


def test_mate_rejects_bad_refs(kernel, workspace: Path):
    _two_instances(kernel, workspace)
    for e1, e2 in [
        ("bolt-1", "bolt-2"),  #缺基准面
        ("Face1@bolt-1", "Top Plane@bolt-2"),  #非基准面
        ("Top Plane@bolt-1", "Top Plane@bolt-1"),  #同一零部件
        ("Top Plane@bolt-1", "Top Plane@bolt-9"),  #不存在的零部件
        ("@bolt-1", "Top Plane@bolt-2"),  #空段
    ]:
        r = kernel.dispatch("mate", {"type": "coincident", "entity1": e1, "entity2": e2})
        assert not r.ok and r.error.code == "INVALID_ARGUMENT", (e1, e2)


def test_component_face_mates(kernel, workspace: Path):
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    assert kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 10}).ok
    kernel.dispatch("end_sketch", {})
    assert kernel.dispatch("extrude", {"depth": 30}).ok
    saved = kernel.dispatch("save_document", {"path": "cyl.sldprt"})
    assert saved.ok, saved.error
    kernel.dispatch("close_document", {"discard": True})
    assert kernel.dispatch("new_assembly", {}).ok
    assert kernel.dispatch("insert_component", {"path": "cyl.sldprt"}).ok
    assert kernel.dispatch("insert_component", {"path": "cyl.sldprt", "x": 50}).ok

    listed = kernel.dispatch("get_component_faces", {"component": "cyl-1"})
    assert listed.ok, listed.error
    kinds = [f["kind"] for f in listed.result["faces"]]
    assert kinds[0] == "cylinder" and kinds[1] == "plane"
    cyls = kernel.dispatch("get_component_faces", {"component": "cyl-1", "kind": "cylinder"})
    assert cyls.ok and [f["kind"] for f in cyls.result["faces"]] == ["cylinder"]
    assert cyls.result["faces"][0]["index"] == 0
    bogus = kernel.dispatch("get_component_faces", {"component": "cyl-1", "kind": "nurbs"})
    assert not bogus.ok and bogus.error.code == "INVALID_ARGUMENT"
    empty_cone = kernel.dispatch("get_component_faces", {"component": "cyl-1", "kind": "cone"})
    assert empty_cone.ok and empty_cone.result["faces"] == []
    offset = kernel.dispatch("get_component_faces", {"component": "cyl-2"})
    assert offset.ok
    assert offset.result["faces"][0]["centroid"][0] == pytest.approx(50.0)

    conc = kernel.dispatch(
        "mate",
        {"type": "concentric", "entity1": "cyl-1#cylinder:99:0,0,15", "entity2": "cyl-2#cylinder:0"},
    )
    assert conc.ok, conc.error
    far = kernel.dispatch(
        "mate",
        {"type": "concentric", "entity1": "cyl-1#face:0:200,0,0", "entity2": "cyl-2#face:0"},
    )
    assert not far.ok and far.error.code == "REF_NOT_FOUND"
    coin = kernel.dispatch(
        "mate", {"type": "coincident", "entity1": "cyl-1#face:1", "entity2": "cyl-2#face:1"}
    )
    assert coin.ok, coin.error

    missing = kernel.dispatch("get_component_faces", {"component": "cyl-9"})
    assert not missing.ok and missing.error.code == "INVALID_ARGUMENT"
    bad_idx = kernel.dispatch(
        "mate", {"type": "concentric", "entity1": "cyl-1#face:9", "entity2": "cyl-2#face:0"}
    )
    assert not bad_idx.ok and bad_idx.error.code == "INVALID_ARGUMENT"
    plane_conc = kernel.dispatch(
        "mate",
        {"type": "concentric", "entity1": "Top Plane@cyl-1", "entity2": "Top Plane@cyl-2"},
    )
    assert not plane_conc.ok and plane_conc.error.code == "FEATURE_CREATE_FAILED"
    cyl_coin = kernel.dispatch(
        "mate", {"type": "coincident", "entity1": "cyl-1#face:0", "entity2": "cyl-2#face:0"}
    )
    assert not cyl_coin.ok and cyl_coin.error.code == "FEATURE_CREATE_FAILED"
    listed_e = kernel.dispatch("get_component_edges", {"component": "cyl-1"})
    assert listed_e.ok, listed_e.error
    assert listed_e.result["edges"][0]["kind"] == "circle"
    edge_conc = kernel.dispatch(
        "mate", {"type": "concentric", "entity1": "cyl-1#edge:0", "entity2": "cyl-2#edge:0"}
    )
    assert edge_conc.ok, edge_conc.error
    edge_coin = kernel.dispatch(
        "mate", {"type": "coincident", "entity1": "cyl-1#edge:0", "entity2": "cyl-2#edge:0"}
    )
    assert edge_coin.ok, edge_coin.error
    bad_align = kernel.dispatch(
        "mate",
        {"type": "concentric", "entity1": "cyl-1#face:0", "entity2": "cyl-2#face:0", "align": "sideways"},
    )
    assert not bad_align.ok and bad_align.error.code == "INVALID_ARGUMENT"
    aligned = kernel.dispatch(
        "mate",
        {"type": "concentric", "entity1": "cyl-1#face:0", "entity2": "cyl-2#face:0", "align": "aligned"},
    )
    assert aligned.ok, aligned.error
    listed_mates = kernel.dispatch("list_mates", {})
    assert listed_mates.ok
    types = [m["mate_type"] for m in listed_mates.result["mates"]]
    assert "concentric" in types and "coincident" in types
    gone = kernel.dispatch("delete_mate", {"name": "NoSuchMate"})
    assert not gone.ok and gone.error.code == "FEATURE_NOT_FOUND"
    first = listed_mates.result["mates"][0]["name"]
    deleted = kernel.dispatch("delete_mate", {"name": first})
    assert deleted.ok, deleted.error
    after = kernel.dispatch("list_mates", {})
    assert after.ok and first not in [m["name"] for m in after.result["mates"]]


def test_check_interference_overlap_and_clear(kernel, workspace: Path):
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    kernel.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 50, "y2": 50})
    kernel.dispatch("end_sketch", {})
    assert kernel.dispatch("extrude", {"depth": 50}).ok
    assert kernel.dispatch("save_document", {"path": "cube.sldprt"}).ok
    kernel.dispatch("close_document", {"discard": True})

    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 10})
    kernel.dispatch("end_sketch", {})
    assert kernel.dispatch("extrude", {"depth": 30}).ok
    assert kernel.dispatch("save_document", {"path": "cyl.sldprt"}).ok
    kernel.dispatch("close_document", {"discard": True})

    kernel.dispatch("new_assembly", {})
    assert kernel.dispatch("insert_component", {"path": "cube.sldprt"}).ok
    assert kernel.dispatch("insert_component", {"path": "cube.sldprt", "x": 25}).ok
    hit = kernel.dispatch("check_interference", {})
    assert hit.ok, hit.error
    assert hit.result["count"] == 1
    assert hit.result["pairs"][0]["status"] == "interfere"
    assert {hit.result["pairs"][0]["a"], hit.result["pairs"][0]["b"]} == {"cube-1", "cube-2"}
    missing = kernel.dispatch("check_interference", {"component1": "cube-1", "component2": "cube-9"})
    assert not missing.ok and missing.error.code == "INVALID_ARGUMENT"
    kernel.dispatch("close_document", {"discard": True})

    kernel.dispatch("new_assembly", {})
    assert kernel.dispatch("insert_component", {"path": "cyl.sldprt"}).ok
    assert kernel.dispatch("insert_component", {"path": "cyl.sldprt", "x": 50}).ok
    clear = kernel.dispatch("check_interference", {})
    assert clear.ok and clear.result["count"] == 0 and clear.result["pairs"] == []
    kernel.dispatch("close_document", {"discard": True})

    kernel.dispatch("new_assembly", {})
    assert kernel.dispatch("insert_component", {"path": "cube.sldprt"}).ok
    assert kernel.dispatch("insert_component", {"path": "cube.sldprt", "x": 50}).ok
    touch = kernel.dispatch("check_interference", {})
    assert touch.ok and touch.result["count"] == 1
    assert touch.result["pairs"][0]["status"] == "contact"
    as_int = kernel.dispatch("check_interference", {"coincident_as_interference": True})
    assert as_int.ok and as_int.result["pairs"][0]["status"] == "interfere"


def test_cone_face_filter(kernel, workspace: Path):
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    kernel.dispatch("sketch_line", {"x1": 10, "y1": 0, "x2": 20, "y2": 0})
    kernel.dispatch("sketch_line", {"x1": 20, "y1": 0, "x2": 10, "y2": 20})
    kernel.dispatch("sketch_line", {"x1": 10, "y1": 20, "x2": 10, "y2": 0})
    kernel.dispatch("end_sketch", {})
    assert kernel.dispatch("revolve", {"axis": "+y"}).ok
    faces = kernel.dispatch("get_faces", {})
    assert faces.ok and "cone" in [f["kind"] for f in faces.result["faces"]]
    assert kernel.dispatch("save_document", {"path": "cone.sldprt"}).ok
    kernel.dispatch("close_document", {"discard": True})
    kernel.dispatch("new_assembly", {})
    assert kernel.dispatch("insert_component", {"path": "cone.sldprt"}).ok
    listed = kernel.dispatch("get_component_faces", {"component": "cone-1", "kind": "cone"})
    assert listed.ok and listed.result["faces"]
    assert listed.result["faces"][0]["kind"] == "cone"
    assert listed.result["faces"][0]["index"] == 0
    bad = kernel.dispatch(
        "mate",
        {"type": "concentric", "entity1": "cone-1#cone:99", "entity2": "cone-1#cone:0"},
    )
    assert not bad.ok and bad.error.code == "INVALID_ARGUMENT"


def test_assembly_ops_require_assembly_document(kernel, workspace: Path):
    _cube(kernel)
    (workspace / "bolt.sldprt").write_text("", encoding="utf-8")
    ins = kernel.dispatch("insert_component", {"path": "bolt.sldprt"})
    assert not ins.ok and ins.error.code == "INVALID_ARGUMENT"
    mate = kernel.dispatch(
        "mate", {"type": "coincident", "entity1": "Top Plane@a-1", "entity2": "Top Plane@b-1"}
    )
    assert not mate.ok and mate.error.code == "INVALID_ARGUMENT"
    inter = kernel.dispatch("check_interference", {})
    assert not inter.ok and inter.error.code == "INVALID_ARGUMENT"


def test_insert_component_rejects_missing_and_outside(kernel, workspace: Path):
    kernel.dispatch("new_assembly", {})
    missing = kernel.dispatch("insert_component", {"path": "nope.sldprt"})
    assert not missing.ok and missing.error.code == "PATH_NOT_FOUND"
    denied = kernel.dispatch("insert_component", {"path": str(workspace.parent / "x.sldprt")})
    assert not denied.ok and denied.error.code == "PATH_OUTSIDE_SANDBOX"


def test_mate_payload_keeps_overdefined_as_success_warning():
    clean = _mate_payload(MateInfo(name="同心1", mate_type="concentric"))
    assert clean == {"name": "同心1", "mate_type": "concentric"}
    warned = _mate_payload(MateInfo(name="距离2", mate_type="distance", sw_error=5))
    assert warned["mate_status"] == 5 and "warning" in warned


def test_circumscribed_hex_across_flats_geometry(kernel):
    assert kernel.dispatch("new_part", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    poly = kernel.dispatch(
        "sketch_polygon", {"sides": 6, "radius": 8, "polygon_type": "circumscribed"}
    )
    assert poly.ok, poly.error
    sides = poly.result["sides"]
    assert len(sides) == 6
    a, b = sides[0], sides[3]
    amx = (a["x0"] + a["x1"]) / 2
    amy = (a["y0"] + a["y1"]) / 2
    bmx = (b["x0"] + b["x1"]) / 2
    bmy = (b["y0"] + b["y1"]) / 2
    assert (bmx - amx) ** 2 + (bmy - amy) ** 2 == pytest.approx(16.0**2, rel=1e-6)


def test_circumscribed_hex_extrude_volume(kernel):
    assert kernel.dispatch("new_part", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    poly = kernel.dispatch(
        "sketch_polygon", {"sides": 6, "radius": 8, "polygon_type": "circumscribed"}
    )
    assert poly.ok and poly.result["entity_count"] == 6
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("extrude", {"depth": 10}).ok
    mp = kernel.dispatch("get_mass_properties", {})
    assert mp.ok
    assert mp.result["volume"] == pytest.approx(128.0 * math.sqrt(3) * 10.0, rel=1e-6)


def test_cube_faces_include_unit_normals(kernel):
    _cube(kernel)
    faces = kernel.dispatch("get_faces", {})
    assert faces.ok
    items = faces.result["faces"]
    assert len(items) == 6
    for f in items:
        n = f["normal"]
        assert pytest.approx(sum(c * c for c in n), rel=1e-9) == 1.0


def test_cylinder_faces_omit_zero_normal(kernel):
    assert kernel.dispatch("new_part", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 5}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("extrude", {"depth": 10}).ok
    faces = kernel.dispatch("get_faces", {})
    assert faces.ok
    kinds = {f["kind"]: f for f in faces.result["faces"]}
    assert "cylinder" in kinds and "normal" not in kinds["cylinder"]
    planes = [f for f in faces.result["faces"] if f["kind"] == "plane"]
    assert planes and all("normal" in f for f in planes)


def test_polygon_across_flats_dimension(kernel):
    assert kernel.dispatch("new_part", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    poly = kernel.dispatch(
        "sketch_polygon", {"sides": 6, "radius": 8, "polygon_type": "circumscribed"}
    )
    assert poly.ok, poly.error
    assert len(poly.result["sides"]) == 6
    dim = kernel.dispatch(
        "add_sketch_dimension", {"x1": -8, "y1": 0, "x2": 8, "y2": 0, "value": 16}
    )
    assert dim.ok, dim.error


def test_polygon_across_flats_by_index(kernel):
    assert kernel.dispatch("new_part", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    poly = kernel.dispatch(
        "sketch_polygon", {"sides": 6, "radius": 8, "polygon_type": "circumscribed"}
    )
    assert poly.ok
    sides = poly.result["sides"]
    i0, i1 = sides[0]["index"], sides[3]["index"]
    dim = kernel.dispatch(
        "add_sketch_dimension", {"entity1": i0, "entity2": i1, "value": 16}
    )
    assert dim.ok, dim.error


def test_mate_screw_requires_positive_pitch(kernel):
    kernel.dispatch("new_assembly", {})
    r = kernel.dispatch("mate", {"type": "screw", "entity1": "a", "entity2": "b", "pitch": 0})
    assert not r.ok and r.error.code == "INVALID_ARGUMENT"


def test_mate_screw_on_cylinder_faces(kernel, workspace: Path):
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 5})
    kernel.dispatch("end_sketch", {})
    kernel.dispatch("extrude", {"depth": 30})
    assert kernel.dispatch("save_document", {"path": "cyl.sldprt"}).ok
    kernel.dispatch("close_document", {"discard": True})
    kernel.dispatch("new_assembly", {})
    kernel.dispatch("insert_component", {"path": "cyl.sldprt"})
    kernel.dispatch("insert_component", {"path": "cyl.sldprt", "x": 20})
    r = kernel.dispatch(
        "mate",
        {"type": "screw", "entity1": "cyl-1#face:0", "entity2": "cyl-2#face:0", "pitch": 1.5},
    )
    assert r.ok, r.error
    assert r.result["mate_type"] == "screw"


def test_screw_nut_assembly_mates(kernel, workspace: Path):
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 5})
    kernel.dispatch("end_sketch", {})
    kernel.dispatch("extrude", {"depth": 16})
    assert kernel.dispatch(
        "insert_thread", {"diameter": 10, "pitch": 1.5, "length": 6}
    ).ok
    assert kernel.dispatch("save_document", {"path": "screw.sldprt"}).ok
    kernel.dispatch("close_document", {"discard": True})
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 9})
    kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 5})
    kernel.dispatch("end_sketch", {})
    kernel.dispatch("extrude", {"depth": 8})
    assert kernel.dispatch(
        "insert_thread",
        {"diameter": 10, "pitch": 1.5, "length": 6, "internal": True},
    ).ok
    assert kernel.dispatch("save_document", {"path": "nut.sldprt"}).ok
    kernel.dispatch("close_document", {"discard": True})
    kernel.dispatch("new_assembly", {})
    kernel.dispatch("insert_component", {"path": "screw.sldprt"})
    kernel.dispatch("insert_component", {"path": "nut.sldprt", "x": 30})
    conc = kernel.dispatch(
        "mate",
        {"type": "concentric", "entity1": "screw-1#face:0", "entity2": "nut-1#face:1"},
    )
    assert conc.ok, conc.error
    screw = kernel.dispatch(
        "mate",
        {"type": "screw", "entity1": "screw-1#face:0", "entity2": "nut-1#face:1", "pitch": 1.5},
    )
    assert screw.ok, screw.error
    planes = kernel.dispatch(
        "mate",
        {"type": "concentric", "entity1": "screw-1#face:1", "entity2": "nut-1#face:0"},
    )
    assert not planes.ok and planes.error.code == "FEATURE_CREATE_FAILED"


#---------- 草图增强 ----------


def test_sketch_list_edit_and_status(kernel):
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    assert kernel.dispatch("sketch_line", {"x1": 0, "y1": 0, "x2": 50, "y2": 10}).ok
    assert kernel.dispatch("sketch_line", {"x1": 0, "y1": 0, "x2": 10, "y2": 40}).ok
    listed = kernel.dispatch("list_sketch_entities", {})
    assert listed.ok, listed.error
    assert listed.result["count"] == 2
    assert listed.result["entities"][0]["kind"] == "line"
    st = kernel.dispatch("sketch_status", {})
    assert st.ok and st.result["state"] == "under_defined"
    assert kernel.dispatch("add_sketch_relation", {"relation": "horizontal", "entity1": 0}).ok
    after = kernel.dispatch("list_sketch_entities", {})
    y0, y1 = after.result["entities"][0]["points"][0][1], after.result["entities"][0]["points"][1][1]
    assert y0 == pytest.approx(y1, abs=1e-6)
    assert kernel.dispatch("add_sketch_dimension", {"entity1": 0, "value": 80}).ok
    sized = kernel.dispatch("list_sketch_entities", {})
    p0, p1 = sized.result["entities"][0]["points"]
    assert math.hypot(p1[0] - p0[0], p1[1] - p0[1]) == pytest.approx(80.0, abs=1e-6)
    ended = kernel.dispatch("end_sketch", {})
    assert ended.ok and ended.result["name"] == "Sketch1"
    named = kernel.dispatch("list_sketch_entities", {"sketch": "Sketch1"})
    assert named.ok and named.result["count"] == 2
    opened = kernel.dispatch("edit_sketch", {"name": "Sketch1"})
    assert opened.ok and opened.result["name"] == "Sketch1"
    assert kernel.dispatch("end_sketch", {}).ok
    missing = kernel.dispatch("edit_sketch", {"name": "NoSuch"})
    assert not missing.ok and missing.error.code == "FEATURE_NOT_FOUND"
    idle = kernel.dispatch("list_sketch_entities", {})
    assert not idle.ok and idle.error.code == "NO_ACTIVE_SKETCH"


def test_sketch_advanced_entities(kernel):
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {})
    line = kernel.dispatch("sketch_line", {"x1": 0, "y1": 0, "x2": 10, "y2": 2})
    assert line.ok and line.result["entity_count"] == 1
    poly = kernel.dispatch("sketch_polygon", {"sides": 6, "radius": 5})
    assert poly.ok and poly.result["entity_count"] == 7
    assert len(poly.result["sides"]) == 6
    dim = kernel.dispatch(
        "add_sketch_dimension", {"x1": 0, "y1": 0, "x2": 10, "y2": 2, "value": 20}
    )
    assert dim.ok, dim.error
    rel = kernel.dispatch("add_sketch_relation", {"relation": "horizontal", "entity1": 0})
    assert rel.ok, rel.error
    circ = kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 5})
    assert circ.ok
    diam = kernel.dispatch(
        "add_sketch_dimension", {"x1": 0, "y1": 0, "x2": 5, "y2": 0, "value": 16}
    )
    assert diam.ok, diam.error
    tan_line = kernel.dispatch("sketch_line", {"x1": 8, "y1": -2, "x2": 12, "y2": 3})
    assert tan_line.ok
    tan = kernel.dispatch(
        "add_sketch_relation", {"relation": "tangent", "entity1": 7, "entity2": 8}
    )
    assert tan.ok, tan.error


def test_sketch_spline_open_and_closed(kernel):
    kernel.dispatch("new_part", {})
    idle = kernel.dispatch("sketch_spline", {"points": [[0, 0], [10, 0]]})
    assert not idle.ok and idle.error.code == "NO_ACTIVE_SKETCH"
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    few = kernel.dispatch("sketch_spline", {"points": [[0, 0]]})
    assert not few.ok and few.error.code == "INVALID_ARGUMENT"
    open_sp = kernel.dispatch("sketch_spline", {"points": [[0, 0], [20, 5], [40, 0]]})
    assert open_sp.ok, open_sp.error
    listed = kernel.dispatch("list_sketch_entities", {})
    assert listed.ok
    kinds = [e["kind"] for e in listed.result["entities"]]
    assert "spline" in kinds
    kernel.dispatch("end_sketch", {})
    cut = kernel.dispatch("extrude", {"depth": 10})
    assert not cut.ok and cut.error.code == "FEATURE_CREATE_FAILED"
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    closed = kernel.dispatch(
        "sketch_spline",
        {"points": [[0, 0], [40, 0], [40, 20], [0, 20]], "closed": True},
    )
    assert closed.ok and closed.result.get("closed") is True
    kernel.dispatch("end_sketch", {})
    boss = kernel.dispatch("extrude", {"depth": 10})
    assert boss.ok, boss.error
    mp = kernel.dispatch("get_mass_properties", {})
    assert mp.result["volume"] == pytest.approx(8000.0, rel=1e-6)


def test_sketch_offset_trim_mirror(kernel):
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    assert kernel.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 40, "y2": 20}).ok
    off = kernel.dispatch("sketch_offset", {"distance": 5, "inward": True})
    assert off.ok, off.error
    assert off.result["entity_count"] == 2
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("extrude", {"depth": 10}).ok
    geo = kernel.dispatch("get_geometry", {})
    assert geo.ok
    assert geo.result["volume"] == pytest.approx(5000.0, rel=1e-6)
    assert geo.result["face_count"] == 10
    assert geo.result["edge_count"] == 16
    idle = kernel.dispatch("sketch_offset", {"distance": 5})
    assert not idle.ok and idle.error.code == "NO_ACTIVE_SKETCH"

    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    assert kernel.dispatch("sketch_line", {"x1": 0, "y1": 0, "x2": 20, "y2": 0}).ok
    assert kernel.dispatch("sketch_line", {"x1": 20, "y1": 0, "x2": 20, "y2": 20}).ok
    trim = kernel.dispatch("sketch_trim", {"entity1": 0, "entity2": 1, "radius": 4})
    assert trim.ok, trim.error
    listed = kernel.dispatch("list_sketch_entities", {})
    assert listed.ok and listed.result["count"] == 3
    zero = kernel.dispatch("sketch_trim", {"entity1": 0, "entity2": 1, "radius": 0})
    assert not zero.ok and zero.error.code == "INVALID_ARGUMENT"
    assert kernel.dispatch("end_sketch", {}).ok

    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    assert kernel.dispatch("sketch_line", {"x1": 0, "y1": 0, "x2": 0, "y2": 20}).ok
    assert kernel.dispatch("sketch_rectangle", {"x1": 5, "y1": 0, "x2": 25, "y2": 10}).ok
    mir = kernel.dispatch("sketch_mirror", {"axis": 0})
    assert mir.ok, mir.error
    after = kernel.dispatch("list_sketch_entities", {})
    assert after.ok and after.result["count"] == 3
    assert after.result["entities"][0]["construction"] is True
    bad = kernel.dispatch("sketch_mirror", {"axis": 99})
    assert not bad.ok and bad.error.code == "INVALID_ARGUMENT"


def test_hole_wizard_through(kernel):
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    assert kernel.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 50, "y2": 50}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("extrude", {"depth": 20}).ok
    faces = kernel.dispatch("get_faces", {"kind": "plane", "query": "max_z"})
    idx = faces.result["faces"][0]["index"]
    hole = kernel.dispatch("hole_wizard", {"face": idx, "diameter": 6, "end": "through_all"})
    assert hole.ok, hole.error
    assert hole.result["kind"] == "hole_wizard"
    geo = kernel.dispatch("get_geometry", {})
    assert geo.result["volume"] == pytest.approx(50000.0 - math.pi * 9.0 * 20.0, rel=1e-6)
    bad = kernel.dispatch("hole_wizard", {"face": 99, "diameter": 6, "end": "through_all"})
    assert not bad.ok and bad.error.code == "INVALID_ARGUMENT"
    need_depth = kernel.dispatch("hole_wizard", {"face": idx, "diameter": 6, "end": "blind"})
    assert not need_depth.ok and need_depth.error.code == "INVALID_ARGUMENT"


def test_sheet_metal_base_edge_unfold(kernel):
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    assert kernel.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 80, "y2": 40}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    base = kernel.dispatch("base_flange", {"thickness": 1})
    assert base.ok, base.error
    assert base.result["kind"] == "base_flange"
    geo = kernel.dispatch("get_geometry", {})
    assert geo.result["volume"] == pytest.approx(3200.0, rel=1e-6)
    fl = kernel.dispatch("edge_flange", {"edge": 8, "length": 20})
    assert fl.ok, fl.error
    assert fl.result["kind"] == "edge_flange"
    flat = kernel.dispatch("sheet_metal_unfold", {})
    assert flat.ok, flat.error
    assert flat.result["k_factor"] == pytest.approx(0.5)
    assert flat.result["length"] > flat.result["width"] > 0
    bad = kernel.dispatch("edge_flange", {"edge": 99, "length": 10})
    assert not bad.ok and bad.error.code == "INVALID_ARGUMENT"
    zero = kernel.dispatch("base_flange", {"thickness": 0})
    assert not zero.ok and zero.error.code == "INVALID_ARGUMENT"
    kernel.dispatch("close_document", {"discard": True})
    kernel.dispatch("new_part", {})
    naked = kernel.dispatch("sheet_metal_unfold", {})
    assert not naked.ok and naked.error.code == "FEATURE_CREATE_FAILED"


def test_split_body_right_plane(kernel):
    assert kernel.dispatch("new_part", {}).ok
    missing = kernel.dispatch("split_body", {"plane": "Right Plane"})
    assert not missing.ok and missing.error.code == "FEATURE_CREATE_FAILED"
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch("sketch_rectangle", {"x1": -20, "y1": -10, "x2": 20, "y2": 10}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("extrude", {"depth": 10}).ok
    nosuch = kernel.dispatch("split_body", {"plane": "NoSuch"})
    assert not nosuch.ok and nosuch.error.code == "FEATURE_NOT_FOUND"
    face = kernel.dispatch("split_body", {"plane": "Front Plane"})
    assert not face.ok and face.error.code == "FEATURE_CREATE_FAILED"
    feat = kernel.dispatch("split_body", {"plane": "Right Plane"})
    assert feat.ok, feat.error
    assert feat.result["kind"] == "split_body"
    geo = kernel.dispatch("get_geometry", {})
    assert geo.result["volume"] == pytest.approx(8000.0, rel=1e-6)
    assert geo.result["face_count"] == 12
    comb = kernel.dispatch("combine", {"op": "add"})
    assert comb.ok, comb.error


def test_parting_line(kernel):
    assert kernel.dispatch("new_part", {}).ok
    empty = kernel.dispatch("parting_line", {"pull_face": 0})
    assert not empty.ok and empty.error.code == "FEATURE_CREATE_FAILED"
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 40, "y2": 20}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("extrude", {"depth": 10}).ok
    bad = kernel.dispatch("parting_line", {"pull_face": 999})
    assert not bad.ok and bad.error.code == "INVALID_ARGUMENT"
    empty_edges = kernel.dispatch("parting_line", {"pull_face": 0, "edges": []})
    assert not empty_edges.ok and empty_edges.error.code == "INVALID_ARGUMENT"
    feat = kernel.dispatch("parting_line", {"pull_face": 0})
    assert feat.ok, feat.error
    assert feat.result["kind"] == "parting_line"
    assert feat.result["pull_face"] == 0
    mp = kernel.dispatch("get_mass_properties", {})
    assert mp.result["volume"] == pytest.approx(8000.0, rel=1e-6)


def test_parting_surface(kernel):
    assert kernel.dispatch("new_part", {}).ok
    missing = kernel.dispatch("parting_surface", {})
    assert not missing.ok and missing.error.code == "FEATURE_CREATE_FAILED"
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 40, "y2": 20}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("extrude", {"depth": 10}).ok
    assert kernel.dispatch("parting_line", {"pull_face": 0}).ok
    nosuch = kernel.dispatch("parting_surface", {"parting_line": "NoSuch"})
    assert not nosuch.ok and nosuch.error.code == "FEATURE_NOT_FOUND"
    surf = kernel.dispatch("parting_surface", {})
    assert surf.ok, surf.error
    assert surf.result["kind"] == "parting_surface"
    mp = kernel.dispatch("get_mass_properties", {})
    assert mp.result["volume"] == pytest.approx(8000.0, rel=1e-6)


def test_sketch_3d_sweep_path(kernel):
    assert kernel.dispatch("new_part", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "3D"}).ok
    assert kernel.dispatch("sketch_line", {"x1": 0, "y1": 0, "z1": 0, "x2": 40, "y2": 0, "z2": 10}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Right Plane"}).ok
    assert kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 5}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    feat = kernel.dispatch("sweep", {})
    assert feat.ok, feat.error
    geo = kernel.dispatch("get_geometry", {})
    assert geo.result["volume"] == pytest.approx(
        math.pi * 25.0 * math.hypot(40.0, 10.0), rel=1e-6
    )
    assert kernel.dispatch("new_part", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    z2d = kernel.dispatch("sketch_line", {"x1": 0, "y1": 0, "z1": 5, "x2": 10, "y2": 0})
    assert not z2d.ok and z2d.error.code == "INVALID_ARGUMENT"


def test_sketch_circle_3d(kernel):
    assert kernel.dispatch("new_part", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "3D"}).ok
    circ = kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "cz": 5, "r": 10})
    assert circ.ok, circ.error
    assert circ.result["entity_count"] >= 1
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("new_part", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    bad_z = kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "cz": 5, "r": 10})
    assert not bad_z.ok and bad_z.error.code == "INVALID_ARGUMENT"


def test_sketch_polygon_3d(kernel):
    assert kernel.dispatch("new_part", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "3D"}).ok
    poly = kernel.dispatch(
        "sketch_polygon", {"sides": 6, "radius": 10, "cx": 0, "cy": 0, "cz": 5}
    )
    assert poly.ok, poly.error
    assert poly.result["entity_count"] == 6
    assert len(poly.result["sides"]) == 6
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("new_part", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    bad_z = kernel.dispatch("sketch_polygon", {"sides": 6, "radius": 10, "cz": 5})
    assert not bad_z.ok and bad_z.error.code == "INVALID_ARGUMENT"


def test_sketch_arc_3d(kernel):
    assert kernel.dispatch("new_part", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "3D"}).ok
    three = kernel.dispatch(
        "sketch_arc",
        {"x1": 0, "y1": 0, "z1": 0, "x2": 20, "y2": 10, "z2": 5, "x3": 40, "y3": 0, "z3": 0},
    )
    assert three.ok, three.error
    assert three.result["entity_count"] >= 1
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("new_part", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "3D"}).ok
    center = kernel.dispatch(
        "sketch_arc",
        {"cx": 0, "cy": 0, "cz": 0, "x1": 10, "y1": 0, "z1": 0, "x2": 0, "y2": 10, "z2": 0},
    )
    assert center.ok, center.error
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("new_part", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    bad_z = kernel.dispatch(
        "sketch_arc",
        {"x1": 0, "y1": 0, "z1": 5, "x2": 10, "y2": 10, "x3": 20, "y3": 0},
    )
    assert not bad_z.ok and bad_z.error.code == "INVALID_ARGUMENT"


def test_sketch_spline_3d(kernel):
    assert kernel.dispatch("new_part", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "3D"}).ok
    sp = kernel.dispatch(
        "sketch_spline",
        {"points": [[0, 0, 0], [20, 0, 10], [40, 5, 0]]},
    )
    assert sp.ok, sp.error
    assert sp.result["entity_count"] >= 1
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("new_part", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    bad_z = kernel.dispatch(
        "sketch_spline",
        {"points": [[0, 0, 5], [20, 5, 0], [40, 0, 0]]},
    )
    assert not bad_z.ok and bad_z.error.code == "INVALID_ARGUMENT"


def test_sketch_rect_3d(kernel):
    assert kernel.dispatch("new_part", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "3D"}).ok
    rect = kernel.dispatch(
        "sketch_rectangle",
        {"x1": 0, "y1": 0, "z1": 0, "x2": 40, "y2": 20, "z2": 10},
    )
    assert rect.ok, rect.error
    assert rect.result["entity_count"] >= 1
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("new_part", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    bad_z = kernel.dispatch(
        "sketch_rectangle",
        {"x1": 0, "y1": 0, "z1": 5, "x2": 20, "y2": 10, "z2": 0},
    )
    assert not bad_z.ok and bad_z.error.code == "INVALID_ARGUMENT"


def test_rib_draft_combine(kernel):
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    assert kernel.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 40, "y2": 20}).ok
    assert kernel.dispatch("sketch_offset", {"distance": 5, "inward": True}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("extrude", {"depth": 10}).ok
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    assert kernel.dispatch("sketch_line", {"x1": 5, "y1": 10, "x2": 35, "y2": 10}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    rib = kernel.dispatch("rib", {"thickness": 3})
    assert rib.ok, rib.error
    geo = kernel.dispatch("get_geometry", {})
    assert geo.result["volume"] == pytest.approx(5900.0, rel=1e-6)

    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    assert kernel.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 40, "y2": 20}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("extrude", {"depth": 10}).ok
    dft = kernel.dispatch("draft", {"angle_deg": 5, "faces": [2], "neutral": 1})
    assert dft.ok, dft.error
    bad_face = kernel.dispatch("draft", {"angle_deg": 5, "faces": [99], "neutral": 1})
    assert not bad_face.ok and bad_face.error.code == "INVALID_ARGUMENT"

    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    assert kernel.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 20, "y2": 20}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("extrude", {"depth": 10}).ok
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    assert kernel.dispatch("sketch_rectangle", {"x1": 5, "y1": 5, "x2": 15, "y2": 15}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("extrude", {"depth": 10, "merge": False}).ok
    comb = kernel.dispatch("combine", {"op": "add"})
    assert comb.ok, comb.error
    geo2 = kernel.dispatch("get_geometry", {})
    assert geo2.result["volume"] == pytest.approx(4000.0, rel=1e-6)
    one = kernel.dispatch("combine", {"op": "add"})
    assert not one.ok and one.error.code == "FEATURE_CREATE_FAILED"


def test_sketch_arc_three_point_and_center(kernel):
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {})
    a = kernel.dispatch(
        "sketch_arc", {"x1": 0, "y1": 10, "x2": 10, "y2": 0, "x3": 0, "y3": -10}
    )
    assert a.ok and a.result["entity_count"] == 1
    b = kernel.dispatch(
        "sketch_arc", {"cx": 30, "cy": 0, "x1": 40, "y1": 0, "x2": 30, "y2": 10}
    )
    assert b.ok and b.result["entity_count"] == 2
    bad = kernel.dispatch("sketch_arc", {"x1": 0, "y1": 0, "x2": 10, "y2": 0})
    assert not bad.ok and bad.error.code == "INVALID_ARGUMENT"
    collinear = kernel.dispatch(
        "sketch_arc", {"x1": 0, "y1": 0, "x2": 10, "y2": 0, "x3": 20, "y3": 0}
    )
    assert not collinear.ok and collinear.error.code == "SKETCH_OP_FAILED"
    line = kernel.dispatch("sketch_line", {"x1": 0, "y1": 10, "x2": 40, "y2": 10})
    assert line.ok
    rel = kernel.dispatch(
        "add_sketch_relation", {"relation": "coincident", "entity1": 0, "entity2": 2}
    )
    assert rel.ok, rel.error


def test_slot_extrude_volume(kernel):
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    assert kernel.dispatch("sketch_line", {"x1": 0, "y1": 10, "x2": 40, "y2": 10}).ok
    assert kernel.dispatch(
        "sketch_arc", {"x1": 40, "y1": 10, "x2": 50, "y2": 0, "x3": 40, "y3": -10}
    ).ok
    assert kernel.dispatch("sketch_line", {"x1": 40, "y1": -10, "x2": 0, "y2": -10}).ok
    assert kernel.dispatch(
        "sketch_arc", {"x1": 0, "y1": -10, "x2": -10, "y2": 0, "x3": 0, "y3": 10}
    ).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("extrude", {"depth": 10}).ok
    mp = kernel.dispatch("get_mass_properties", {})
    expected = 40.0 * 20.0 * 10.0 + math.pi * 10.0 * 10.0 * 10.0
    assert mp.result["volume"] == pytest.approx(expected, rel=1e-9)


def test_rounded_plate_volume(kernel):
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    w, h, r = 50.0, 30.0, 5.0

    def polar(cx: float, cy: float, deg: float) -> tuple[float, float]:
        a = math.radians(deg)
        return (cx + r * math.cos(a), cy + r * math.sin(a))

    assert kernel.dispatch("sketch_line", {"x1": r, "y1": 0, "x2": w - r, "y2": 0}).ok
    x, y = polar(w - r, r, -45)
    assert kernel.dispatch(
        "sketch_arc", {"x1": w - r, "y1": 0, "x2": x, "y2": y, "x3": w, "y3": r}
    ).ok
    assert kernel.dispatch("sketch_line", {"x1": w, "y1": r, "x2": w, "y2": h - r}).ok
    x, y = polar(w - r, h - r, 45)
    assert kernel.dispatch(
        "sketch_arc", {"x1": w, "y1": h - r, "x2": x, "y2": y, "x3": w - r, "y3": h}
    ).ok
    assert kernel.dispatch("sketch_line", {"x1": w - r, "y1": h, "x2": r, "y2": h}).ok
    x, y = polar(r, h - r, 135)
    assert kernel.dispatch(
        "sketch_arc", {"x1": r, "y1": h, "x2": x, "y2": y, "x3": 0, "y3": h - r}
    ).ok
    assert kernel.dispatch("sketch_line", {"x1": 0, "y1": h - r, "x2": 0, "y2": r}).ok
    x, y = polar(r, r, 225)
    assert kernel.dispatch(
        "sketch_arc", {"x1": 0, "y1": r, "x2": x, "y2": y, "x3": r, "y3": 0}
    ).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("extrude", {"depth": 10}).ok
    mp = kernel.dispatch("get_mass_properties", {})
    area = w * h - 4 * r * r + math.pi * r * r
    assert mp.result["volume"] == pytest.approx(area * 10.0, rel=1e-9)


def test_sketch_dimension_rejects_nonpositive(kernel):
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {})
    kernel.dispatch("sketch_line", {"x1": 0, "y1": 0, "x2": 10, "y2": 2})
    r = kernel.dispatch(
        "add_sketch_dimension", {"x1": 0, "y1": 0, "x2": 10, "y2": 2, "value": 0}
    )
    assert not r.ok and r.error.code == "INVALID_ARGUMENT"


def test_sketch_relation_rejects_unknown_and_oob(kernel):
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {})
    kernel.dispatch("sketch_line", {"x1": 0, "y1": 0, "x2": 10, "y2": 2})
    unknown = kernel.dispatch("add_sketch_relation", {"relation": "foo", "entity1": 0})
    assert not unknown.ok and unknown.error.code == "INVALID_ARGUMENT"
    missing_pair = kernel.dispatch("add_sketch_relation", {"relation": "coincident", "entity1": 0})
    assert not missing_pair.ok and missing_pair.error.code == "INVALID_ARGUMENT"
    oob = kernel.dispatch("add_sketch_relation", {"relation": "horizontal", "entity1": 9})
    assert not oob.ok and oob.error.code == "INVALID_ARGUMENT"


def test_sketch_relations_ext(kernel):
    assert kernel.dispatch("new_part", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch("sketch_line", {"x1": 0, "y1": 0, "x2": 40, "y2": 2}).ok
    assert kernel.dispatch("sketch_line", {"x1": 45, "y1": 0, "x2": 80, "y2": -1}).ok
    col = kernel.dispatch(
        "add_sketch_relation", {"relation": "colinear", "entity1": 0, "entity2": 1}
    )
    assert col.ok, col.error
    assert kernel.dispatch("sketch_line", {"x1": 0, "y1": 20, "x2": 20, "y2": 25}).ok
    fix = kernel.dispatch("add_sketch_relation", {"relation": "fixed", "entity1": 2})
    assert fix.ok, fix.error
    assert kernel.dispatch("sketch_line", {"x1": 0, "y1": 40, "x2": 40, "y2": 40}).ok
    assert kernel.dispatch("sketch_line", {"x1": 18, "y1": 50, "x2": 22, "y2": 55}).ok
    mid = kernel.dispatch(
        "add_sketch_relation", {"relation": "midpoint", "entity1": 4, "entity2": 3}
    )
    assert mid.ok, mid.error
    ents = kernel.dispatch("list_sketch_entities", {})
    assert ents.ok and ents.result["count"] >= 5
    #中点后 stub 近端应贴近中线中点 (20,40)
    stub = next(e for e in ents.result["entities"] if e["index"] == 4)
    pts = stub["points"]
    near = min(math.hypot(p[0] - 20.0, p[1] - 40.0) for p in pts[:2])
    assert near == pytest.approx(0.0, abs=1e-6)
    bad = kernel.dispatch(
        "add_sketch_relation", {"relation": "symmetric", "entity1": 0, "entity2": 1}
    )
    assert not bad.ok and bad.error.code == "INVALID_ARGUMENT"


def test_sketch_symmetric(kernel):
    assert kernel.dispatch("new_part", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch("sketch_line", {"x1": 0, "y1": -30, "x2": 0, "y2": 30}).ok
    assert kernel.dispatch("sketch_line", {"x1": -20, "y1": 10, "x2": -10, "y2": 15}).ok
    assert kernel.dispatch("sketch_line", {"x1": 10, "y1": 12, "x2": 20, "y2": 8}).ok
    ok = kernel.dispatch(
        "add_sketch_relation",
        {"relation": "symmetric", "entity1": 1, "entity2": 2, "entity3": 0},
    )
    assert ok.ok, ok.error
    ents = kernel.dispatch("list_sketch_entities", {})
    assert ents.ok and ents.result["count"] >= 3
    right = next(e for e in ents.result["entities"] if e["index"] == 2)
    #fake：右线应为左线关于 y 轴的镜像 → x 取反
    pts = right["points"]
    assert pts[0][0] == pytest.approx(20.0, abs=1e-6)
    assert pts[0][1] == pytest.approx(10.0, abs=1e-6)
    assert pts[1][0] == pytest.approx(10.0, abs=1e-6)
    assert pts[1][1] == pytest.approx(15.0, abs=1e-6)
    missing = kernel.dispatch(
        "add_sketch_relation", {"relation": "symmetric", "entity1": 1, "entity2": 2}
    )
    assert not missing.ok and missing.error.code == "INVALID_ARGUMENT"


def test_sketch_polygon_rejects_degenerate_sides(kernel):
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {})
    r = kernel.dispatch("sketch_polygon", {"sides": 2, "radius": 5})
    assert not r.ok and r.error.code == "INVALID_ARGUMENT"  # schema minimum 3


#---------- 螺纹 / 螺旋线 / 扫掠 ----------


def _circle_sketch(kernel, radius: float = 5.0) -> None:
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    assert kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": radius}).ok
    assert kernel.dispatch("end_sketch", {}).ok


def _path_and_circle_profile(
    kernel, *, profile_r: float = 5.0, path: tuple[float, float, float, float] = (0, 0, 50, 0)
) -> None:
    if not kernel.dispatch("get_active_document", {}).ok:
        kernel.dispatch("new_part", {})
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch(
        "sketch_line", {"x1": path[0], "y1": path[1], "x2": path[2], "y2": path[3]}
    ).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Right Plane"}).ok
    assert kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": profile_r}).ok
    assert kernel.dispatch("end_sketch", {}).ok


def test_create_helix_from_circle_sketch(kernel):
    _circle_sketch(kernel)
    r = kernel.dispatch("create_helix", {"pitch": 1.5, "revolutions": 4})
    assert r.ok, r.error
    assert r.result["name"] == "Helix1"
    assert r.result["unit"] == "mm"
    feats = kernel.dispatch("list_features", {})
    assert feats.ok and any(f["name"] == "Helix1" for f in feats.result["features"])


def test_create_helix_by_height_and_pitch(kernel):
    _circle_sketch(kernel)
    r = kernel.dispatch("create_helix", {"pitch": 1.5, "height": 6})
    assert r.ok, r.error
    assert r.result["name"] == "Helix1"


def test_create_helix_rejects_bad_params_and_sketch(kernel):
    _circle_sketch(kernel)
    bad_pitch = kernel.dispatch("create_helix", {"pitch": 0, "revolutions": 4})
    assert not bad_pitch.ok and bad_pitch.error.code == "INVALID_ARGUMENT"

    #消耗草图后再调 → SKETCH_NOT_FOUND
    assert kernel.dispatch("create_helix", {"pitch": 1.5, "revolutions": 2}).ok
    again = kernel.dispatch("create_helix", {"pitch": 1.5, "revolutions": 2})
    assert not again.ok and again.error.code == "SKETCH_NOT_FOUND"

    #矩形草图不能生成螺旋线
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {})
    kernel.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 10, "y2": 10})
    kernel.dispatch("end_sketch", {})
    rect = kernel.dispatch("create_helix", {"pitch": 1.5, "revolutions": 2})
    assert not rect.ok and rect.error.code == "FEATURE_CREATE_FAILED"


def test_sweep_and_cut_from_last_two_sketches(kernel):
    _path_and_circle_profile(kernel, profile_r=5)
    r = kernel.dispatch("sweep", {})
    assert r.ok, r.error
    assert r.result == {"name": "Sweep1", "kind": "sweep"}
    boss = kernel.dispatch("get_mass_properties", {})
    assert boss.ok and boss.result["volume"] > 0

    #凸台扫掠吸收轮廓+路径 → 再扫掠找不到草图
    again = kernel.dispatch("sweep", {})
    assert not again.ok and again.error.code == "SKETCH_NOT_FOUND"

    _path_and_circle_profile(kernel, profile_r=2, path=(0, 0, 50, 0))
    cut = kernel.dispatch("sweep_cut", {})
    assert cut.ok, cut.error
    assert cut.result == {"name": "Cut-Sweep1", "kind": "sweep_cut"}
    after = kernel.dispatch("get_mass_properties", {})
    assert after.ok and after.result["volume"] < boss.result["volume"]


def test_sweep_accepts_explicit_sketch_names(kernel):
    _path_and_circle_profile(kernel, profile_r=3)
    r = kernel.dispatch("sweep", {"profile_sketch": "Sketch2", "path_sketch": "Sketch1"})
    assert r.ok, r.error


def test_sweep_cut_requires_material(kernel):
    _path_and_circle_profile(kernel, profile_r=2)
    r = kernel.dispatch("sweep_cut", {})
    assert not r.ok and r.error.code == "FEATURE_CREATE_FAILED"


def test_sweep_rejects_bad_profile_and_path(kernel):
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    kernel.dispatch("sketch_line", {"x1": 0, "y1": 0, "x2": 50, "y2": 0})
    kernel.dispatch("end_sketch", {})
    kernel.dispatch("start_sketch", {"plane": "Right Plane"})
    kernel.dispatch("sketch_line", {"x1": 0, "y1": 0, "x2": 5, "y2": 0})
    kernel.dispatch("end_sketch", {})
    bad_profile = kernel.dispatch("sweep", {})
    assert not bad_profile.ok and bad_profile.error.code == "FEATURE_CREATE_FAILED"

    #路径是圆（非直线）→ FEATURE_CREATE_FAILED
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 5})
    kernel.dispatch("end_sketch", {})
    kernel.dispatch("start_sketch", {"plane": "Right Plane"})
    kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 2})
    kernel.dispatch("end_sketch", {})
    bad_path = kernel.dispatch("sweep", {})
    assert not bad_path.ok and bad_path.error.code == "FEATURE_CREATE_FAILED"


def test_sweep_along_polyline_and_arc_chain(kernel):
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    assert kernel.dispatch("sketch_line", {"x1": 0, "y1": 0, "x2": 40, "y2": 0}).ok
    assert kernel.dispatch("sketch_line", {"x1": 40, "y1": 0, "x2": 40, "y2": 20}).ok
    assert kernel.dispatch("sketch_line", {"x1": 40, "y1": 20, "x2": 0, "y2": 20}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    kernel.dispatch("start_sketch", {"plane": "Right Plane"})
    assert kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 5}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    r = kernel.dispatch("sweep", {})
    assert r.ok, r.error
    geo = kernel.dispatch("get_mass_properties", {})
    assert geo.ok
    #路径长 100 mm，圆面积 π·25 → 体积 2500π mm³
    assert geo.result["volume"] == pytest.approx(2500.0 * math.pi, rel=1e-6)

    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    assert kernel.dispatch("sketch_line", {"x1": 0, "y1": 0, "x2": 40, "y2": 0}).ok
    assert kernel.dispatch(
        "sketch_arc", {"x1": 40, "y1": 0, "x2": 50, "y2": 10, "x3": 40, "y3": 20}
    ).ok
    assert kernel.dispatch("sketch_line", {"x1": 40, "y1": 20, "x2": 0, "y2": 20}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    kernel.dispatch("start_sketch", {"plane": "Right Plane"})
    assert kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 5}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    arc = kernel.dispatch("sweep", {})
    assert arc.ok, arc.error
    geo2 = kernel.dispatch("get_mass_properties", {})
    #两段 40 mm + 半径 10 的半圆 π·10 → 路径 80+10π，体积 π·25·(80+10π)
    assert geo2.result["volume"] == pytest.approx(math.pi * 25.0 * (80.0 + 10.0 * math.pi), rel=1e-6)

    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    assert kernel.dispatch("sketch_line", {"x1": 0, "y1": 0, "x2": 20, "y2": 0}).ok
    assert kernel.dispatch("sketch_line", {"x1": 40, "y1": 10, "x2": 60, "y2": 10}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    kernel.dispatch("start_sketch", {"plane": "Right Plane"})
    assert kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 5}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    disconnected = kernel.dispatch("sweep", {})
    assert not disconnected.ok and disconnected.error.code == "FEATURE_CREATE_FAILED"


def test_sweep_along_helix_path(kernel):
    #真机：轮廓须与螺旋线起点相交。前视 r=5 圆生成螺旋后，再在前视 (5,0) 画 r=1 圆。
    _circle_sketch(kernel, radius=5)
    helix = kernel.dispatch("create_helix", {"pitch": 1.5, "revolutions": 4})
    assert helix.ok, helix.error
    assert helix.result["name"] == "Helix1"
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    kernel.dispatch("sketch_circle", {"cx": 5, "cy": 0, "r": 1})
    prof = kernel.dispatch("end_sketch", {})
    assert prof.ok and prof.result["name"] == "Sketch2"
    r = kernel.dispatch("sweep", {})
    assert r.ok, r.error
    assert r.result["name"] == "Sweep1"


def test_sweep_explicit_helix_and_sketch_names(kernel):
    _circle_sketch(kernel, radius=5)
    assert kernel.dispatch("create_helix", {"pitch": 1.5, "revolutions": 4}).ok
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    kernel.dispatch("sketch_circle", {"cx": 5, "cy": 0, "r": 1})
    kernel.dispatch("end_sketch", {})
    r = kernel.dispatch("sweep", {"profile_sketch": "Sketch2", "path_sketch": "Helix1"})
    assert r.ok, r.error


def test_sweep_accepts_localized_sketch_name(kernel):
    _path_and_circle_profile(kernel, profile_r=3)
    r = kernel.dispatch("sweep", {"profile_sketch": "草图2", "path_sketch": "Sketch1"})
    assert r.ok, r.error


def test_insert_thread_external_on_cylinder(kernel):
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    assert kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 5}).ok
    kernel.dispatch("end_sketch", {})
    assert kernel.dispatch("extrude", {"depth": 20}).ok
    r = kernel.dispatch("insert_thread", {"diameter": 10, "pitch": 1.5, "length": 6})
    assert r.ok, r.error
    assert r.result["kind"] == "thread"
    mp = kernel.dispatch("get_mass_properties", {})
    assert mp.ok and mp.result["volume"] < 1570.8


def test_insert_thread_requires_solid(kernel):
    kernel.dispatch("new_part", {})
    r = kernel.dispatch("insert_thread", {"diameter": 10, "pitch": 1.5})
    assert not r.ok and r.error.code == "FEATURE_CREATE_FAILED"


def test_insert_thread_rejects_huge_pitch(kernel):
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 5})
    kernel.dispatch("end_sketch", {})
    kernel.dispatch("extrude", {"depth": 20})
    huge = kernel.dispatch("insert_thread", {"diameter": 2, "pitch": 10})
    assert not huge.ok and huge.error.code == "INVALID_ARGUMENT"


def test_insert_thread_internal_on_tube(kernel):
    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    assert kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 9}).ok
    assert kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 5}).ok
    kernel.dispatch("end_sketch", {})
    assert kernel.dispatch("extrude", {"depth": 20}).ok
    r = kernel.dispatch(
        "insert_thread", {"diameter": 10, "pitch": 1.5, "length": 6, "internal": True}
    )
    assert r.ok, r.error
    assert r.result["kind"] == "thread"


#---------- 特征操作 ----------


def test_feature_suppress_delete(kernel):
    _cube(kernel)
    assert kernel.dispatch("suppress_feature", {"name": "Boss-Extrude1"}).ok
    assert kernel.dispatch("delete_feature", {"name": "Boss-Extrude1"}).ok
    r = kernel.dispatch("delete_feature", {"name": "Boss-Extrude1"})
    assert not r.ok and r.error.code == "FEATURE_NOT_FOUND"


#---------- 视图 / 选择 ----------


def test_view_selection_and_queries(kernel):
    _cube(kernel)
    assert kernel.dispatch("set_view", {"view": "front"}).ok
    bad = kernel.dispatch("set_view", {"view": "nope"})
    assert not bad.ok and bad.error.code == "INVALID_ARGUMENT"

    faces = kernel.dispatch("get_faces", {})
    assert faces.ok and len(faces.result["faces"]) == 6
    top = kernel.dispatch("get_faces", {"kind": "plane", "query": "max_z"})
    assert top.ok and len(top.result["faces"]) == 1
    assert top.result["faces"][0]["centroid"][2] == pytest.approx(10.0, abs=1e-6)
    none = kernel.dispatch("get_faces", {"kind": "cone"})
    assert none.ok and none.result["faces"] == []
    edges = kernel.dispatch("get_edges", {})
    assert edges.ok and len(edges.result["edges"]) == 12

    assert kernel.dispatch("select_face", {"index": 0}).ok
    assert kernel.dispatch("select_edge", {"index": 0}).ok

    kernel.dispatch("new_part", {})
    kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    kernel.dispatch("sketch_circle", {"cx": 0, "cy": 0, "r": 5})
    kernel.dispatch("end_sketch", {})
    kernel.dispatch("extrude", {"depth": 12})
    along_z = kernel.dispatch("get_faces", {"query": "axis_z"})
    assert along_z.ok and len(along_z.result["faces"]) == 1
    assert along_z.result["faces"][0]["kind"] == "cylinder"
    along_x = kernel.dispatch("get_faces", {"query": "axis_x"})
    assert along_x.ok and along_x.result["faces"] == []


def test_faces_and_edges_pagination_is_opt_in(kernel):
    _cube(kernel)
    full = kernel.dispatch("get_faces", {})
    assert full.ok and "total" not in full.result
    page = kernel.dispatch("get_faces", {"limit": 2, "offset": 1})
    assert page.ok
    assert [f["index"] for f in page.result["faces"]] == [1, 2]
    assert page.result["total"] == 6 and page.result["offset"] == 1
    edges = kernel.dispatch("get_edges", {"limit": 3})
    assert edges.ok and len(edges.result["edges"]) == 3
    assert edges.result["total"] == 12 and edges.result["offset"] == 0


def test_new_tools_require_document(kernel):
    for name, args in [
        ("set_view", {"view": "front"}),
        ("get_faces", {}),
        ("select_face", {"index": 0}),
        ("mate", {"type": "concentric", "entity1": "a", "entity2": "b"}),
    ]:
        r = kernel.dispatch(name, args)
        assert not r.ok and r.error.code == "NO_ACTIVE_DOCUMENT", name
