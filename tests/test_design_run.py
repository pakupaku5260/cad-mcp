"""F11 design_run: topology, params, precheck, stop_on_error, verify stubs."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cadmcp.backend.fake.backend import FakeBackend
from cadmcp.consistency.sequences.design import RUN_PART_SPEC
from cadmcp.design_run import substitute_params, topological_order
from cadmcp.errors import CadMcpError
from cadmcp.kernel import Kernel
from cadmcp.toolsets.core import core_registry


def _kernel(ws: Path) -> Kernel:
    return Kernel(core_registry(), FakeBackend(), workspace=ws)


def _write(ws: Path, name: str, data: dict) -> Path:
    path = ws / name
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_topological_order_stable_within_layer():
    # Declaration order: b (idx0), c (idx1), a (idx2). Both b and c depend on a.
    spec = {
        "features": [
            {"name": "b", "tool": "t", "args": {}, "depends_on": ["a"]},
            {"name": "c", "tool": "t", "args": {}, "depends_on": ["a"]},
            {"name": "a", "tool": "t", "args": {}},
        ]
    }
    names = [f["name"] for f in topological_order(spec)]
    # a first; then b before c (min original index among ready peers)
    assert names == ["a", "b", "c"]


def test_substitute_params_nested_list():
    params = {"d": 6.0, "t": 8}
    raw = {
        "depth": {"$param": "t"},
        "holes": [{"diameter": {"$param": "d"}}, 1],
    }
    out = substitute_params(raw, params, path="design_spec.features[0].args")
    assert out == {"depth": 8, "holes": [{"diameter": 6.0}, 1]}


def test_substitute_unknown_param_raises():
    with pytest.raises(CadMcpError) as ei:
        substitute_params({"x": {"$param": "missing"}}, {}, path="design_spec.features[1].args")
    assert ei.value.code == "INVALID_ARGUMENT"
    assert "design_spec.features[1].args" in ei.value.message
    assert "missing" in ei.value.message


def test_precheck_unknown_tool_zero_side_effects(tmp_path: Path):
    k = _kernel(tmp_path)
    before = k.state_version
    k.dispatch("new_part", {})
    after_new = k.state_version
    assert after_new > before
    spec = {
        "schema_version": 1,
        "kind": "part",
        "doc": {"title": "X", "units": "mm"},
        "features": [
            {"name": "a", "tool": "no_such_tool_zzz", "args": {}},
            {"name": "b", "tool": "extrude", "args": {"depth": 1}, "depends_on": ["a"]},
        ],
    }
    _write(tmp_path, "bad_tool.json", spec)
    r = k.dispatch("design_run", {"spec_path": "bad_tool.json"})
    assert not r.ok
    assert r.error is not None
    assert r.error.code == "INVALID_ARGUMENT"
    assert "no_such_tool_zzz" in r.error.message
    assert k.state_version == after_new  # no feature dispatches


def test_precheck_bad_param_zero_side_effects(tmp_path: Path):
    k = _kernel(tmp_path)
    k.dispatch("new_part", {})
    sv = k.state_version
    spec = {
        "schema_version": 1,
        "kind": "part",
        "doc": {"title": "X", "units": "mm"},
        "params": {},
        "features": [
            {
                "name": "sk",
                "tool": "start_sketch",
                "args": {"plane": {"$param": "missing_plane"}},
            }
        ],
    }
    _write(tmp_path, "bad_param.json", spec)
    r = k.dispatch("design_run", {"spec_path": "bad_param.json"})
    assert not r.ok
    assert r.error.code == "INVALID_ARGUMENT"
    assert "missing_plane" in r.error.message
    assert k.state_version == sv


def test_stop_on_error_true_halts(tmp_path: Path):
    k = _kernel(tmp_path)
    k.dispatch("new_part", {})
    spec = {
        "schema_version": 1,
        "kind": "part",
        "doc": {"title": "X", "units": "mm"},
        "features": [
            {
                "name": "sk",
                "tool": "start_sketch",
                "args": {"plane": "Front Plane"},
                "assert": {"ok": True},
            },
            {
                "name": "boom",
                "tool": "extrude",
                "args": {"depth": 10},
                "depends_on": ["sk"],
                "assert": {"ok": True},
            },
            {
                "name": "later",
                "tool": "end_sketch",
                "args": {},
                "depends_on": ["boom"],
            },
        ],
    }
    # extrude without ended sketch → fail; later must not run when stop_on_error
    _write(tmp_path, "halt.json", spec)
    r = k.dispatch("design_run", {"spec_path": "halt.json", "stop_on_error": True})
    assert r.ok  # outer ok (replay_recipe pattern)
    payload = r.result
    assert payload["ok"] is False
    assert payload["failed_step"]["name"] == "boom"
    names = [s["name"] for s in payload["steps"]]
    assert names == ["sk", "boom"]
    assert payload["checkpoints"]["snapshots"] == []
    assert payload["outputs"]["written"] == []


def test_stop_on_error_false_continues(tmp_path: Path):
    k = _kernel(tmp_path)
    k.dispatch("new_part", {})
    spec = {
        "schema_version": 1,
        "kind": "part",
        "doc": {"title": "X", "units": "mm"},
        "features": [
            {
                "name": "sk",
                "tool": "start_sketch",
                "args": {"plane": "Front Plane"},
            },
            {
                "name": "boom",
                "tool": "extrude",
                "args": {"depth": 10},
                "depends_on": ["sk"],
                "assert": {"ok": True},
            },
            {
                "name": "rect",
                "tool": "sketch_rectangle",
                "args": {"x1": 0, "y1": 0, "x2": 10, "y2": 10},
                "depends_on": ["sk"],
            },
        ],
    }
    _write(tmp_path, "cont.json", spec)
    r = k.dispatch("design_run", {"spec_path": "cont.json", "stop_on_error": False})
    assert r.ok
    payload = r.result
    assert payload["ok"] is False
    assert payload["failed_step"]["name"] == "boom"
    names = [s["name"] for s in payload["steps"]]
    assert names == ["sk", "boom", "rect"]


def test_assert_failure_sets_detail(tmp_path: Path):
    k = _kernel(tmp_path)
    k.dispatch("new_part", {})
    spec = {
        "schema_version": 1,
        "kind": "part",
        "doc": {"title": "X", "units": "mm"},
        "features": [
            {
                "name": "sk",
                "tool": "start_sketch",
                "args": {"plane": "Front Plane"},
                "assert": {"ok": False},  # expect failure but tool succeeds
            }
        ],
    }
    _write(tmp_path, "assert.json", spec)
    r = k.dispatch("design_run", {"spec_path": "assert.json"})
    assert r.ok
    payload = r.result
    assert payload["ok"] is False
    assert payload["steps"][0]["assert_ok"] is False
    assert "assert_detail" in payload["steps"][0]


def test_happy_path_with_verify_and_param(tmp_path: Path):
    k = _kernel(tmp_path)
    k.dispatch("new_part", {})
    _write(tmp_path, "run.json", RUN_PART_SPEC)
    r = k.dispatch("design_run", {"spec_path": "run.json"})
    assert r.ok
    payload = r.result
    assert payload["ok"] is True
    assert [s["name"] for s in payload["steps"]] == ["sk", "rect", "end", "boss"]
    assert all(s["ok"] for s in payload["steps"])
    assert payload["verification"] is not None
    assert payload["verification"]["ok"] is True
    assert payload["checkpoints"]["declared"] == ["boss"]
    assert payload["checkpoints"]["resumed_from"] is None
    assert payload["checkpoints"]["skipped"] == []
    assert len(payload["checkpoints"]["snapshots"]) == 1
    snap = payload["checkpoints"]["snapshots"][0]
    assert snap["ok"] is True
    assert snap["name"] == "boss"
    assert snap["fingerprint_digest"]
    assert snap["bytes"] and snap["bytes"] > 0
    assert Path(snap["path"]).is_file()
    assert Path(snap["path"]).with_suffix(".json").is_file()
    assert snap["state_version"] == payload["steps"][-1]["state_version"]
    assert payload["outputs"]["declared"] == ["step"]
    assert len(payload["outputs"]["written"]) == 1
    w = payload["outputs"]["written"][0]
    assert w["ok"] is True
    assert w["kind"] == "step"
    assert w["bytes"] and w["bytes"] > 0
    assert Path(w["path"]).is_file()


def test_failed_verification_turns_payload_not_ok(tmp_path: Path):
    k = _kernel(tmp_path)
    k.dispatch("new_part", {})
    spec = {
        "schema_version": 1,
        "kind": "part",
        "doc": {"title": "Empty", "units": "mm"},
        "features": [
            {"name": "sk", "tool": "start_sketch", "args": {"plane": "Front Plane"}}
        ],
        "verify": {"groups": ["geometry"], "thresholds": {}},
    }
    _write(tmp_path, "empty.json", spec)
    r = k.dispatch("design_run", {"spec_path": "empty.json"})
    assert r.ok  # outer envelope stays ok (replay_recipe pattern)
    payload = r.result
    assert all(s["ok"] for s in payload["steps"])
    assert payload["failed_step"] is None
    assert payload["verification"] is not None
    assert payload["verification"]["ok"] is False
    assert payload["verification"]["result"]["verification"]["status"] == "failed"
    assert payload["ok"] is False


def test_expect_title_mismatch_zero_side_effects(tmp_path: Path):
    k = _kernel(tmp_path)
    doc = k.dispatch("new_part", {})
    title = doc.result["title"]
    _write(tmp_path, "run.json", RUN_PART_SPEC)
    sv = k.state_version
    r = k.dispatch(
        "design_run",
        {"spec_path": "run.json", "expect_title": title + "_nope"},
    )
    assert not r.ok
    assert r.error is not None
    assert r.error.code == "WRONG_DOCUMENT"
    assert k.state_version == sv


def _three_feature_spec(*, checkpoint: str = "mid") -> dict:
    """sk → mid(rect, checkpoint) → boom(extrude, fails without end_sketch)."""
    return {
        "schema_version": 1,
        "kind": "part",
        "doc": {"title": "Resume plate", "units": "mm"},
        "features": [
            {
                "name": "sk",
                "tool": "start_sketch",
                "args": {"plane": "Front Plane"},
                "assert": {"ok": True},
            },
            {
                "name": "mid",
                "tool": "sketch_rectangle",
                "args": {"x1": 0, "y1": 0, "x2": 30, "y2": 15},
                "depends_on": ["sk"],
                "assert": {"ok": True},
            },
            {
                "name": "boom",
                "tool": "extrude",
                "args": {"depth": 5},
                "depends_on": ["mid"],
                "assert": {"ok": True},
            },
        ],
        "checkpoints": [checkpoint],
        "verify": {"groups": ["geometry"], "thresholds": {}},
    }


def test_resume_skips_completed_and_reruns_remaining(tmp_path: Path):
    """Fail after mid checkpoint; resume_from=mid skips sk+mid, re-runs boom."""
    k = _kernel(tmp_path)
    k.dispatch("new_part", {})
    spec = _three_feature_spec()
    _write(tmp_path, "resume.json", spec)
    r1 = k.dispatch("design_run", {"spec_path": "resume.json", "stop_on_error": True})
    assert r1.ok
    p1 = r1.result
    assert p1["ok"] is False
    assert p1["failed_step"]["name"] == "boom"
    assert [s["name"] for s in p1["steps"]] == ["sk", "mid", "boom"]
    assert len(p1["checkpoints"]["snapshots"]) == 1
    assert p1["checkpoints"]["snapshots"][0]["name"] == "mid"
    assert p1["checkpoints"]["snapshots"][0]["ok"] is True

    doc_before = k._backend.active_document()
    path_before = doc_before.path if doc_before else None
    r2 = k.dispatch(
        "design_run",
        {"spec_path": "resume.json", "stop_on_error": True, "resume_from": "mid"},
    )
    assert r2.ok
    p2 = r2.result
    assert p2["checkpoints"]["resumed_from"] == "mid"
    assert p2["checkpoints"]["skipped"] == ["sk", "mid"]
    assert [s["name"] for s in p2["steps"]] == ["boom"]
    assert p2["steps"][0]["index"] == 2  # topological position
    # boom still fails (open sketch, no end) — verification skipped
    assert p2["ok"] is False
    assert p2["failed_step"]["name"] == "boom"
    assert p2["verification"] is None
    # restored doc is the snapshot copy (path changed, inside .cadmcp/checkpoints)
    doc_after = k._backend.active_document()
    assert doc_after is not None
    assert doc_after.path != path_before
    assert ".cadmcp" in (doc_after.path or "")


def test_resume_success_remaining_with_verify(tmp_path: Path):
    """Checkpoint at end; first run fails on boss? Use end checkpoint then resume boss."""
    k = _kernel(tmp_path)
    k.dispatch("new_part", {})
    spec = {
        "schema_version": 1,
        "kind": "part",
        "doc": {"title": "Resume ok", "units": "mm"},
        "params": {"thickness": 10.0},
        "features": [
            {
                "name": "sk",
                "tool": "start_sketch",
                "args": {"plane": "Front Plane"},
                "assert": {"ok": True},
            },
            {
                "name": "rect",
                "tool": "sketch_rectangle",
                "args": {"x1": 0, "y1": 0, "x2": 40, "y2": 20},
                "depends_on": ["sk"],
                "assert": {"ok": True},
            },
            {
                "name": "end",
                "tool": "end_sketch",
                "args": {},
                "depends_on": ["rect"],
                "assert": {"ok": True},
            },
            {
                "name": "boss",
                "tool": "extrude",
                "args": {"depth": {"$param": "thickness"}},
                "depends_on": ["end"],
                "assert": {"ok": True},
            },
        ],
        "checkpoints": ["end"],
        "verify": {"groups": ["geometry"], "thresholds": {}},
    }
    _write(tmp_path, "resume_ok.json", spec)
    r1 = k.dispatch("design_run", {"spec_path": "resume_ok.json"})
    assert r1.result["ok"] is True
    assert r1.result["checkpoints"]["snapshots"][0]["name"] == "end"

    r2 = k.dispatch(
        "design_run",
        {"spec_path": "resume_ok.json", "resume_from": "end"},
    )
    assert r2.ok
    p2 = r2.result
    assert p2["checkpoints"]["resumed_from"] == "end"
    assert p2["checkpoints"]["skipped"] == ["sk", "rect", "end"]
    assert [s["name"] for s in p2["steps"]] == ["boss"]
    assert p2["steps"][0]["index"] == 3
    assert p2["verification"] is not None
    assert p2["verification"]["ok"] is True
    assert p2["ok"] is True


def test_resume_unknown_name_zero_side_effects(tmp_path: Path):
    k = _kernel(tmp_path)
    k.dispatch("new_part", {})
    _write(tmp_path, "run.json", RUN_PART_SPEC)
    # establish a real run so doc exists; then unknown resume must not mutate
    k.dispatch("design_run", {"spec_path": "run.json"})
    info = k._backend.active_document()
    path_before = info.path if info else None
    title_before = info.title if info else None
    sv = k.state_version
    r = k.dispatch(
        "design_run",
        {"spec_path": "run.json", "resume_from": "not_a_checkpoint"},
    )
    assert not r.ok
    assert r.error is not None
    assert r.error.code == "INVALID_ARGUMENT"
    assert k.state_version == sv
    info2 = k._backend.active_document()
    assert (info2.path if info2 else None) == path_before
    assert (info2.title if info2 else None) == title_before


def test_resume_missing_snapshot_zero_side_effects(tmp_path: Path):
    k = _kernel(tmp_path)
    k.dispatch("new_part", {})
    spec = {**RUN_PART_SPEC, "checkpoints": ["boss"]}
    _write(tmp_path, "missing_cp.json", spec)
    info = k._backend.active_document()
    path_before = info.path if info else None
    sv = k.state_version
    r = k.dispatch(
        "design_run",
        {"spec_path": "missing_cp.json", "resume_from": "boss"},
    )
    assert not r.ok
    assert r.error is not None
    assert r.error.code == "PATH_NOT_FOUND"
    assert k.state_version == sv
    info2 = k._backend.active_document()
    assert (info2.path if info2 else None) == path_before


def test_resume_kind_mismatch_zero_side_effects(tmp_path: Path):
    k = _kernel(tmp_path)
    k.dispatch("new_part", {})
    _write(tmp_path, "run.json", RUN_PART_SPEC)
    r0 = k.dispatch("design_run", {"spec_path": "run.json"})
    snap_path = Path(r0.result["checkpoints"]["snapshots"][0]["path"])
    sidecar = snap_path.with_suffix(".json")
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    meta["doc_type"] = "assembly"
    sidecar.write_text(json.dumps(meta), encoding="utf-8")
    info = k._backend.active_document()
    path_before = info.path if info else None
    sv = k.state_version
    r = k.dispatch(
        "design_run",
        {"spec_path": "run.json", "resume_from": "boss"},
    )
    assert not r.ok
    assert r.error is not None
    assert r.error.code == "INVALID_ARGUMENT"
    assert "doc_type" in r.error.message
    assert k.state_version == sv
    info2 = k._backend.active_document()
    assert (info2.path if info2 else None) == path_before


def test_snapshot_failure_does_not_fail_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    k = _kernel(tmp_path)
    k.dispatch("new_part", {})
    _write(tmp_path, "run.json", RUN_PART_SPEC)

    def _boom(_path):
        raise CadMcpError("SAVE_FAILED", "Injected capture failure", "Test")

    monkeypatch.setattr(k._backend, "save_copy_as", _boom)
    r = k.dispatch("design_run", {"spec_path": "run.json"})
    assert r.ok
    payload = r.result
    assert payload["ok"] is True  # verification still passes
    assert len(payload["checkpoints"]["snapshots"]) == 1
    bad = payload["checkpoints"]["snapshots"][0]
    assert bad["ok"] is False
    assert bad["error_code"] == "SAVE_FAILED"
    assert "Injected capture failure" in (bad["detail"] or "")


def _outputs_spec(*, kinds_paths: list[tuple[str, str]]) -> dict:
    spec = {
        "schema_version": 1,
        "kind": "part",
        "doc": {"title": "Out plate", "units": "mm"},
        "params": {"thickness": 10.0},
        "features": [
            {
                "name": "sk",
                "tool": "start_sketch",
                "args": {"plane": "Front Plane"},
                "assert": {"ok": True},
            },
            {
                "name": "rect",
                "tool": "sketch_rectangle",
                "args": {"x1": 0, "y1": 0, "x2": 40, "y2": 20},
                "depends_on": ["sk"],
                "assert": {"ok": True},
            },
            {
                "name": "end",
                "tool": "end_sketch",
                "args": {},
                "depends_on": ["rect"],
                "assert": {"ok": True},
            },
            {
                "name": "boss",
                "tool": "extrude",
                "args": {"depth": {"$param": "thickness"}},
                "depends_on": ["end"],
                "assert": {"ok": True},
            },
        ],
        "checkpoints": [],
        "verify": {"groups": ["geometry"], "thresholds": {}},
        "outputs": [{"kind": k, "path": p} for k, p in kinds_paths],
    }
    return spec


def test_outputs_write_step_and_stl(tmp_path: Path):
    k = _kernel(tmp_path)
    k.dispatch("new_part", {})
    spec = _outputs_spec(
        kinds_paths=[("step", "out/plate.step"), ("stl", "out/plate.stl")]
    )
    _write(tmp_path, "out.json", spec)
    r = k.dispatch("design_run", {"spec_path": "out.json"})
    assert r.ok
    payload = r.result
    assert payload["ok"] is True
    written = payload["outputs"]["written"]
    assert [w["kind"] for w in written] == ["step", "stl"]
    assert all(w["ok"] for w in written)
    assert all(w["bytes"] and w["bytes"] > 0 for w in written)
    assert (tmp_path / "out" / "plate.step").is_file()
    assert (tmp_path / "out" / "plate.stl").is_file()
    assert all(s["ok"] for s in payload["steps"])


def test_aborted_run_skips_export(tmp_path: Path):
    k = _kernel(tmp_path)
    k.dispatch("new_part", {})
    spec = {
        "schema_version": 1,
        "kind": "part",
        "doc": {"title": "Abort", "units": "mm"},
        "features": [
            {
                "name": "sk",
                "tool": "start_sketch",
                "args": {"plane": "Front Plane"},
                "assert": {"ok": True},
            },
            {
                "name": "boom",
                "tool": "extrude",
                "args": {"depth": 10},
                "depends_on": ["sk"],
                "assert": {"ok": True},
            },
        ],
        "outputs": [{"kind": "step", "path": "out/nope.step"}],
    }
    _write(tmp_path, "abort.json", spec)
    r = k.dispatch("design_run", {"spec_path": "abort.json", "stop_on_error": True})
    assert r.ok
    payload = r.result
    assert payload["ok"] is False
    assert payload["outputs"]["written"] == []
    assert not (tmp_path / "out" / "nope.step").exists()


def test_output_overwrite_denied_sets_payload_not_ok(tmp_path: Path):
    k = _kernel(tmp_path)
    k.dispatch("new_part", {})
    spec = _outputs_spec(kinds_paths=[("step", "out/exist.step")])
    _write(tmp_path, "ow.json", spec)
    (tmp_path / "out").mkdir(parents=True)
    (tmp_path / "out" / "exist.step").write_text("OLD", encoding="utf-8")
    r = k.dispatch("design_run", {"spec_path": "ow.json"})
    assert r.ok
    payload = r.result
    assert payload["ok"] is False
    assert all(s["ok"] for s in payload["steps"])  # steps stay green
    assert payload["verification"]["ok"] is True
    w = payload["outputs"]["written"][0]
    assert w["ok"] is False
    assert w["error_code"] == "PATH_OVERWRITE_DENIED"
    assert (tmp_path / "out" / "exist.step").read_text(encoding="utf-8") == "OLD"


def test_verify_failure_still_exports(tmp_path: Path):
    k = _kernel(tmp_path)
    k.dispatch("new_part", {})
    spec = {
        "schema_version": 1,
        "kind": "part",
        "doc": {"title": "Empty export", "units": "mm"},
        "features": [
            {"name": "sk", "tool": "start_sketch", "args": {"plane": "Front Plane"}}
        ],
        "verify": {"groups": ["geometry"], "thresholds": {}},
        "outputs": [{"kind": "step", "path": "out/empty.step"}],
    }
    _write(tmp_path, "ve.json", spec)
    r = k.dispatch("design_run", {"spec_path": "ve.json"})
    assert r.ok
    payload = r.result
    assert payload["verification"]["ok"] is False
    assert payload["outputs"]["written"][0]["ok"] is True
    assert payload["ok"] is False  # verify failed
    assert (tmp_path / "out" / "empty.step").is_file()


def _variant_plate_spec() -> dict:
    return {
        "schema_version": 1,
        "kind": "part",
        "doc": {"title": "Variant plate", "units": "mm"},
        "params": {"thickness": 10.0, "width": 40.0},
        "variants": {
            "thick": {"thickness": 20.0},
            "narrow": {"width": 15.0},
        },
        "features": [
            {
                "name": "sk",
                "tool": "start_sketch",
                "args": {"plane": "Front Plane"},
                "assert": {"ok": True},
            },
            {
                "name": "rect",
                "tool": "sketch_rectangle",
                "args": {"x1": 0, "y1": 0, "x2": {"$param": "width"}, "y2": 20},
                "depends_on": ["sk"],
                "assert": {"ok": True},
            },
            {
                "name": "end",
                "tool": "end_sketch",
                "args": {},
                "depends_on": ["rect"],
                "assert": {"ok": True},
            },
            {
                "name": "boss",
                "tool": "extrude",
                "args": {"depth": {"$param": "thickness"}},
                "depends_on": ["end"],
                "assert": {"ok": True},
            },
        ],
        "verify": {"groups": ["geometry"], "thresholds": {}},
        "outputs": [],
    }


def test_variant_overrides_base_params(tmp_path: Path):
    k = _kernel(tmp_path)
    k.dispatch("new_part", {})
    _write(tmp_path, "v.json", _variant_plate_spec())
    r = k.dispatch("design_run", {"spec_path": "v.json", "variant": "thick"})
    assert r.ok
    payload = r.result
    assert payload["ok"] is True
    assert "variant" not in payload
    depths = [c[1].get("depth") for c in k._backend.calls if c[0] == "extrude_blind"]
    assert depths, k._backend.call_names()
    assert abs(float(depths[-1]) - 0.02) < 1e-9  # 20 mm → SI meters


def test_variant_partial_keeps_base_keys(tmp_path: Path):
    k = _kernel(tmp_path)
    k.dispatch("new_part", {})
    _write(tmp_path, "v.json", _variant_plate_spec())
    r = k.dispatch("design_run", {"spec_path": "v.json", "variant": "narrow"})
    assert r.ok
    assert r.result["ok"] is True
    rect_calls = [c[1] for c in k._backend.calls if c[0] == "draw_rectangle"]
    assert rect_calls
    # width=15 mm → 0.015 m; thickness stays base 10 mm on extrude
    assert abs(float(rect_calls[-1]["x2"]) - 0.015) < 1e-9
    depths = [c[1].get("depth") for c in k._backend.calls if c[0] == "extrude_blind"]
    assert abs(float(depths[-1]) - 0.01) < 1e-9


def test_unknown_variant_zero_side_effects(tmp_path: Path):
    k = _kernel(tmp_path)
    k.dispatch("new_part", {})
    sv = k.state_version
    _write(tmp_path, "v.json", _variant_plate_spec())
    r = k.dispatch("design_run", {"spec_path": "v.json", "variant": "missing"})
    assert not r.ok
    assert r.error is not None
    assert r.error.code == "INVALID_ARGUMENT"
    assert "unknown variant" in r.error.message
    assert k.state_version == sv


def test_variant_without_variants_table_zero_side_effects(tmp_path: Path):
    k = _kernel(tmp_path)
    k.dispatch("new_part", {})
    sv = k.state_version
    _write(tmp_path, "run.json", RUN_PART_SPEC)  # no variants
    r = k.dispatch("design_run", {"spec_path": "run.json", "variant": "thick"})
    assert not r.ok
    assert r.error is not None
    assert r.error.code == "INVALID_ARGUMENT"
    assert k.state_version == sv


def test_omit_variant_keeps_base_behaviour(tmp_path: Path):
    k = _kernel(tmp_path)
    k.dispatch("new_part", {})
    _write(tmp_path, "v.json", _variant_plate_spec())
    r = k.dispatch("design_run", {"spec_path": "v.json"})
    assert r.ok
    assert r.result["ok"] is True
    assert set(r.result) == {
        "ok",
        "spec",
        "steps",
        "failed_step",
        "verification",
        "checkpoints",
        "outputs",
    }
