"""F10 DesignSpec load/validate + design_spec_validate tool."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cadmcp.consistency.sequences.design import VALID_PART_SPEC
from cadmcp.design_spec import load_design_spec, select_variant
from cadmcp.errors import CadMcpError
from cadmcp.kernel import Kernel
from cadmcp.toolsets.core import core_registry


def _write(ws: Path, name: str, data: dict) -> Path:
    path = ws / name
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def _kernel(ws: Path) -> Kernel:
    from cadmcp.backend.fake.backend import FakeBackend

    return Kernel(core_registry(), FakeBackend(), workspace=ws)


def test_valid_spec_loads(tmp_path: Path):
    path = _write(tmp_path, "ok.json", VALID_PART_SPEC)
    spec = load_design_spec(path)
    assert spec["schema_version"] == 1
    assert spec["kind"] == "part"
    assert [f["name"] for f in spec["features"]] == ["base", "holes"]
    assert spec["checkpoints"] == ["base"]


def test_missing_file(tmp_path: Path):
    with pytest.raises(CadMcpError) as ei:
        load_design_spec(tmp_path / "nope.json")
    assert ei.value.code == "PATH_NOT_FOUND"


@pytest.mark.parametrize(
    "mutate,path_substr",
    [
        (lambda d: d.pop("schema_version"), "schema_version"),
        (lambda d: d.__setitem__("schema_version", 99), "schema_version"),
        (lambda d: d.__setitem__("kind", "solid"), "kind"),
        (lambda d: d["doc"].__setitem__("title", ""), "doc.title"),
        (lambda d: d["doc"].__setitem__("units", "cm"), "doc.units"),
        (lambda d: d.__setitem__("params", {"x": {"nested": 1}}), "params.x"),
        (lambda d: d.__setitem__("features", []), "features"),
        (
            lambda d: (
                d["features"].append(
                    {"name": "base", "tool": "extrude", "args": {}}
                )
            ),
            "name duplicates",
        ),
        (
            lambda d: d["features"][1].__setitem__("depends_on", ["missing"]),
            "depends_on",
        ),
        (
            lambda d: (
                d["features"][0].__setitem__("depends_on", ["holes"]),
                d["features"][1].__setitem__("depends_on", ["base"]),
            ),
            "cycle",
        ),
        (
            lambda d: d.__setitem__("checkpoints", ["holes", "base"]),
            "checkpoints",
        ),
        (
            lambda d: d["verify"].__setitem__("groups", ["nope"]),
            "verify.groups",
        ),
        (
            lambda d: d["outputs"].__setitem__(0, {"kind": "iges", "path": "a.iges"}),
            "outputs[0].kind",
        ),
        (
            lambda d: d["features"][0].__setitem__("assert", {"nope": 1}),
            "assert",
        ),
    ],
)
def test_invalid_rules(tmp_path: Path, mutate, path_substr: str):
    data = json.loads(json.dumps(VALID_PART_SPEC))
    mutate(data)
    path = _write(tmp_path, "bad.json", data)
    with pytest.raises(CadMcpError) as ei:
        load_design_spec(path)
    assert ei.value.code == "INVALID_ARGUMENT"
    assert path_substr in ei.value.message


def test_tool_validate_ok(tmp_path: Path):
    _write(tmp_path, "ok.json", VALID_PART_SPEC)
    k = _kernel(tmp_path)
    r = k.dispatch("design_spec_validate", {"spec_path": "ok.json"})
    assert r.ok
    assert r.result["ok"] is True
    assert r.result["spec"]["feature_count"] == 2
    assert r.result["spec"]["features"] == ["base", "holes"]
    assert "warnings" not in r.result


def test_tool_path_outside_sandbox(tmp_path: Path):
    k = _kernel(tmp_path)
    r = k.dispatch("design_spec_validate", {"spec_path": "../escape.json"})
    assert not r.ok
    assert r.error is not None
    assert r.error.code == "PATH_OUTSIDE_SANDBOX"


def test_tool_path_not_found(tmp_path: Path):
    k = _kernel(tmp_path)
    r = k.dispatch("design_spec_validate", {"spec_path": "missing.json"})
    assert not r.ok
    assert r.error is not None
    assert r.error.code == "PATH_NOT_FOUND"


def test_design_in_part_profile():
    from cadmcp.registry import TOOLSET_PROFILES

    assert "design" in TOOLSET_PROFILES["part"]
    assert "design" in TOOLSET_PROFILES["full"]
    assert "design" not in TOOLSET_PROFILES["assembly"]
    assert "task" in TOOLSET_PROFILES["part"]
    assert "task" in TOOLSET_PROFILES["full"]


def test_output_kind_suffix_mismatch(tmp_path: Path):
    bad = dict(VALID_PART_SPEC)
    bad["outputs"] = [{"kind": "step", "path": "out/base.stl"}]
    path = _write(tmp_path, "bad_ext.json", bad)
    with pytest.raises(CadMcpError) as ei:
        load_design_spec(path)
    assert ei.value.code == "INVALID_ARGUMENT"
    assert "design_spec.outputs[0]" in ei.value.message


def test_output_stp_accepted_for_step(tmp_path: Path):
    ok = dict(VALID_PART_SPEC)
    ok["outputs"] = [{"kind": "step", "path": "out/base.stp"}]
    path = _write(tmp_path, "stp.json", ok)
    spec = load_design_spec(path)
    assert spec["outputs"][0]["path"].endswith(".stp")


def test_variants_default_empty(tmp_path: Path):
    path = _write(tmp_path, "ok.json", VALID_PART_SPEC)
    spec = load_design_spec(path)
    assert spec["variants"] == {}
    assert select_variant(spec, None) == spec["params"]


def test_variants_load_and_select(tmp_path: Path):
    data = dict(VALID_PART_SPEC)
    data["variants"] = {
        "thick": {"thickness": 12.0},
        "thin": {"thickness": 4.0, "extra": True},
    }
    path = _write(tmp_path, "v.json", data)
    spec = load_design_spec(path)
    assert set(spec["variants"]) == {"thick", "thin"}
    merged = select_variant(spec, "thick")
    assert merged["thickness"] == 12.0
    # partial override keeps other base keys if any; base only has thickness
    partial = select_variant(spec, "thin")
    assert partial["thickness"] == 4.0
    assert partial["extra"] is True


def test_variants_scalar_error_path(tmp_path: Path):
    data = dict(VALID_PART_SPEC)
    data["variants"] = {"bad": {"thickness": [1, 2]}}
    path = _write(tmp_path, "bad_v.json", data)
    with pytest.raises(CadMcpError) as ei:
        load_design_spec(path)
    assert ei.value.code == "INVALID_ARGUMENT"
    assert "design_spec.variants.bad.thickness" in ei.value.message


def test_select_variant_unknown_raises():
    spec = {
        "params": {"thickness": 8.0},
        "variants": {"thick": {"thickness": 12.0}},
    }
    with pytest.raises(CadMcpError) as ei:
        select_variant(spec, "nope")
    assert ei.value.code == "INVALID_ARGUMENT"
    assert "unknown variant" in ei.value.message
    assert "thick" in ei.value.message


def test_verify_groups_single_source():
    from cadmcp.toolsets import verification as vt
    from cadmcp.verification import VERIFY_GROUPS

    assert vt.VERIFY_GROUPS is VERIFY_GROUPS


def test_assert_keys_single_source():
    from cadmcp.recipe import ASSERT_KEYS

    assert ASSERT_KEYS == frozenset({"ok", "error_code", "result_keys", "delta_changed"})
    from cadmcp import design_spec as mod

    assert "ASSERT_KEYS" in mod.load_design_spec.__globals__
    assert mod.load_design_spec.__globals__["ASSERT_KEYS"] is ASSERT_KEYS
