"""F6: DocInfo extensions, list_open_documents, expect_* → WRONG_DOCUMENT (zero side effects)."""
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


def test_docinfo_additive_fields_on_new_part(kernel: Kernel):
    r = kernel.dispatch("new_part")
    assert r.ok
    assert set(r.result) >= {
        "title", "path", "doc_type", "modified", "units",
        "configuration", "epoch", "saved",
    }
    assert r.result["configuration"] == "Default"
    assert r.result["saved"] is False
    assert r.result["path"] is None
    assert r.result["epoch"] == "1"
    assert r.result["modified"] is False


def test_list_open_documents_multi_doc_and_active(kernel: Kernel):
    a = kernel.dispatch("new_part")
    b = kernel.dispatch("new_part")
    assert a.ok and b.ok
    listed = kernel.dispatch("list_open_documents")
    assert listed.ok
    assert listed.result["count"] == 2
    docs = listed.result["documents"]
    assert sorted(d["title"] for d in docs) == ["Part1", "Part2"]
    actives = [d for d in docs if d["active"]]
    assert len(actives) == 1
    assert actives[0]["title"] == "Part2"
    active = kernel.dispatch("get_active_document")
    assert active.result["title"] == "Part2"


def test_expect_title_mismatch_wrong_document_zero_side_effects(kernel: Kernel):
    kernel.dispatch("new_part")  # Part1
    kernel.dispatch("new_part")  # Part2 active
    sv = kernel.state_version
    before_calls = list(kernel._backend.call_names())
    bad = kernel.dispatch(
        "start_sketch",
        {"plane": "Front Plane", "expect_title": "Part1"},
    )
    assert bad.ok is False
    assert bad.error.code == "WRONG_DOCUMENT"
    assert bad.error.side_effect == SideEffect.NONE
    assert bad.state_version == sv
    assert bad.error.context["expected_title"] == "Part1"
    assert bad.error.context["actual_title"] == "Part2"
    # No mutating backend call beyond the guard's active_document read
    after = kernel._backend.call_names()
    assert after == before_calls + ["active_document"]
    assert "begin_sketch" not in after


def test_expect_when_no_document_is_wrong_document(kernel: Kernel):
    r = kernel.dispatch(
        "start_sketch",
        {"plane": "Front Plane", "expect_title": "Part1"},
    )
    assert r.ok is False
    assert r.error.code == "WRONG_DOCUMENT"
    assert r.error.side_effect == SideEffect.NONE
    assert r.error.context["actual_title"] is None
    assert r.state_version == 0


def test_without_expect_keeps_no_active_document(kernel: Kernel):
    r = kernel.dispatch("start_sketch", {"plane": "Front Plane"})
    assert r.ok is False
    assert r.error.code == "NO_ACTIVE_DOCUMENT"


def test_expect_title_match_allows_write(kernel: Kernel):
    created = kernel.dispatch("new_part")
    title = created.result["title"]
    ok = kernel.dispatch(
        "start_sketch",
        {"plane": "Front Plane", "expect_title": title},
    )
    assert ok.ok
    assert kernel.state_version == 2


def test_saved_true_after_save_document(kernel: Kernel, tmp_path: Path):
    kernel.dispatch("new_part")
    path = str(tmp_path / "A.sldprt")
    saved = kernel.dispatch("save_document", {"path": path, "overwrite": True})
    assert saved.ok
    info = kernel.dispatch("get_active_document")
    assert info.result["saved"] is True
    assert info.result["path"]
    assert info.result["modified"] is False


def test_configuration_empty_on_drawing(kernel: Kernel):
    r = kernel.dispatch("new_drawing")
    assert r.ok
    assert r.result["configuration"] == ""
    assert r.result["doc_type"] == "drawing"


def test_all_mutating_tools_expose_expect_params():
    regs = core_registry()
    missing = []
    for spec in regs.all():
        if not spec.mutating:
            continue
        props = spec.input_schema.get("properties") or {}
        if "expect_title" not in props or "expect_path" not in props:
            missing.append(spec.name)
    assert not missing
