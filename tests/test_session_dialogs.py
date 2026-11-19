"""0.4.0 R1: session_dialogs / session_respond whitelist contract (FakeDialogProbe)."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from cadmcp.backend.fake.backend import FakeBackend
from cadmcp.dialog_policy import classify_dialog
from cadmcp.executor import Executor
from cadmcp.kernel import Kernel
from cadmcp.probe import FakeDialogProbe, WindowInfo
from cadmcp.result import ok_result
from cadmcp.toolsets.core import core_registry


def _ex(probe: FakeDialogProbe) -> Executor:
    e = Executor(FakeBackend, probe=probe)
    e.start()
    return e


def test_classify_four_kinds_and_unknown():
    restart = classify_dialog(title="SOLIDWORKS", text="是否重新启动 SOLIDWORKS？", buttons=["是", "否"])
    assert restart.kind == "restart" and restart.allowed == frozenset({"no"})

    save_all = classify_dialog(title="SOLIDWORKS", text="全部保存", buttons=["是", "否", "取消"])
    assert save_all.kind == "save_all" and save_all.allowed == frozenset({"cancel"})

    low = classify_dialog(
        title="SOLIDWORKS",
        text="系统内存极低。是否要继续？",
        buttons=["是", "否"],
    )
    assert low.kind == "low_memory" and low.allowed == frozenset({"yes"})

    progress = classify_dialog(title="Open Progress...", text="", buttons=[])
    assert progress.kind == "progress" and progress.blocks_sta is False

    unknown = classify_dialog(title="Tip", text="Something else", buttons=["OK"])
    assert unknown.kind == "unknown" and not unknown.allowed
    assert unknown.blocks_sta is True


@pytest.mark.parametrize(
    "kind,text,buttons,ok_action,bad_action",
    [
        ("restart", "是否重新启动 SOLIDWORKS？", ["是", "否"], "no", "yes"),
        ("save_all", "全部保存未保存的文档？", ["是", "否", "取消"], "cancel", "yes"),
        ("low_memory", "系统内存极低…是否要继续？", ["是", "否"], "yes", "no"),
    ],
)
def test_fake_respond_whitelist(kind, text, buttons, ok_action, bad_action):
    probe = FakeDialogProbe(
        [
            WindowInfo(
                title="SOLIDWORKS",
                class_name="#32770",
                rect=(0, 0, 100, 80),
                modal=True,
                text=text,
                buttons=buttons,
            )
        ]
    )
    ok = probe.respond(ok_action)  # type: ignore[arg-type]
    assert ok["responded"] is True
    assert ok["kind"] == kind
    assert ok["action"] == ok_action

    with pytest.raises(Exception) as exc:
        probe.respond(bad_action)  # type: ignore[arg-type]
    err = exc.value
    assert getattr(err, "code", None) == "INVALID_ARGUMENT"


def test_unclassified_and_match_miss_refused():
    probe = FakeDialogProbe(
        [
            WindowInfo(
                title="Other",
                class_name="#32770",
                rect=(0, 0, 10, 10),
                modal=True,
                text="Please confirm update",
                buttons=["OK", "Cancel"],
            )
        ]
    )
    with pytest.raises(Exception) as exc:
        probe.respond("yes")
    assert getattr(exc.value, "code", None) == "INVALID_ARGUMENT"

    with pytest.raises(Exception) as exc2:
        probe.respond("cancel", match="no-such-dialog")
    assert "No dialog matched" in getattr(exc2.value, "message", "")


def test_session_tools_bypass_queue_while_stuck(tmp_path: Path):
    probe = FakeDialogProbe(
        [
            WindowInfo(
                title="SOLIDWORKS",
                class_name="#32770",
                rect=(0, 0, 100, 80),
                modal=True,
                text="是否重新启动 SOLIDWORKS？",
                buttons=["是", "否"],
            )
        ]
    )
    e = _ex(probe)
    try:

        def hang():
            time.sleep(0.4)
            return ok_result({"ok": True})

        r = asyncio.run(e.run(hang, tool="hang", timeout=0.05))
        assert not r.ok and r.error.code == "EXEC_TIMEOUT"
        assert r.error.context.get("dialog", {}).get("title") == "SOLIDWORKS"
        assert "session_respond" in r.error.hint

        kernel = Kernel(
            core_registry(),
            e.backend(),
            workspace=tmp_path,
            dialogs_scan=e.scan_dialogs,
            dialogs_respond=e.respond_dialog,
        )
        listed = kernel.dispatch("session_dialogs")
        assert listed.ok
        assert listed.result["count"] >= 1
        assert listed.result["dialogs"][0]["text"]
        assert "否" in listed.result["dialogs"][0]["buttons"]

        responded = kernel.dispatch("session_respond", {"action": "no"})
        assert responded.ok
        assert responded.result["responded"] is True
        assert responded.result["kind"] == "restart"
        assert probe.respond_calls[-1]["action"] == "no"

        bad = kernel.dispatch("session_respond", {"action": "yes"})
        assert not bad.ok and bad.error.code == "INVALID_ARGUMENT"
    finally:
        e.shutdown()


def test_active_document_tools_fake(tmp_path: Path):
    k = Kernel(core_registry(), FakeBackend(), workspace=tmp_path, verify_mutations=False)
    assert k.dispatch("new_part").ok
    assert k.dispatch("new_part").ok
    active = k.dispatch("active_document")
    assert active.ok and active.result["title"] == "Part2"
    switched = k.dispatch("set_active_document", {"path_or_title": "Part1"})
    assert switched.ok and switched.result["title"] == "Part1"
    assert k.dispatch("get_active_document").result["title"] == "Part1"
