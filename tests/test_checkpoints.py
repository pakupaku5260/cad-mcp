"""F12 L1 checkpoints module (capture / find / restore / prune) — no design_run."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from cadmcp.backend.fake.backend import FakeBackend
from cadmcp.checkpoints import (
    capture,
    checkpoints_root,
    doc_key,
    find,
    prune,
    restore,
    snapshot_dir,
)
from cadmcp.errors import CadMcpError, SideEffect
from cadmcp.kernel import Kernel
from cadmcp.toolsets.core import core_registry
from cadmcp.transaction import fingerprint_digest


def _kernel(ws: Path) -> Kernel:
    return Kernel(core_registry(), FakeBackend(), workspace=ws)


def test_doc_key_and_dirs(tmp_path: Path):
    k = _kernel(tmp_path)
    k.dispatch("new_part", {})
    info = k._backend.active_document()
    key = doc_key(info)
    assert key.startswith("title:")
    root = checkpoints_root(tmp_path)
    assert root == tmp_path / ".cadmcp" / "checkpoints"
    folder = snapshot_dir(tmp_path, key)
    assert folder.parent == root
    assert len(folder.name) == 12


def test_capture_writes_copy_and_sidecar(tmp_path: Path):
    k = _kernel(tmp_path)
    k.dispatch("new_part", {})
    k.dispatch("start_sketch", {"plane": "Front Plane"})
    k.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 10, "y2": 10})
    k.dispatch("end_sketch", {})
    k.dispatch("extrude", {"depth": 5})
    info = k._backend.active_document()
    key = doc_key(info)
    entry = capture(
        k._backend, tmp_path, name="boss", index=3, state_version=k.state_version
    )
    assert entry["ok"] is True
    assert entry["name"] == "boss"
    assert entry["index"] == 3
    assert entry["bytes"] and entry["bytes"] > 0
    assert entry["fingerprint_digest"]
    assert entry["fingerprint_digest"] == fingerprint_digest(k._backend.fingerprint())
    dest = Path(entry["path"])
    assert dest.is_file()
    sidecar = dest.with_suffix(".json")
    assert sidecar.is_file()
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    assert meta["doc_key"] == key
    assert meta["fingerprint_digest"] == entry["fingerprint_digest"]
    assert meta["state_version"] == k.state_version
    assert meta["doc_type"] == "part"
    found = find(tmp_path, key, "boss")
    assert found is not None
    assert found["path"] == entry["path"]


def test_capture_failure_returns_ok_false(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    k = _kernel(tmp_path)
    k.dispatch("new_part", {})

    def _boom(_path):
        raise CadMcpError(
            "SAVE_FAILED",
            "Forced save failure",
            "Test inject",
        )

    monkeypatch.setattr(k._backend, "save_copy_as", _boom)
    entry = capture(k._backend, tmp_path, name="x", index=0, state_version=1)
    assert entry["ok"] is False
    assert entry["error_code"] == "SAVE_FAILED"
    assert "Forced save failure" in (entry["detail"] or "")
    assert entry["path"] is None
    # no leftover files under checkpoints root
    root = checkpoints_root(tmp_path)
    if root.exists():
        leftovers = [p for p in root.rglob("*") if p.is_file()]
        assert leftovers == []


def test_restore_opens_snapshot_copy(tmp_path: Path):
    k = _kernel(tmp_path)
    k.dispatch("new_part", {})
    k.dispatch("start_sketch", {"plane": "Front Plane"})
    k.dispatch("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 20, "y2": 10})
    k.dispatch("end_sketch", {})
    k.dispatch("extrude", {"depth": 8})
    info = k._backend.active_document()
    key = doc_key(info)
    entry = capture(k._backend, tmp_path, name="base", index=1, state_version=2)
    assert entry["ok"]
    # mutate further then restore
    k.dispatch("start_sketch", {"plane": "Top Plane"})
    meta = restore(k._backend, tmp_path, key=key, name="base")
    assert meta["name"] == "base"
    active = k._backend.active_document()
    assert active is not None
    assert active.doc_type == "part"
    assert Path(entry["path"]).name in (active.path or "")


def test_restore_open_failure_reports_unknown_side_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    k = _kernel(tmp_path)
    k.dispatch("new_part", {})
    info = k._backend.active_document()
    key = doc_key(info)
    assert capture(k._backend, tmp_path, name="base", index=0, state_version=1)["ok"]

    def _boom(_path):
        raise RuntimeError("open failed")

    monkeypatch.setattr(k._backend, "open_document", _boom)
    with pytest.raises(CadMcpError) as excinfo:
        restore(k._backend, tmp_path, key=key, name="base")
    # The active doc is already discarded: never report a clean no-op.
    assert excinfo.value.code == "ROLLBACK_FAILED"
    assert excinfo.value.side_effect is SideEffect.UNKNOWN


def test_prune_keeps_newest(tmp_path: Path):
    k = _kernel(tmp_path)
    k.dispatch("new_part", {})
    info = k._backend.active_document()
    key = doc_key(info)
    folder = snapshot_dir(tmp_path, key)
    folder.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for i in range(12):
        p = folder / f"{i:02d}_n{i}.sldprt"
        p.write_text(f"fake-{i}", encoding="utf-8")
        (folder / f"{i:02d}_n{i}.json").write_text(
            json.dumps({"name": f"n{i}", "path": str(p)}), encoding="utf-8"
        )
        paths.append(p)
        time.sleep(0.01)  # distinct mtimes
    before = sorted(p.name for p in folder.glob("*.sldprt"))
    assert len(before) == 12
    deleted = prune(tmp_path, key, keep=10)
    assert len(deleted) >= 2
    after = sorted(p.name for p in folder.glob("*.sldprt"))
    assert len(after) == 10
    # oldest two gone
    assert "00_n0.sldprt" not in after
    assert "01_n1.sldprt" not in after
