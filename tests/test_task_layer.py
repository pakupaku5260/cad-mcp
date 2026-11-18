"""F14 task layer: TOOL_LAYERS, ledger, task_status/task_list."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cadmcp.backend.fake.backend import FakeBackend
from cadmcp.consistency.sequences.design import RUN_PART_SPEC
from cadmcp.kernel import Kernel
from cadmcp.registry import TOOL_LAYERS, ToolRegistry, ToolSpec, make_schema
from cadmcp.task_ledger import finish, get, list_jobs, reset_for_tests, start
from cadmcp.toolsets.core import core_registry


@pytest.fixture(autouse=True)
def _clear_ledger():
    reset_for_tests()
    yield
    reset_for_tests()


def _kernel(ws: Path) -> Kernel:
    return Kernel(core_registry(), FakeBackend(), workspace=ws)


def test_tool_layers_single_source():
    assert TOOL_LAYERS == ("primitive", "domain", "task")
    specs = core_registry().all()
    by_layer = {layer: [] for layer in TOOL_LAYERS}
    for s in specs:
        assert s.layer in TOOL_LAYERS
        by_layer[s.layer].append(s.name)
    assert set(by_layer["task"]) == {"batch", "design_run", "task_list", "task_status"}
    assert "new_part" in by_layer["domain"]
    assert by_layer["primitive"] == []  # none declared yet


def test_default_layer_is_domain():
    spec = ToolSpec(
        name="toy_layer_default",
        description="toy",
        input_schema=make_schema({}),
        handler=lambda ctx: {},
    )
    assert spec.layer == "domain"


def test_illegal_layer_rejected():
    reg = ToolRegistry()
    with pytest.raises(ValueError, match="Unknown layer"):
        reg.register(
            ToolSpec(
                name="toy_bad_layer",
                description="toy",
                input_schema=make_schema({}),
                handler=lambda ctx: {},
                layer="workflow",
            )
        )


def test_ledger_fifo_keeps_100():
    ids = [start(f"t{i}") for i in range(105)]
    assert ids[0] == 1
    assert ids[-1] == 105
    assert get(1) is None  # pruned
    assert get(5) is None
    assert get(6) is not None
    assert get(105) is not None
    page, total = list_jobs(limit=200, offset=0)
    assert total == 100
    assert page[0]["job_id"] == 6
    assert page[-1]["job_id"] == 105


def test_ledger_finish_exception_path():
    jid = start("batch")
    finish(jid, None, state="failed", error_code="INVALID_ARGUMENT")
    entry = get(jid)
    assert entry is not None
    assert entry["state"] == "failed"
    assert entry["ok"] is False
    assert entry["error_code"] == "INVALID_ARGUMENT"
    assert entry["finished_at"]


def test_task_status_and_list(tmp_path: Path):
    k = _kernel(tmp_path)
    r = k.dispatch(
        "batch",
        {
            "steps": [
                {"tool": "new_part", "args": {}},
                {"tool": "start_sketch", "args": {"plane": "Front Plane"}},
            ]
        },
    )
    assert r.ok
    st = k.dispatch("task_status", {"job_id": 1})
    assert st.ok
    assert st.result["tool"] == "batch"
    assert st.result["state"] == "done"
    assert st.result["ok"] is True
    assert st.result["step_count"] == 2
    listed = k.dispatch("task_list", {"limit": 5, "offset": 0})
    assert listed.ok
    assert listed.result["total"] == 1
    assert listed.result["offset"] == 0
    assert len(listed.result["tasks"]) == 1


def test_task_status_unknown_id(tmp_path: Path):
    k = _kernel(tmp_path)
    r = k.dispatch("task_status", {"job_id": 999})
    assert not r.ok
    assert r.error is not None
    assert r.error.code == "INVALID_ARGUMENT"


def test_task_list_pagination(tmp_path: Path):
    k = _kernel(tmp_path)
    for _ in range(3):
        k.dispatch("batch", {"steps": [{"tool": "new_part", "args": {}}]})
    page = k.dispatch("task_list", {"limit": 2, "offset": 1})
    assert page.ok
    assert page.result["total"] == 3
    assert page.result["offset"] == 1
    assert len(page.result["tasks"]) == 2
    assert page.result["tasks"][0]["job_id"] == 2


def test_design_run_ledger_payload_unchanged(tmp_path: Path):
    k = _kernel(tmp_path)
    k.dispatch("new_part", {})
    (tmp_path / "run.json").write_text(json.dumps(RUN_PART_SPEC), encoding="utf-8")
    r = k.dispatch("design_run", {"spec_path": "run.json"})
    assert r.ok
    payload = r.result
    assert set(payload) == {
        "ok",
        "spec",
        "steps",
        "failed_step",
        "verification",
        "checkpoints",
        "outputs",
    }
    assert "job_id" not in payload
    st = k.dispatch("task_status", {"job_id": 1})
    assert st.result["tool"] == "design_run"
    assert st.result["step_count"] == len(payload["steps"])


def test_batch_precheck_failure_finishes_ledger(tmp_path: Path):
    k = _kernel(tmp_path)
    r = k.dispatch("batch", {"steps": [{"tool": "no_such_tool", "args": {}}]})
    assert not r.ok
    assert r.error.code == "INVALID_ARGUMENT"
    st = k.dispatch("task_status", {"job_id": 1})
    assert st.ok
    assert st.result["state"] == "failed"
    assert st.result["error_code"] == "INVALID_ARGUMENT"
