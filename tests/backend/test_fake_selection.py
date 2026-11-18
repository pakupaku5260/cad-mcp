"""F1.3: Fake geometric-signature persist refs (selection)."""

from __future__ import annotations

from cadmcp.backend.fake import FakeBackend


def _make_box() -> FakeBackend:
    b = FakeBackend()
    b.new_part()
    b.begin_sketch("Front Plane")
    b.draw_rectangle(0.0, 0.0, 0.04, 0.05)
    b.end_sketch()
    b.extrude_blind(0.03)
    return b


def test_fake_ref_hit_without_model_change():
    b = _make_box()
    face = b.list_faces()[0]
    assert face.ref_id and face.ref_id.startswith("fake:")
    hit = b._face_by_persist_ref(face.ref_id)
    assert hit is not None
    assert hit.index == face.index
    assert hit.centroid_m == face.centroid_m


def test_fake_ref_stale_after_fillet_geometry_change():
    b = _make_box()
    face = b.list_faces()[0]
    ref_id = face.ref_id
    assert b._face_by_persist_ref(ref_id) is not None
    b.fillet_blind(0.002, edge_indexes=[0])
    assert b._face_by_persist_ref(ref_id) is None


def test_fake_ref_stale_after_delete_entity():
    b = _make_box()
    face = b.list_faces()[0]
    ref_id = face.ref_id
    assert b._face_by_persist_ref(ref_id) is not None
    b.delete_feature("Boss-Extrude1")
    assert b._face_by_persist_ref(ref_id) is None
