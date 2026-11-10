"""ComBackend document domain offline tests: stub COM for templates, open/save/close, and error mapping."""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from cadmcp.backend.solidworks._helpers import _as_bbox6, _union_bbox6, feature_kind_from_sw
from cadmcp.backend.solidworks.backend import ComBackend
from cadmcp.errors import CadMcpError, SideEffect, fail


class _Doc:
    def __init__(
        self,
        *,
        title: str = "Part1",
        path: str = "",
        modified: bool = False,
        doc_type: int = 1,
        save_result: object = 0,
    ) -> None:
        self.title = title
        self.path = path
        self.modified = modified
        self.doc_type = doc_type
        self.save_result = save_result
        self.saved_path: str | None = None

    def GetTitle(self):  # noqa: N802
        return self.title

    def GetPathName(self):  # noqa: N802
        return self.path

    def GetSaveFlag(self):  # noqa: N802
        return self.modified

    def GetType(self):  # noqa: N802
        return self.doc_type

    def SaveAs3(self, path, options, export_data):  # noqa: N802
        self.saved_path = str(path)
        return self.save_result


class _Sw:
    def __init__(
        self,
        *,
        folder: Path | None = None,
        template: str | None = None,
        new_doc: _Doc | None = None,
        active_doc: _Doc | None = None,
        open6_result: _Doc | None = None,
        open6_error: Exception | None = None,
        open_result: _Doc | None = None,
        open_error: Exception | None = None,
    ) -> None:
        self.folder = folder
        self.template = template
        self.new_doc = new_doc or _Doc()
        self.active_doc = active_doc
        self.open6_result = open6_result
        self.open6_error = open6_error
        self.open_result = open_result
        self.open_error = open_error
        self.new_template: str | None = None
        self.closed_title: str | None = None
        self.RevisionNumber = "33.0"

    def GetUserPreferenceStringValue(self, code):  # noqa: N802
        assert code == 6
        return str(self.folder or "")

    def GetDocumentTemplate(self, *args):  # noqa: N802
        return self.template

    def NewDocument(self, template, paper_size, options, configuration):  # noqa: N802
        self.new_template = str(template)
        return self.new_doc

    def OpenDoc6(self, path, doc_type, options, configuration, errors, warnings):  # noqa: N802
        if self.open6_error is not None:
            raise self.open6_error
        return self.open6_result

    def OpenDoc(self, path, doc_type):  # noqa: N802
        if self.open_error is not None:
            raise self.open_error
        return self.open_result

    @property
    def ActiveDoc(self):  # noqa: N802
        return self.active_doc

    def CloseDoc(self, title):  # noqa: N802
        self.closed_title = str(title)
        self.active_doc = None     # SW close clears active doc


def _backend(sw: _Sw) -> ComBackend:
    backend = ComBackend()
    backend.sw = sw
    backend._ready.set()
    backend._call = lambda fn: fn()  # type: ignore[method-assign]
    return backend


def test_revision_reads_com_value():
    assert _backend(_Sw()).revision() == "33.0"


def test_new_part_uses_explicit_template(tmp_path: Path):
    tpl = tmp_path / "custom.prtdot"
    tpl.write_text("", encoding="utf-8")
    sw = _Sw()
    info = _backend(sw).new_part(str(tpl))
    assert sw.new_template == str(tpl)
    assert info.title == "Part1"
    assert info.doc_type == "part"


def test_new_part_falls_back_to_preference_folder(tmp_path: Path):
    tpl = tmp_path / "gb_part.prtdot"
    tpl.write_text("", encoding="utf-8")
    sw = _Sw(folder=tmp_path, template=str(tmp_path / "missing.prtdot"))
    _backend(sw).new_part()
    assert sw.new_template == str(tpl)


def test_new_part_without_template_is_open_failed(tmp_path: Path):
    sw = _Sw(folder=tmp_path)
    with pytest.raises(CadMcpError) as exc:
        _backend(sw).new_part()
    assert exc.value.code == "OPEN_FAILED"
    assert exc.value.side_effect is SideEffect.NONE


def test_open_document_falls_back_to_opendoc(tmp_path: Path):
    doc = _Doc(title="Assembly1", path=str(tmp_path / "a.sldasm"), doc_type=2)
    sw = _Sw(open6_error=RuntimeError("类型不匹配"), open_result=doc)
    info = _backend(sw).open_document(tmp_path / "a.sldasm")
    assert info.title == "Assembly1"
    assert info.doc_type == "assembly"


def test_open_document_reports_both_failures(tmp_path: Path):
    sw = _Sw(open6_error=RuntimeError("OpenDoc6 失败"), open_error=RuntimeError("OpenDoc 失败"))
    with pytest.raises(CadMcpError) as exc:
        _backend(sw).open_document(tmp_path / "a.sldprt")
    assert exc.value.code == "OPEN_FAILED"
    assert "OpenDoc6 失败" in exc.value.message
    assert "OpenDoc 失败" in exc.value.message


@pytest.mark.parametrize("result", [0, True])
def test_save_as_accepts_success_values(tmp_path: Path, result):
    doc = _Doc(save_result=result)
    sw = _Sw(active_doc=doc)
    target = tmp_path / "part.sldprt"
    _backend(sw).save_as(target)
    assert doc.saved_path == str(target)


@pytest.mark.parametrize("result", [1, False])
def test_save_as_rejects_failure_values(tmp_path: Path, result):
    sw = _Sw(active_doc=_Doc(save_result=result))
    with pytest.raises(CadMcpError) as exc:
        _backend(sw).save_as(tmp_path / "part.sldprt")
    assert exc.value.code == "SAVE_FAILED"


def test_save_as_without_active_document():
    with pytest.raises(CadMcpError) as exc:
        _backend(_Sw()).save_as(Path("x.sldprt"))
    assert exc.value.code == "NO_ACTIVE_DOCUMENT"


def test_active_document_derives_type_and_close_uses_title():
    doc = _Doc(title="Drawing1", doc_type=3)
    sw = _Sw(active_doc=doc)
    backend = _backend(sw)
    info = backend.active_document()
    assert info is not None
    assert info.doc_type == "drawing"
    backend.close_document(discard=True)
    assert sw.closed_title == "Drawing1"


def test_close_document_without_active_document():
    with pytest.raises(CadMcpError) as exc:
        _backend(_Sw()).close_document(discard=True)
    assert exc.value.code == "NO_ACTIVE_DOCUMENT"


def test_call_before_ready_maps_attach_failed():
    backend = ComBackend()
    with pytest.raises(CadMcpError) as exc:
        backend.revision()
    assert exc.value.code == "COM_ATTACH_FAILED"
    assert exc.value.side_effect is SideEffect.NONE


def test_attach_failure_is_not_cached(monkeypatch):
    monkeypatch.setattr(ComBackend, "_instance", None)

    def _boom(self):
        raise fail("COM_ATTACH_FAILED", "boom", "retry")

    monkeypatch.setattr(ComBackend, "_start_sta", _boom)
    with pytest.raises(CadMcpError):
        ComBackend.attach()
    assert ComBackend._instance is None


def test_map_error_preserves_cadmcperror_and_maps_generic():
    backend = ComBackend()
    original = fail("OPEN_FAILED", "x", "y")
    assert backend._map_error(original) is original

    mapped = backend._map_error(RuntimeError("OpenDoc6 boom"))
    assert mapped.code == "OPEN_FAILED"
    assert mapped.side_effect is SideEffect.APPLIED


def test_unimplemented_query_domains_still_raise():
    backend = _backend(_Sw())
    assert backend.list_planes()
    # queries need active doc
    with pytest.raises(CadMcpError) as exc:
        backend.fingerprint()
    assert exc.value.code == "NO_ACTIVE_DOCUMENT"


def test_close_document_raises_when_doc_stays_open():
    doc = _Doc(title="Part1", doc_type=1)

    class _StuckSw(_Sw):
        def CloseDoc(self, title):  # noqa: N802
            self.closed_title = str(title)  # record close, keep active_doc

    sw = _StuckSw(active_doc=doc)
    with pytest.raises(CadMcpError) as ei:
        _backend(sw).close_document(discard=True)
    assert ei.value.code == "COM_CALL_FAILED"
    assert sw.active_doc is doc


def test_close_document_retries_with_path_when_title_fails(tmp_path: Path):
    doc = _Doc(title="a", path=str(tmp_path / "a.sldprt"))

    class _PathOnlySw(_Sw):
        def CloseDoc(self, title):  # noqa: N802
            self.closed_title = str(title)
            if str(title) == doc.path:  # full path only
                self.active_doc = None

    sw = _PathOnlySw(active_doc=doc)
    _backend(sw).close_document(discard=True)
    assert sw.closed_title == doc.path
    assert sw.active_doc is None


class _NoModal:
    def scan(self):
        return []


def _real_call_backend(monkeypatch) -> ComBackend:
    """Keep real _call (_backend() replaces it)."""
    monkeypatch.setattr("cadmcp.backend.solidworks.sta.Win32DialogProbe", _NoModal)
    backend = ComBackend()
    backend.sw = object()
    backend._ready.set()
    return backend


def _serve_once(backend: ComBackend, kind: str, value: object) -> None:
    """Simulate STA: one task, return (kind, value)."""
    def run() -> None:
        _fn, q = backend._queue.get(timeout=5)
        q.put((kind, value))

    threading.Thread(target=run, daemon=True).start()


def test_call_is_reentrant_on_sta_thread(monkeypatch):
    """Regression: reentrant _call on STA must not deadlock."""
    backend = _real_call_backend(monkeypatch)
    backend._thread = threading.current_thread()
    assert backend._call(lambda: 42) == 42


def test_call_maps_server_gone_to_sw_not_running(monkeypatch):
    class _Gone(Exception):
        hresult = -2147417848  # RPC_E_DISCONNECTED

    backend = _real_call_backend(monkeypatch)
    _serve_once(backend, "err", _Gone())
    with pytest.raises(CadMcpError) as exc:
        backend._call(lambda: None)
    assert exc.value.code == "SW_NOT_RUNNING"


def test_call_rejects_when_modal_dialog_present(monkeypatch):
    modal = SimpleNamespace(title="警告", class_name="#32770", rect=(0, 0, 1, 1), modal=True)

    class _Blocked:
        def scan(self):
            return [modal]

    backend = _real_call_backend(monkeypatch)
    monkeypatch.setattr("cadmcp.backend.solidworks.sta.Win32DialogProbe", _Blocked)
    with pytest.raises(CadMcpError) as exc:
        backend._call(lambda: None)
    assert exc.value.code == "EXEC_BLOCKED"
    assert exc.value.side_effect is SideEffect.NONE  # blocked before dispatch


def test_as_bbox6_accepts_six_and_eight_corners():
    assert _as_bbox6((-1, 0, 0, 1, 2, 3)) == (-1.0, 0.0, 0.0, 1.0, 2.0, 3.0)
    assert _as_bbox6((True, [0, 0, 0, 1, 1, 1])) == (0.0, 0.0, 0.0, 1.0, 1.0, 1.0)
    corners = (
        0, 0, 0, 1, 0, 0, 0, 2, 0, 1, 2, 0,
        0, 0, 3, 1, 0, 3, 0, 2, 3, 1, 2, 3,
    )
    assert _as_bbox6(corners) == (0.0, 0.0, 0.0, 1.0, 2.0, 3.0)
    assert _as_bbox6(None) is None
    assert _as_bbox6((1, 2, 3)) is None
    assert _union_bbox6([(-1, 0, 0, 1, 1, 1), (0, -2, 0, 2, 0, 4)]) == (-1, -2, 0, 2, 1, 4)


def test_feature_kind_maps_ice_cut_extrude():
    assert feature_kind_from_sw("ICE") == "extrude_cut"
    assert feature_kind_from_sw("Cut") == "extrude_cut"
    assert feature_kind_from_sw("Extrusion") == "extrude"
    assert feature_kind_from_sw("") == "unknown"


class _PatternHarness:
    """pattern_component dispatch only."""

    def __init__(self) -> None:
        self.sw = SimpleNamespace(ActiveDoc=object())
        self.checked = False

    def _require_assembly_doc(self, asm, message) -> None:
        self.checked = True

    def _call(self, fn, timeout=None):
        return fn()

    def _linear_pattern_component(self, asm, name, count, offset):
        return ("linear", name, count, offset)

    def _circular_pattern_component(self, asm, name, count, axis, about):
        return ("circular", name, count, axis, about)


def test_pattern_component_linear_and_circular_dispatch():
    """Regression: missing linear_pattern_offset_m → NameError on COM path."""
    from cadmcp.backend.solidworks.assembly.component import ComponentMixin

    harness = _PatternHarness()
    assert ComponentMixin.pattern_component(harness, "seed", 3, dx_m=0.01) == (
        "linear",
        "seed",
        3,
        (0.01, 0.0, 0.0),
    )
    assert ComponentMixin.pattern_component(harness, "seed", 4, axis="+z") == (
        "circular",
        "seed",
        4,
        "+z",
        "world",
    )
    assert harness.checked is True

    with pytest.raises(CadMcpError) as exc:
        ComponentMixin.pattern_component(harness, "seed", 4, axis="+z", dx_m=0.01)
    assert exc.value.code == "INVALID_ARGUMENT"
