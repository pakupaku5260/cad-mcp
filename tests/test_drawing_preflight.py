"""F18: DrawingSpec text preflight."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cadmcp.backend.fake import FakeBackend
from cadmcp.drawing_preflight import (
    ASSUMPTIONS,
    PREFLIGHT_CHECKS,
    assess,
    evaluate_preflight,
    evaluate_spec,
)
from cadmcp.errors import CadMcpError
from cadmcp.kernel import Kernel
from cadmcp.toolsets.core import core_registry
from cadmcp.units import UnitContext


def _kernel(tmp_path: Path) -> Kernel:
    return Kernel(
        backend=FakeBackend(),
        units=UnitContext("mm"),
        workspace=tmp_path,
        registry=core_registry(),
    )


def _write(tmp_path: Path, name: str, spec: dict) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    return path


def _base_l3(**overrides) -> dict:
    spec = {
        "model": "plate.sldprt",
        "sheets": [
            {
                "name": "Sheet1",
                "paper": "A4",
                "scale": [1, 1],
                "views": [{"orient": "front"}],
            }
        ],
        "title_block": {"PartNo": "P-001"},
        "gdts": [
            {
                "kind": "gdt",
                "symbol": "position",
                "tolerance": "0.1",
                "datums": ["A"],
            }
        ],
        "bom": {"type": "top"},
    }
    spec.update(overrides)
    return spec


def test_preflight_checks_count_and_names():
    assert len(PREFLIGHT_CHECKS) == 8
    assert [c.name for c in PREFLIGHT_CHECKS] == [
        "spec_loadable",
        "has_sheets",
        "has_views",
        "valid_view_orientations",
        "valid_gdt_symbols",
        "valid_bom_types",
        "title_block_keys_wellformed",
        "no_duplicate_sheet_names",
    ]


def test_pass_full_l3_spec(tmp_path: Path):
    path = _write(tmp_path, "ok.json", _base_l3())
    checks, skipped = evaluate_preflight(path)
    by_name = {c.name: c for c in checks}
    assert by_name["spec_loadable"].ok
    assert by_name["has_sheets"].ok
    assert by_name["has_views"].ok
    assert by_name["valid_view_orientations"].ok
    assert by_name["valid_gdt_symbols"].ok
    assert by_name["valid_bom_types"].ok
    assert by_name["title_block_keys_wellformed"].ok
    assert by_name["no_duplicate_sheet_names"].ok
    assert skipped == []
    payload = assess(path)
    assert set(payload) == {
        "status",
        "verification",
        "checks_run",
        "skipped",
        "assumptions",
        "risk",
    }
    assert payload["status"] == "verified"
    assert payload["risk"] == "unverified"
    assert payload["assumptions"] == list(ASSUMPTIONS)


def test_skip_optional_fields_l2(tmp_path: Path):
    spec = {
        "model": "plate.sldprt",
        "paper": "A4",
        "scale": [1, 1],
        "views": [{"orient": "front"}],
    }
    path = _write(tmp_path, "l2.json", spec)
    checks, skipped = evaluate_preflight(path)
    skip_names = {s["name"] for s in skipped}
    assert skip_names == {
        "has_sheets",
        "valid_gdt_symbols",
        "valid_bom_types",
        "title_block_keys_wellformed",
        "no_duplicate_sheet_names",
    }
    assert {c.name for c in checks} == {
        "spec_loadable",
        "has_views",
        "valid_view_orientations",
    }


def test_fail_bad_orientation_via_evaluate_spec():
    checks, skipped = evaluate_spec(
        {
            "model": "p.sldprt",
            "views": [{"orient": "sideways"}],
        }
    )
    orient = next(c for c in checks if c.name == "valid_view_orientations")
    assert orient.ok is False


def test_fail_title_block_and_bom_and_dup_sheets(tmp_path: Path):
    spec = _base_l3(
        title_block={"PartNo": "P-001", "NotAKey": "x"},
        bom={"type": "magic"},
        sheets=[
            {"name": "Sheet1", "paper": "A4", "scale": [1, 1], "views": [{"orient": "front"}]},
            {"name": "Sheet1", "paper": "A4", "scale": [1, 1], "views": [{"orient": "top"}]},
        ],
    )
    path = _write(tmp_path, "bad.json", spec)
    checks, _skipped = evaluate_preflight(path)
    by_name = {c.name: c for c in checks}
    assert by_name["title_block_keys_wellformed"].ok is False
    assert by_name["valid_bom_types"].ok is False
    assert by_name["no_duplicate_sheet_names"].ok is False
    assert assess(path)["status"] == "failed"


def test_fail_gdt_symbol_via_evaluate_spec():
    checks, skipped = evaluate_spec(
        {
            "model": "p.sldprt",
            "views": [{"orient": "front"}],
            "gdts": [{"kind": "gdt", "symbol": "roundness", "tolerance": "0.1", "datums": []}],
        }
    )
    gdt = next(c for c in checks if c.name == "valid_gdt_symbols")
    assert gdt.ok is False
    assert "roundness" in gdt.detail


def test_missing_file_and_bad_json(tmp_path: Path):
    with pytest.raises(CadMcpError) as missing:
        evaluate_preflight(tmp_path / "nope.json")
    assert missing.value.code == "PATH_NOT_FOUND"
    bad = tmp_path / "bad.json"
    bad.write_text("{not-json", encoding="utf-8")
    with pytest.raises(CadMcpError) as invalid:
        evaluate_preflight(bad)
    assert invalid.value.code == "INVALID_ARGUMENT"


def test_tool_readonly_payload_and_state_version(tmp_path: Path):
    k = _kernel(tmp_path)
    _write(tmp_path, "ok.json", _base_l3())
    sv = k.state_version
    r = k.dispatch("check_drawing_spec", {"spec_path": "ok.json"})
    assert r.ok
    assert k.state_version == sv
    assert r.result is not None
    assert set(r.result) == {
        "status",
        "verification",
        "checks_run",
        "skipped",
        "assumptions",
        "risk",
    }
    assert "spec" not in r.result
    assert r.result["status"] == "verified"


def test_no_overlap_with_verify_model_completeness_names():
    preflight_names = {c.name for c in PREFLIGHT_CHECKS}
    forbidden = {
        "drawing.completeness",
        "untoleranced",
        "required_gdt_symbols",
        "min_datums",
        "require_bom",
        "required_title_keys",
    }
    assert not (preflight_names & forbidden)


def test_tool_registration():
    from cadmcp.registry import TOOLSET_PROFILES

    tool = next(s for s in core_registry().all() if s.name == "check_drawing_spec")
    assert tool.toolset == "drawing"
    assert tool.mutating is False
    assert tool.bypass_queue is True
    assert tool.layer == "domain"
    assert tool.timeout_class == "fast"
    assert tool.input_schema["required"] == ["spec_path"]
    assert "drawing" in TOOLSET_PROFILES["full"]
    assert "drawing" in TOOLSET_PROFILES["drawing"]
    assert "drawing" not in TOOLSET_PROFILES["part"]
