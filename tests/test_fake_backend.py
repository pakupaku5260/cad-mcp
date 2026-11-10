"""fake back-end behavioral surface test: strict domain check, canned geometric formula, call record, fault injection."""

from __future__ import annotations

import math

import pytest

from cadmcp.backend.fake import FakeBackend
from cadmcp.backend.fake._state import DENSITY_KG_M3
from cadmcp.backend.protocol.constants import STANDARD_VIEWS
from cadmcp.errors import CadMcpError

# ---------- Domain Precondition (Strictness: fake is established by = protocol semantics) ------------


@pytest.mark.parametrize(
    "call",
    [
        lambda b: b.mass_properties(),
        lambda b: b.fingerprint(),
        lambda b: b.list_features(),
        lambda b: b.begin_sketch("Front Plane"),
        lambda b: b.draw_rectangle(0, 0, 1, 1),
        lambda b: b.extrude_blind(0.01),
        lambda b: b.force_rebuild(),
        lambda b: b.close_document(discard=True),
    ],
    ids=["mass", "fingerprint", "features", "begin_sketch", "draw", "extrude", "rebuild", "close"],
)
def test_no_doc_raises_no_active_document(call):
    with pytest.raises(CadMcpError) as e:
        call(FakeBackend())
    assert e.value.code == "NO_ACTIVE_DOCUMENT"
    assert e.value.hint  # errors must include a next-step hint


def test_plane_unknown_lists_candidates():
    b = FakeBackend()
    b.new_part()
    with pytest.raises(CadMcpError) as e:
        b.begin_sketch("基准面X")
    assert e.value.code == "SKETCH_NOT_FOUND"
    assert "Front Plane" in e.value.hint


def test_draw_without_sketch_and_double_sketch():
    b = FakeBackend()
    b.new_part()
    with pytest.raises(CadMcpError) as e:
        b.draw_rectangle(0, 0, 1, 1)
    assert e.value.code == "NO_ACTIVE_SKETCH"

    b.begin_sketch("Front Plane")
    with pytest.raises(CadMcpError) as e:
        b.begin_sketch("Top Plane")
    assert e.value.code == "SKETCH_OP_FAILED"

    b.end_sketch()
    with pytest.raises(CadMcpError) as e:
        b.end_sketch()
    assert e.value.code == "NO_ACTIVE_SKETCH"


@pytest.mark.parametrize(
    "setup,expected_code",
    [
        (lambda b: None, "SKETCH_NOT_FOUND"),  # no profile drawn yet
        (lambda b: b.begin_sketch("Front Plane"), "SKETCH_OP_FAILED"),  # sketch still open
    ],
    ids=["no_pending", "sketch_still_open"],
)
def test_extrude_preconditions(setup, expected_code):
    b = FakeBackend()
    b.new_part()
    setup(b)
    with pytest.raises(CadMcpError) as e:
        b.extrude_blind(0.01)
    assert e.value.code == expected_code


def test_extrude_depth_and_profile_validation():
    b = FakeBackend()
    b.new_part()
    b.begin_sketch("Front Plane")
    b.draw_rectangle(0, 0, 0.01, 0.01)
    b.end_sketch()
    with pytest.raises(CadMcpError) as e:
        b.extrude_blind(0)
    assert e.value.code == "INVALID_ARGUMENT"

    # Empty sketch
    b.begin_sketch("Front Plane")
    b.end_sketch()
    with pytest.raises(CadMcpError) as e:
        b.extrude_blind(0.01)
    assert e.value.code == "FEATURE_CREATE_FAILED"


# ---------- canned geometry (parsing formula) ----------


def test_rect_prism_geometry_exact():
    b = FakeBackend()
    b.new_part()
    b.begin_sketch("Front Plane")
    b.draw_rectangle(0.0, 0.0, 0.04, 0.05)
    b.end_sketch()
    feat = b.extrude_blind(0.03)
    assert feat.name == "Boss-Extrude1"

    mp = b.mass_properties()
    vol = 0.04 * 0.05 * 0.03
    area = 2 * (0.04 * 0.05) + 2 * (0.04 + 0.05) * 0.03
    assert mp.volume_m3 == pytest.approx(vol, rel=1e-12)
    assert mp.surface_area_m2 == pytest.approx(area, rel=1e-12)
    assert mp.mass_kg == pytest.approx(vol * DENSITY_KG_M3, rel=1e-12)
    assert mp.center_of_mass_m == pytest.approx((0.02, 0.025, 0.015), rel=1e-12)

    fp = b.fingerprint()
    assert (fp.face_count, fp.edge_count) == (6, 12)
    assert fp.bbox_m == pytest.approx((0.0, 0.0, 0.0, 0.04, 0.05, 0.03), rel=1e-12)


def test_cylinder_geometry():
    b = FakeBackend()
    b.new_part()
    b.begin_sketch("Top Plane")
    b.draw_circle(0.02, 0.03, 0.01)
    b.end_sketch()
    b.extrude_blind(0.02)

    mp = b.mass_properties()
    vol = math.pi * 0.01**2 * 0.02
    assert mp.volume_m3 == pytest.approx(vol, rel=1e-12)
    fp = b.fingerprint()
    assert (fp.face_count, fp.edge_count) == (3, 2)
    # Top Plane: u/v→ X/Z, stretched edge + Y
    assert fp.bbox_m == pytest.approx((0.01, 0.0, 0.02, 0.03, 0.02, 0.04), rel=1e-12)


def test_multiple_features_sum_and_uuid_consumption():
    b = FakeBackend()
    b.new_part()
    for i in range(2):
        b.begin_sketch("Front Plane")
        b.draw_rectangle(0, 0, 0.01 * (i + 1), 0.01)
        b.end_sketch()
        b.extrude_blind(0.01)
    mp = b.mass_properties()
    expected = 0.01 * 0.01 * 0.01 + 0.02 * 0.01 * 0.01
    assert mp.volume_m3 == pytest.approx(expected, rel=1e-12)
    assert b.fingerprint().face_count == 12
    names = [f.name for f in b.list_features()]
    assert names == ["Boss-Extrude1", "Boss-Extrude2"]


# ---------- Call Recording and Fault Injection ----------


def test_call_recording_covers_attempts():
    b = FakeBackend()
    b.new_part()
    with pytest.raises(CadMcpError):
        b.extrude_blind(0.01)  # no sketch, expected failure
    assert b.call_names()[:2] == ["new_part", "extrude_blind"]
    assert b.calls_named("new_part")[0]["template"] is None


def test_fail_on_injection_records_and_skips_behavior():
    b = FakeBackend(fail_on=[("new_part", 1)])
    with pytest.raises(CadMcpError) as e:
        b.new_part()
    assert e.value.code == "COM_CALL_FAILED"
    assert e.value.side_effect.value == "applied"
    assert e.value.context.get("injected") is True
    # Attempt was logged, but the behavior was not performed
    assert b.call_names() == ["new_part"]
    assert b.active_document() is None
    # Second call OK
    assert b.new_part().title == "Part1"


def test_save_open_roundtrip_renames_title(tmp_path):
    b = FakeBackend()
    b.new_part()
    b.begin_sketch("Front Plane")
    b.draw_rectangle(0, 0, 1, 1)
    b.end_sketch()
    b.save_as(tmp_path / "bracket.sldprt")

    doc = b.active_document()
    assert doc is not None
    assert doc.title == "bracket"  # SW behavior: title after save-as equals file name
    assert doc.modified is False
    assert doc.path is not None

    b.close_document(discard=False)
    assert b.active_document() is None
    reopened = b.open_document(tmp_path / "bracket.sldprt")
    assert reopened.title == "bracket"


def test_screenshot_view_validation_and_write(tmp_path):
    b = FakeBackend()
    b.new_part()
    out = tmp_path / "shot.png"
    with pytest.raises(CadMcpError) as e:
        b.screenshot(out, "四十五度")
    assert e.value.code == "INVALID_ARGUMENT"
    assert "isometric" in e.value.hint

    b.screenshot(out, STANDARD_VIEWS[0])
    assert out.read_bytes().startswith(b"\x89PNG")


def test_rebuild_errors_injection():
    b = FakeBackend(rebuild_errors=["Boss-Extrude1: 轮廓未闭合"])
    b.new_part()
    out = b.force_rebuild()
    assert out.ok is False
    assert out.feature_errors[0].startswith("Boss-Extrude1")

