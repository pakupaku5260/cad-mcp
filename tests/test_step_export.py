"""STEP properties, sidecar meta, AP paths, and export_batch."""
from __future__ import annotations

import json
from pathlib import Path

from cadmcp.backend.step_schema import detect_step_ap
from cadmcp.kernel import Kernel


def _cube(kernel: Kernel, size: float = 20.0) -> None:
    assert kernel.dispatch("new_part", {}).ok
    assert kernel.dispatch("start_sketch", {"plane": "Front Plane"}).ok
    assert kernel.dispatch(
        "sketch_rectangle", {"x1": 0, "y1": 0, "x2": size, "y2": size}
    ).ok
    assert kernel.dispatch("end_sketch", {}).ok
    assert kernel.dispatch("extrude", {"depth": size}).ok


def test_set_get_properties_roundtrip(kernel: Kernel):
    _cube(kernel)
    written = kernel.dispatch(
        "set_properties",
        {
            "entries": [
                {"key": "PartNo", "value": "P-100"},
                {"key": "Material", "value": "Al6061"},
                {"key": "pn", "value": "P-100b"},  # alias → PartNo
            ]
        },
    )
    assert written.ok, written.error
    assert written.result["written"]["PartNo"] == "P-100b"
    got = kernel.dispatch("get_properties", {})
    assert got.ok
    props = got.result["properties"]
    assert props["PartNo"] == "P-100b"
    assert props["Material"] == "Al6061"
    assert props["THREAD_SPEC"] == ""
    subset = kernel.dispatch("get_properties", {"keys": ["PartNo", "Revision"]})
    assert subset.ok and set(subset.result["properties"]) == {"PartNo", "Revision"}


def test_export_write_meta_includes_properties(kernel: Kernel, workspace: Path):
    _cube(kernel)
    assert kernel.dispatch(
        "set_properties",
        {
            "entries": [
                {"key": "PartNo", "value": "BOX-1"},
                {"key": "Revision", "value": "A"},
                {"key": "THREAD_SPEC", "value": "M6x1-6g"},
            ]
        },
    ).ok
    r = kernel.dispatch("export", {"path": "box.step", "step_ap": 214})
    assert r.ok, r.error
    assert r.result["step_ap"] == 214
    meta_path = Path(r.result["meta"])
    assert meta_path.is_file()
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    assert payload["step_ap"] == 214
    assert payload["step_ap_verified"] is True
    assert payload["export_path"] == "SaveAs3"
    assert payload["properties"]["PartNo"] == "BOX-1"
    assert payload["properties"]["THREAD_SPEC"] == "M6x1-6g"
    assert detect_step_ap(workspace / "box.step") == 214


def test_export_write_meta_false_skips_sidecar(kernel: Kernel, workspace: Path):
    _cube(kernel)
    r = kernel.dispatch("export", {"path": "nometa.step", "write_meta": False})
    assert r.ok and "meta" not in r.result
    assert not (workspace / "nometa.step.meta.json").exists()


def test_export_batch_two_parts_and_stop_on_fail(kernel: Kernel, workspace: Path):
    _cube(kernel)
    assert kernel.dispatch("save_document", {"path": "p1.sldprt"}).ok
    kernel.dispatch("close_document", {"discard": True})
    _cube(kernel, 15.0)
    assert kernel.dispatch(
        "set_properties", {"entries": [{"key": "PartNo", "value": "P2"}]}
    ).ok
    assert kernel.dispatch("save_document", {"path": "p2.sldprt"}).ok
    kernel.dispatch("close_document", {"discard": True})

    ok = kernel.dispatch(
        "export_batch",
        {
            "items": [
                {"path": "p1.sldprt", "out": "p1.step", "step_ap": 214},
                {"path": "p2.sldprt", "out": "p2.step", "step_ap": 203},
            ],
            "overwrite": True,
        },
    )
    assert ok.ok and ok.result["ok"] is True and ok.result["count"] == 2
    assert (workspace / "p1.step.meta.json").is_file()
    assert (workspace / "p2.step.meta.json").is_file()
    assert detect_step_ap(workspace / "p2.step") == 203

    fail = kernel.dispatch(
        "export_batch",
        {
            "items": [
                {"path": "p1.sldprt", "out": "again1.step"},
                {"path": "missing.sldprt", "out": "no.step"},
                {"path": "p2.sldprt", "out": "again2.step"},
            ],
            "overwrite": True,
        },
    )
    assert fail.ok  # tool itself returns payload
    body = fail.result
    assert body["ok"] is False
    assert body["count"] == 2  # first ok + second failed; third not run
    assert body["results"][0]["ok"] is True
    assert body["results"][1]["ok"] is False
    assert not (workspace / "again2.step").exists()
