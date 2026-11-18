"""F4 transaction skeleton: begin/status/commit/rollback + compensators (Fake)."""
from __future__ import annotations

from pathlib import Path

import pytest

from cadmcp.backend.fake.backend import FakeBackend
from cadmcp.errors import SideEffect
from cadmcp.kernel import Kernel
from cadmcp.toolsets.core import core_registry


@pytest.fixture
def kernel(tmp_path: Path) -> Kernel:
    return Kernel(core_registry(), FakeBackend(), workspace=tmp_path)


def _box(kernel: Kernel) -> None:
    assert kernel.dispatch("new_part", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 40, "y2": 40}).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("extrude", {"depth": 20}).ok


def test_transaction_tools_registered():
    names = {s.name for s in core_registry().all() if s.toolset == "transaction"}
    assert names == {"tx_begin", "tx_status", "tx_commit", "tx_rollback"}


def test_tx_begin_status_commit(kernel: Kernel, tmp_path: Path):
    _box(kernel)
    r = kernel.dispatch("tx_begin", {"name": "t1"})
    assert r.ok, r.error
    tx_id = r.result["tx_id"]
    assert r.result["mode"] in {"checkpoint", "journal-only"}
    assert (tmp_path / ".cadmcp" / "tx" / tx_id).is_dir()

    st = kernel.dispatch("tx_status", {"tx_id": tx_id})
    assert st.ok and st.result["status"] == "active"

    c = kernel.dispatch("tx_commit", {"tx_id": tx_id})
    assert c.ok and c.result["journal_path"]
    # checkpoint removed on commit when present
    assert kernel.dispatch("tx_status", {"tx_id": tx_id}).ok is False
    assert kernel.dispatch("tx_status", {"tx_id": tx_id}).error.code == "NO_ACTIVE_TRANSACTION"


def test_compensate_restores_fingerprint(kernel: Kernel):
    _box(kernel)
    before = kernel.dispatch("get_geometry", {})
    assert before.ok
    fp0 = before.result

    begin = kernel.dispatch("tx_begin", {"name": "fillet_tx", "mode": "journal-only"})
    assert begin.ok
    tx_id = begin.result["tx_id"]

    fr = kernel.dispatch("fillet", {"radius": 2})
    if not fr.ok:
        fr = kernel.dispatch("shell", {"thickness": 1})
    assert fr.ok, fr.error

    # Bad param — must fail without journaling success
    bad = kernel.dispatch("fillet", {"radius": -1})
    assert not bad.ok

    rb = kernel.dispatch("tx_rollback", {"tx_id": tx_id, "mode": "compensate"})
    assert rb.ok, rb.error

    after = kernel.dispatch("get_geometry", {})
    assert after.ok
    for key in ("volume", "surface_area", "face_count", "edge_count"):
        assert after.result[key] == fp0[key], key


def test_repeat_rollback_no_active(kernel: Kernel):
    _box(kernel)
    begin = kernel.dispatch("tx_begin", {"name": "once", "mode": "journal-only"})
    tx_id = begin.result["tx_id"]
    assert kernel.dispatch("tx_rollback", {"tx_id": tx_id, "mode": "compensate"}).ok
    again = kernel.dispatch("tx_rollback", {"tx_id": tx_id, "mode": "compensate"})
    assert not again.ok
    assert again.error.code == "NO_ACTIVE_TRANSACTION"
    assert again.error.side_effect == SideEffect.NONE


def test_save_then_rollback_unsafe(kernel: Kernel, tmp_path: Path):
    _box(kernel)
    begin = kernel.dispatch("tx_begin", {"name": "save_block", "mode": "journal-only"})
    tx_id = begin.result["tx_id"]
    fp_before = kernel.dispatch("get_geometry", {}).result

    save = kernel.dispatch("save_document", {"path": "part_saved.sldprt", "overwrite": True})
    assert save.ok, save.error

    rb = kernel.dispatch("tx_rollback", {"tx_id": tx_id, "mode": "compensate"})
    assert not rb.ok
    assert rb.error.code == "ROLLBACK_UNSAFE"
    assert rb.error.side_effect == SideEffect.NONE

    fp_after = kernel.dispatch("get_geometry", {}).result
    for key in ("volume", "surface_area", "face_count", "edge_count"):
        assert fp_after[key] == fp_before[key]


def test_unsupported_step_blocks_compensate(kernel: Kernel):
    _box(kernel)
    begin = kernel.dispatch("tx_begin", {"name": "uns", "mode": "journal-only"})
    tx_id = begin.result["tx_id"]
    # set_equation is mutating but not in first-batch compensators
    eq = kernel.dispatch("set_equation", {"name": "D", "expression": "10"})
    if not eq.ok:
        pytest.skip("set_equation unavailable on bare box")
    assert any("TX_UNSUPPORTED_STEP" in w for w in eq.warnings)

    st = kernel.dispatch("tx_status", {"tx_id": tx_id})
    assert st.ok and "set_equation" in st.result.get("unsupported", [])

    rb = kernel.dispatch("tx_rollback", {"tx_id": tx_id, "mode": "compensate"})
    assert not rb.ok
    assert rb.error.code == "ROLLBACK_UNSAFE"


def test_discard_new_unsaved(kernel: Kernel):
    assert kernel.dispatch("new_part", {}).ok
    begin = kernel.dispatch("tx_begin", {"name": "discard_me", "mode": "journal-only"})
    tx_id = begin.result["tx_id"]
    rb = kernel.dispatch("tx_rollback", {"tx_id": tx_id, "mode": "discard"})
    assert rb.ok, rb.error
    gone = kernel.dispatch("get_active_document", {})
    assert not gone.ok and gone.error.code == "NO_ACTIVE_DOCUMENT"


def test_reload_from_checkpoint(kernel: Kernel, tmp_path: Path):
    _box(kernel)
    assert kernel.dispatch("save_document", {"path": "base.sldprt", "overwrite": True}).ok
    begin = kernel.dispatch("tx_begin", {"name": "reload_tx", "mode": "checkpoint"})
    assert begin.ok, begin.error
    tx_id = begin.result["tx_id"]
    if begin.result["mode"] != "checkpoint" or not begin.result.get("checkpoint"):
        pytest.skip("checkpoint degraded")
    fp0 = kernel.dispatch("get_geometry", {}).result
    assert kernel.dispatch("shell", {"thickness": 1}).ok
    rb = kernel.dispatch("tx_rollback", {"tx_id": tx_id, "mode": "reload"})
    assert rb.ok, rb.error
    fp1 = kernel.dispatch("get_geometry", {}).result
    for key in ("volume", "surface_area", "face_count", "edge_count"):
        assert fp1[key] == fp0[key]


def test_error_codes_in_catalog():
    from cadmcp.errors import CATALOG

    for code in (
        "NO_ACTIVE_TRANSACTION",
        "ROLLBACK_UNSAFE",
        "ROLLBACK_FAILED",
        "TX_UNSUPPORTED_STEP",
    ):
        assert code in CATALOG


def test_side_effect_unknown_exists():
    assert SideEffect.UNKNOWN.value == "unknown"
