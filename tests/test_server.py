"""W4 E2E: MCP client over Streamable HTTP + fake backend golden path (§17.3 M0)."""

from __future__ import annotations

import asyncio
import json
import socket
import sys
import threading
import time
import types
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import uvicorn
from mcp import ClientSession, MCPError
from mcp.client.streamable_http import streamable_http_client

from cadmcp import safety
from cadmcp.auth import TOKEN_FILENAME
from cadmcp.backend.fake.backend import FakeBackend
from cadmcp.cli import main
from cadmcp.probe import FakeDialogProbe, WindowInfo
from cadmcp.server import build_stack
from cadmcp.toolsets.core import core_registry


class _Served:
    """Background uvicorn on ephemeral port."""

    def __init__(self, app) -> None:
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        self.port = sock.getsockname()[1]
        sock.listen()
        config = uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning")
        self.server = uvicorn.Server(config)
        # pre-bound socket avoids race
        self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [sock]}, daemon=True)
        self.thread.start()
        for _ in range(300):
            if self.server.started:
                break
            time.sleep(0.01)
        else:
            raise RuntimeError("uvicorn failed to start")

    def close(self) -> None:
        self.server.should_exit = True
        self.thread.join(5)

    @property
    def mcp_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/mcp"

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


@pytest.fixture()
def served(tmp_path: Path) -> Iterator[_Served]:
    stack = build_stack(workspace=tmp_path, backend_factory=FakeBackend)
    s = _Served(stack.app)
    try:
        yield s
    finally:
        s.close()
        stack.executor.shutdown()


# ---------- Golden path (M0 via HTTP) ----------


def test_golden_cube_over_http(served: _Served):
    async def main():
        async with streamable_http_client(served.mcp_url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = sorted(t.name for t in tools.tools)
                assert "extrude" in names and "get_mass_properties" in names
                assert "revolve" in names and "extrude_cut" in names
                assert "fillet" in names and "chamfer" in names
                assert "shell" in names and "linear_pattern" in names
                assert "circular_pattern" in names
                assert "get_entities" in names and "get_selection" in names
                assert "sketch_circle" in names
                assert "help" in names
                assert "status" in names
                assert "new_assembly" in names and "insert_component" in names
                assert "mate" in names and "list_mates" in names
                assert "sketch_polygon" in names and "insert_thread" in names
                assert "sketch_arc" in names
                assert "create_helix" in names and "sweep_cut" in names
                assert "set_view" in names and "select_face" in names
                assert len(names) == len(core_registry())
                assert "split_body" in names and "parting_line" in names and "parting_surface" in names
                assert "base_flange" in names and "edge_flange" in names and "sheet_metal_unfold" in names
                assert "hole_wizard" in names
                assert "create_section_view" in names and "insert_model_items" in names
                assert "insert_balloons" in names and "export" in names
                assert "extrude_surface" in names and "knit" in names and "thicken" in names
                assert "fill_surface" in names and "boundary_surface" in names
                assert (
                    "trim_surface" in names
                    and "extend_surface" in names
                    and "fillet_surface" in names
                    and "untrim_surface" in names
                )
                assert "sketch_offset" in names and "sketch_trim" in names and "sketch_mirror" in names
                assert "rib" in names and "draft" in names and "combine" in names and "split_body" in names
                assert "move_component" in names and "rotate_component" in names
                assert "list_dimensions" in names and "set_dimension" in names
                assert "list_components" in names and "pattern_component" in names
                assert "edit_component" in names and "end_edit" in names and "get_edit_target" in names
                assert "set_lightweight" in names
                assert "explode_view" in names and "show_exploded" in names and "list_exploded_views" in names
                assert "set_color" in names and "get_color" in names

                async def call(name: str, args: dict | None = None):
                    r = await session.call_tool(name, args or {})
                    payload = json.loads(r.content[0].text)
                    assert r.is_error is not payload["ok"], f"{name}: {payload}"
                    return payload

                assert (await call("new_part"))["ok"]
                assert (await call("start_sketch", {"plane": "Front Plane"}))["ok"]
                assert (await call("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 50, "y2": 50}))["ok"]
                assert (await call("end_sketch"))["ok"]
                ext = await call("extrude", {"depth": 50})
                assert ext["ok"]
                assert ext["rebuild"]["ok"] is True
                assert "volume_mm3" in ext["delta"]["changed"]

                mp = await call("get_mass_properties")
                assert mp["result"]["volume"] == pytest.approx(125000.0, rel=1e-9)
                assert mp["state_version"] == 5

    asyncio.run(main())


def test_domain_error_is_iserror_result(served: _Served):
    async def main():
        async with streamable_http_client(served.mcp_url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                r = await session.call_tool("extrude", {"depth": 5})
                assert r.is_error is True
                payload = json.loads(r.content[0].text)
                assert payload["error"]["code"] == "NO_ACTIVE_DOCUMENT"
                assert payload["error"]["hint"]

    asyncio.run(main())


def test_status_tool_coarse_over_http(served: _Served):
    """HTTP status coarse tier without token (§11.2 item 3)."""

    async def main():
        async with streamable_http_client(served.mcp_url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                r = await session.call_tool("status", {})
                assert r.is_error is False
                payload = json.loads(r.content[0].text)
                health = payload["result"]["health"]
                assert health["state"] in {"IDLE", "BUSY", "STUCK"}
                assert "queue_depth" in health and "thread_alive" in health
                assert "windows" not in health and "detector_error" not in health

    asyncio.run(main())


def test_unknown_tool_rejected_at_bridge(served: _Served):
    async def main():
        async with streamable_http_client(served.mcp_url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                r = await session.call_tool("no_such_tool", {})
                assert r.is_error is True
                payload = json.loads(r.content[0].text)
                assert payload["error"]["code"] == "INVALID_ARGUMENT"

    asyncio.run(main())


# ---------- /health never 500 ----------


def test_health_endpoint(served: _Served):
    with httpx.Client(base_url=served.base_url) as client:
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True and body["state"] == "IDLE"
        assert body["thread_alive"] is True and body["backend_ready"] is True


def test_health_never_500_even_if_executor_broken():
    from starlette.applications import Starlette

    from cadmcp.server import _health_route

    class BrokenExecutor:
        def health(self, detail: bool = False):
            raise RuntimeError("health read crashed")

    app = Starlette(routes=[_health_route(BrokenExecutor())])
    s = _Served(app)
    try:
        with httpx.Client(base_url=s.base_url) as client:
            r = client.get("/health")
            assert r.status_code == 503
            assert r.json()["ok"] is False
            assert "RuntimeError" in r.json()["error"]
    finally:
        s.close()


# ---------- /health when STUCK ----------


def test_health_reports_stuck_after_timeout(tmp_path: Path):
    stack = build_stack(workspace=tmp_path, backend_factory=FakeBackend)
    # slow extrude exceeds timeout
    slow = FakeBackend()

    original = slow.extrude_blind

    def slow_extrude(depth_m: float, sketch: str | None = None, **kwargs):
        time.sleep(0.5)
        return original(depth_m, sketch, **kwargs)

    slow.extrude_blind = slow_extrude  # type: ignore[method-assign]
    stack.kernel._backend = slow  # noqa: SLF001 — slow backend inject
    stack.executor._tiers = {"fast": 0.05, "normal": 0.1, "slow": 0.2}  # noqa: SLF001

    s = _Served(stack.app)
    try:
        async def main():
            async with streamable_http_client(s.mcp_url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    await session.call_tool("new_part", {})
                    await session.call_tool("start_sketch", {})
                    await session.call_tool("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 10, "y2": 10})
                    await session.call_tool("end_sketch", {})
                    r = await session.call_tool("extrude", {"depth": 10})
                    payload = json.loads(r.content[0].text)
                    assert payload["error"]["code"] == "EXEC_TIMEOUT"

        asyncio.run(main())
        with httpx.Client(base_url=s.base_url) as client:
            body = client.get("/health").json()
            assert body["ok"] is False and body["state"] == "STUCK"
            assert "extrude" in (body["stuck_reason"] or "")
            time.sleep(0.6)  # late result counted
            assert client.get("/health").json()["late_results"] == 1
            assert stack.executor.resolve_stuck().ok
            assert client.get("/health").json()["state"] == "IDLE"
    finally:
        s.close()
        stack.executor.shutdown()


def test_health_blocker_coarse_only(tmp_path: Path):
    """W8: /health blocker coarse; no window detail unauthenticated (§11)."""
    probe = FakeDialogProbe(
        [
            WindowInfo(
                title="另存为 C:\\secret\\gear.sldprt",
                class_name="#32770",
                rect=(10, 10, 640, 480),
                modal=True,
            )
        ]
    )
    stack = build_stack(workspace=tmp_path, backend_factory=FakeBackend, probe=probe)
    s = _Served(stack.app)
    try:
        with httpx.Client(base_url=s.base_url) as client:
            resp = client.get("/health")
            body = resp.json()
            assert body["blocker"] is True
            assert "windows" not in body and "detector_error" not in body
            assert "gear.sldprt" not in resp.text  # title not leaked (§11)
    finally:
        s.close()
        stack.executor.shutdown()


def test_health_blocker_null_without_probe(tmp_path: Path):
    stack = build_stack(workspace=tmp_path, backend_factory=FakeBackend)  # no probe default
    s = _Served(stack.app)
    try:
        with httpx.Client(base_url=s.base_url) as client:
            body = client.get("/health").json()
        assert body["blocker"] is None  # unknown, not false negative
        assert body["ok"] is True
    finally:
        s.close()
        stack.executor.shutdown()


# ---------- CLI bind / doctor / audit ----------


def _audit_events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _stub_uvicorn(monkeypatch) -> None:
    """Stub uvicorn import in serve (no real port)."""
    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=lambda *a, **k: None))


def test_serve_non_loopback_auto_token_warns(tmp_path: Path, monkeypatch, capsys):
    """Item 2: non-loopback starts with token + reverse-proxy warning."""
    _stub_uvicorn(monkeypatch)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    audit_file = tmp_path / "audit.jsonl"
    code = main(
        ["serve", "--host", "0.0.0.0", "--audit-log", str(audit_file),
         "--workspace", str(tmp_path / "ws")]
    )
    assert code == 0
    err = capsys.readouterr().err
    assert "reverse proxy" in err and "Authorization: Bearer" in err
    token = (tmp_path / "cadmcp" / TOKEN_FILENAME).read_text(encoding="utf-8").strip()
    assert token not in err  # value not in stderr
    start = next(e for e in _audit_events(audit_file) if e["event"] == "serve_start")
    assert start["host"] == "0.0.0.0" and start["auth"] is True


def test_serve_start_and_stop_audited(tmp_path: Path, monkeypatch):
    _stub_uvicorn(monkeypatch)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))  # token under tmp config
    audit_file = tmp_path / "audit.jsonl"
    code = main(["serve", "--audit-log", str(audit_file), "--workspace", str(tmp_path / "ws")])
    assert code == 0
    events = _audit_events(audit_file)
    assert any(e["event"] == "serve_start" for e in events)
    assert any(e["event"] == "serve_stop" for e in events)
    assert not any(e["event"].startswith("insecure") for e in events)
    start = next(e for e in events if e["event"] == "serve_start")
    assert start["host"] == "127.0.0.1" and start["backend"] == "fake"
    assert start["auth"] is True  # default auth (§11.2 item 2)
    assert (tmp_path / "cadmcp" / TOKEN_FILENAME).exists()  # auto token file (item 3)
    assert safety._audit_path is None


def test_serve_allow_insecure_rejected_on_non_loopback(tmp_path: Path, capsys):
    """Item 2: --allow-insecure loopback-only; non-loopback refused."""
    audit_file = tmp_path / "audit.jsonl"
    code = main(["serve", "--host", "0.0.0.0", "--allow-insecure", "--audit-log", str(audit_file)])
    assert code == 2
    assert "INSECURE_BIND_REJECTED" in capsys.readouterr().err
    # rejection audited
    assert any(e["event"] == "insecure_bind_rejected" for e in _audit_events(audit_file))
    assert safety._audit_path is None


def test_serve_insecure_loopback_audited_and_warned(tmp_path: Path, monkeypatch, capsys):
    _stub_uvicorn(monkeypatch)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    audit_file = tmp_path / "audit.jsonl"
    code = main(
        ["serve", "--allow-insecure", "--audit-log", str(audit_file),
         "--workspace", str(tmp_path / "ws")]
    )
    assert code == 0
    err = capsys.readouterr().err
    assert "Warning" in err and "--allow-insecure" in err and "without auth" in err  # prominent warning (§11.2)
    events = _audit_events(audit_file)
    assert any(e["event"] == "insecure_bind" and e["host"] == "127.0.0.1" for e in events)
    assert any(e["event"] == "serve_start" and e["auth"] is False for e in events)


def test_serve_insecure_fails_closed_when_audit_unwritable(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    blocked = tmp_path / "not-a-file"  # directory blocks append
    blocked.mkdir()
    code = main(["serve", "--allow-insecure", "--audit-log", str(blocked)])
    assert code == 2  # fail-closed if audit bad
    err = capsys.readouterr().err
    assert "INSECURE_BIND_REJECTED" in err and "audit log not writable" in err
    assert safety._audit_path is None


def test_user_config_dir_platform_branches(monkeypatch, tmp_path: Path):
    from cadmcp.cli import _default_audit_path, _user_config_dir

    monkeypatch.setattr(sys, "platform", "linux")  # POSIX branch
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert _user_config_dir() == tmp_path / "cadmcp"
    assert _default_audit_path() == tmp_path / "cadmcp" / "audit.jsonl"

    monkeypatch.delenv("XDG_CONFIG_HOME")
    monkeypatch.setattr(sys, "platform", "win32")  # Windows branch
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert _user_config_dir() == tmp_path / "cadmcp"

    monkeypatch.setattr(sys, "platform", "darwin")  # fallback without env
    monkeypatch.delenv("APPDATA")
    assert _user_config_dir() == Path.home() / ".config" / "cadmcp"


def test_is_loopback_unit():
    from cadmcp.cli import _is_loopback

    assert _is_loopback("127.0.0.1") and _is_loopback("::1") and _is_loopback("localhost")
    assert not _is_loopback("0.0.0.0") and not _is_loopback("192.168.1.5") and not _is_loopback("::")


def test_doctor_fake_healthy(tmp_path: Path, capsys):
    code = main(["doctor", "--backend", "fake", "--workspace", str(tmp_path)])
    report = json.loads(capsys.readouterr().out)
    assert code == 0
    assert report["ok"] is True
    assert report["backend"]["available"] is True
    assert report["backend"]["revision"] == "33.0"
    assert report["executor"]["state"] == "IDLE"
    expected = core_registry()
    assert report["registry"]["tools"] == len(expected)
    assert report["registry"]["toolsets"] == {
        t: len(expected.by_toolset(t)) for t in sorted({s.toolset for s in expected})
    }
    assert report["executor"]["blocker"] is None  # doctor detail blocker (W8)


def test_doctor_backend_init_failure_reports_cleanly(tmp_path: Path, capsys, monkeypatch):
    from cadmcp import cli

    def _factory(_kind: str):
        def _broken():
            raise RuntimeError("boom")

        return _broken

    monkeypatch.setattr(cli, "_make_factory", _factory)
    monkeypatch.setattr(cli, "_probe_for", lambda _kind: None)

    code = main(["doctor", "--backend", "solidworks", "--workspace", str(tmp_path)])
    report = json.loads(capsys.readouterr().out)
    assert code == 1  # init fail → unhealthy report
    assert report["ok"] is False
    assert report["backend"]["available"] is False
    assert "COM_ATTACH_FAILED" in report["backend"]["error"]
    assert report["executor"] is None  # no fake executor


# ---------- resources dual channel (§8) ----------


def test_resources_list_and_read_over_http(served: _Served):
    from cadmcp.resources import topic_uri
    from cadmcp.resources.content import MIME_TYPE, TOPICS

    async def main():
        async with streamable_http_client(served.mcp_url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_resources()
                assert {r.uri for r in listed.resources} == {topic_uri(n) for n in TOPICS}
                for res in listed.resources:
                    assert res.mime_type == MIME_TYPE
                    assert res.description == TOPICS[res.name].description
                    got = await session.read_resource(res.uri)
                    assert got.contents[0].text == TOPICS[res.name].text

    asyncio.run(main())


def test_resources_unknown_uri_is_protocol_error(served: _Served):
    from cadmcp.resources import known_uris

    async def main():
        async with streamable_http_client(served.mcp_url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                with pytest.raises(MCPError) as ei:
                    await session.read_resource("cadmcp://help/nope")
                assert ei.value.code == -32602  # INVALID_PARAMS protocol error
                assert set(ei.value.data["available"]) == set(known_uris())
                assert "cadmcp://help/nope" not in ei.value.data["available"]

    asyncio.run(main())


def test_help_tool_matches_resource_channel(served: _Served):
    from cadmcp.resources import topic_uri
    from cadmcp.resources.content import TOPICS

    async def main():
        async with streamable_http_client(served.mcp_url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                r = await session.call_tool("help", {"topic": "workflow"})
                assert r.is_error is False
                payload = json.loads(r.content[0].text)
                assert payload["ok"]
                assert payload["result"]["uri"] == topic_uri("workflow")
                assert payload["result"]["text"] == TOPICS["workflow"].text  # same source both channels
                bad = await session.call_tool("help", {"topic": "nope"})
                assert bad.is_error is True
                err = json.loads(bad.content[0].text)
                assert err["error"]["code"] == "INVALID_ARGUMENT"
                assert "selectors" in err["error"]["hint"]

    asyncio.run(main())
