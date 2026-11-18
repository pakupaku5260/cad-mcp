"""F13 batch tool: precheck, stop_on_error, limits, partial failure."""
from __future__ import annotations

from pathlib import Path

from cadmcp.backend.fake.backend import FakeBackend
from cadmcp.kernel import Kernel
from cadmcp.toolsets.core import core_registry


def _kernel(ws: Path) -> Kernel:
    return Kernel(core_registry(), FakeBackend(), workspace=ws)


def test_unknown_tool_precheck_zero_side_effects(tmp_path: Path):
    k = _kernel(tmp_path)
    sv = k.state_version
    r = k.dispatch(
        "batch",
        {"steps": [{"tool": "no_such_tool_zzz", "args": {}}]},
    )
    assert not r.ok
    assert r.error is not None
    assert r.error.code == "INVALID_ARGUMENT"
    assert k.state_version == sv


def test_max_steps_exceeded_zero_side_effects(tmp_path: Path):
    k = _kernel(tmp_path)
    sv = k.state_version
    steps = [{"tool": "new_part", "args": {}} for _ in range(3)]
    r = k.dispatch("batch", {"steps": steps, "max_steps": 2})
    assert not r.ok
    assert r.error is not None
    assert r.error.code == "BATCH_LIMIT_EXCEEDED"
    assert k.state_version == sv


def test_nested_batch_rejected(tmp_path: Path):
    k = _kernel(tmp_path)
    sv = k.state_version
    r = k.dispatch(
        "batch",
        {
            "steps": [
                {"tool": "new_part", "args": {}},
                {"tool": "batch", "args": {"steps": [{"tool": "new_part", "args": {}}]}},
            ]
        },
    )
    assert not r.ok
    assert r.error is not None
    assert r.error.code == "INVALID_ARGUMENT"
    assert "nested" in r.error.message.lower()
    assert k.state_version == sv


def test_stop_on_error_true_halts(tmp_path: Path):
    k = _kernel(tmp_path)
    r = k.dispatch(
        "batch",
        {
            "steps": [
                {"tool": "new_part", "args": {}},
                {"tool": "extrude", "args": {"depth": 5}},  # no sketch → fail
                {"tool": "end_sketch", "args": {}},
            ],
            "stop_on_error": True,
        },
    )
    assert r.ok
    payload = r.result
    assert payload["ok"] is False
    assert payload["count"] == 2
    assert [s["tool"] for s in payload["steps"]] == ["new_part", "extrude"]
    assert payload["failed_step"]["index"] == 1
    assert payload["error_code"] == "BATCH_PARTIAL_FAILURE"
    assert payload["limits"] == {"max_steps": 50, "max_duration_s": 600.0}
    assert isinstance(payload["elapsed_s"], (int, float))
    assert payload["elapsed_s"] >= 0


def test_stop_on_error_false_continues(tmp_path: Path):
    k = _kernel(tmp_path)
    r = k.dispatch(
        "batch",
        {
            "steps": [
                {"tool": "new_part", "args": {}},
                {"tool": "extrude", "args": {"depth": 5}},
                {
                    "tool": "start_sketch",
                    "args": {"plane": "Front Plane"},
                },
            ],
            "stop_on_error": False,
        },
    )
    assert r.ok
    payload = r.result
    assert payload["ok"] is False
    assert payload["count"] == 3
    assert [s["tool"] for s in payload["steps"]] == [
        "new_part",
        "extrude",
        "start_sketch",
    ]
    assert payload["steps"][2]["ok"] is True
    assert payload["error_code"] == "BATCH_PARTIAL_FAILURE"


def test_duration_limit_stops_between_steps(tmp_path: Path, monkeypatch):
    import cadmcp.batch as batch_mod

    ticks = [0.0, 1.0, 601.0, 601.0]

    def fake_monotonic() -> float:
        return ticks.pop(0) if ticks else 601.0

    monkeypatch.setattr(batch_mod.time, "monotonic", fake_monotonic)
    k = _kernel(tmp_path)
    r = k.dispatch(
        "batch",
        {
            "steps": [
                {"tool": "new_part", "args": {}},
                {"tool": "start_sketch", "args": {"plane": "Front Plane"}},
            ],
            "max_duration_s": 600,
        },
    )
    assert r.ok
    payload = r.result
    assert payload["ok"] is False
    # Step 0 ran before the budget was exceeded; step 1 never dispatched.
    assert payload["count"] == 1
    assert [s["tool"] for s in payload["steps"]] == ["new_part"]
    assert payload["failed_step"] == {
        "index": 1,
        "tool": "start_sketch",
        "error_code": "BATCH_LIMIT_EXCEEDED",
    }
    assert payload["error_code"] == "BATCH_LIMIT_EXCEEDED"


def test_first_step_failure_uses_real_code(tmp_path: Path):
    k = _kernel(tmp_path)
    r = k.dispatch(
        "batch",
        {"steps": [{"tool": "extrude", "args": {"depth": 5}}]},
    )
    assert r.ok
    payload = r.result
    assert payload["ok"] is False
    assert payload["failed_step"]["index"] == 0
    assert payload["error_code"] == payload["steps"][0]["error_code"]
    assert payload["error_code"] != "BATCH_PARTIAL_FAILURE"
    assert payload["error_code"] is not None


def test_happy_three_steps(tmp_path: Path):
    k = _kernel(tmp_path)
    r = k.dispatch(
        "batch",
        {
            "steps": [
                {"tool": "new_part", "args": {}},
                {"tool": "start_sketch", "args": {"plane": "Front Plane"}},
                {
                    "tool": "sketch_rectangle",
                    "args": {"x1": 0, "y1": 0, "x2": 10, "y2": 10},
                },
            ]
        },
    )
    assert r.ok
    payload = r.result
    assert payload["ok"] is True
    assert payload["count"] == 3
    assert payload["failed_step"] is None
    assert payload["error_code"] is None
    assert all(s["ok"] for s in payload["steps"])


def test_expect_title_mismatch_zero_side_effects(tmp_path: Path):
    k = _kernel(tmp_path)
    k.dispatch("new_part", {})
    sv = k.state_version
    r = k.dispatch(
        "batch",
        {
            "steps": [{"tool": "start_sketch", "args": {"plane": "Front Plane"}}],
            "expect_title": "wrong_title_zzz",
        },
    )
    assert not r.ok
    assert r.error is not None
    assert r.error.code == "WRONG_DOCUMENT"
    assert k.state_version == sv
