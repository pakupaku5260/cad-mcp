"""
stdio transport (v4 §16.5 follow-up): subprocess E2E golden path, gate branches, audit wiring.

Acceptance:
1. A real subprocess (`python -m cadmcp.cli serve --transport stdio`) started by an MCP
   client completes the same golden path as HTTP (125000 mm³) — protocol and executor
   are isomorphic under stdio;
2. Implicit stdout hygiene: a successful initialize proves no stray runtime output
   polluted the protocol stream;
3. Under stdio, `--allow-insecure` is rejected (exit code 2), and the serve_start audit
   event carries a transport field.

"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from cadmcp.cli import main
from cadmcp.resources import topic_uri
from cadmcp.resources.content import TOPICS
from cadmcp.toolsets.core import core_registry

REPO_ROOT = Path(__file__).resolve().parents[1]


def _stdio_params(tmp_path: Path, *, profile: str = "full") -> StdioServerParameters:
    # E2E full tool surface
    args = [
        "-m", "cadmcp.cli", "serve", "--transport", "stdio",
        "--backend", "fake",
        "--profile", profile,
        "--workspace", str(tmp_path / "ws"),
        "--audit-log", str(tmp_path / "audit.jsonl"),
    ]
    return StdioServerParameters(command=sys.executable, args=args, cwd=str(REPO_ROOT))


def test_stdio_golden_cube_and_resources(tmp_path: Path):
    params = _stdio_params(tmp_path)

    async def main_client():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                names = {t.name for t in (await session.list_tools()).tools}
                assert len(names) == len(core_registry()) and "help" in names and "status" in names
                assert "split_body" in names and "parting_line" in names and "parting_surface" in names
                assert "base_flange" in names and "edge_flange" in names and "sheet_metal_unfold" in names
                assert "hole_wizard" in names
                assert "create_section_view" in names and "export" in names
                assert "extrude_surface" in names and "knit" in names and "thicken" in names
                assert "move_component" in names and "rotate_component" in names
                assert "list_dimensions" in names and "set_dimension" in names
                assert "pattern_component" in names and "set_color" in names

                listed = await session.list_resources()
                assert {r.uri for r in listed.resources} == {topic_uri(n) for n in TOPICS}

                async def call(name: str, args: dict | None = None):
                    r = await session.call_tool(name, args or {})
                    payload = json.loads(r.content[0].text)
                    assert r.is_error is not payload["ok"], f"{name}: {payload}"
                    return payload

                assert (await call("new_part"))["ok"]
                assert (await call("start_sketch", {"plane": "Front Plane"}))["ok"]
                assert (await call("sketch_rectangle", {"x1": 0, "y1": 0, "x2": 50, "y2": 50}))["ok"]
                assert (await call("end_sketch"))["ok"]
                assert (await call("extrude", {"depth": 50}))["ok"]
                mp = await call("get_mass_properties")
                assert mp["result"]["volume"] == pytest.approx(125000.0, rel=1e-9)

                # status subprocess inline
                st = await call("status")
                health = st["result"]["health"]
                assert health["state"] in {"IDLE", "BUSY", "STUCK"}
                assert health["jobs_total"] >= 6  # six calls counted

    asyncio.run(main_client())

    # serve_start audited
    audit_file = tmp_path / "audit.jsonl"
    assert audit_file.exists()
    events = [json.loads(line) for line in audit_file.read_text(encoding="utf-8").splitlines()]
    start = next(e for e in events if e["event"] == "serve_start")
    assert start["transport"] == "stdio" and start["backend"] == "fake"


def test_stdio_rejects_allow_insecure(capsys):
    code = main(["serve", "--transport", "stdio", "--allow-insecure"])
    assert code == 2
    err = capsys.readouterr().err
    assert "stdio transport does not use the network" in err and "--allow-insecure does not apply" in err


def test_stdio_serve_start_stop_audited(tmp_path: Path, monkeypatch):
    """Like HTTP stub: stub transport; transport + serve_stop."""
    called: dict = {}
    monkeypatch.setattr(
        "cadmcp.cli._run_stdio", lambda server: called.setdefault("server", server)
    )
    audit_file = tmp_path / "audit.jsonl"
    code = main(
        ["serve", "--transport", "stdio", "--audit-log", str(audit_file),
         "--workspace", str(tmp_path / "ws")]
    )
    assert code == 0
    assert called["server"] is not None  # stdio entry not uvicorn
    events = [json.loads(line) for line in audit_file.read_text(encoding="utf-8").splitlines()]
    assert any(e["event"] == "serve_start" and e["transport"] == "stdio" for e in events)
    assert any(e["event"] == "serve_stop" for e in events)
