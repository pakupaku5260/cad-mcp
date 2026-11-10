"""Token auth (v4 §11.2 items 2/3): 401 gate, /health layers, token file, CLI bind (see test_server)."""
from __future__ import annotations

import asyncio
import json
import os
import stat
import sys
import types
from pathlib import Path

import httpx
import pytest

from cadmcp.auth import TOKEN_FILENAME, bearer_matches, load_or_create_token
from cadmcp.backend.fake.backend import FakeBackend
from cadmcp.cli import main
from cadmcp.probe import FakeDialogProbe, WindowInfo
from cadmcp.server import build_stack

TOKEN = "test-token-abc123"


def _stack(tmp_path: Path, **kw):
    return build_stack(workspace=tmp_path, backend_factory=FakeBackend, **kw)


async def _request(app, method: str, path: str, **req_kw) -> httpx.Response:
    """ASGI direct: 401 gate outermost; no MCP session needed."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **req_kw)


async def _with_lifespan(app, body):
    """One lifespan per test; session manager.run() once per app.

    /health needs no lifespan; authorized /mcp after startup needs lifespan.
    """
    async with app.router.lifespan_context(app):
        return await body()


def test_token_file_created_once_with_posix_perms(tmp_path: Path):
    path = tmp_path / "cfg" / TOKEN_FILENAME
    token = load_or_create_token(path)
    assert token and path.read_text(encoding="utf-8").strip() == token
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600  # §11.2 item 3: mode 600
    assert load_or_create_token(path) == token  # stable: do not regenerate


def test_empty_token_file_regenerates(tmp_path: Path):
    path = tmp_path / TOKEN_FILENAME
    path.write_text(" \n", encoding="utf-8")
    fresh = load_or_create_token(path)
    assert fresh and fresh != " "


@pytest.mark.parametrize(
    "header,token,expected",
    [
        (f"Bearer {TOKEN}", TOKEN, True),
        (f"bearer {TOKEN}", TOKEN, True),  # scheme case-insensitive
        (f"Basic {TOKEN}", TOKEN, False),
        (f"Bearer wrong{TOKEN}", TOKEN, False),
        (f"Bearer {TOKEN}x", TOKEN, False),
        (f"Bearer  {TOKEN}", TOKEN, False),  # extra space → leading space in credential
        (TOKEN, TOKEN, False),  # no scheme
        (f"Bearer {TOKEN}", None, False),
        ("Bearer ", TOKEN, False),
        (None, TOKEN, False),
        ("", TOKEN, False),
    ],
)
def test_bearer_matches_matrix(header: str | None, token: str | None, expected: bool):
    assert bearer_matches(header, token) is expected


def test_mcp_endpoint_requires_bearer(tmp_path: Path):
    stack = _stack(tmp_path, auth_token=TOKEN)

    async def body():
        no_auth = await _request(stack.app, "POST", "/mcp", json={"probe": 1})
        assert no_auth.status_code == 401
        assert no_auth.headers.get("www-authenticate") == "Bearer"
        assert TOKEN not in no_auth.text  # token not echoed (item 3)
        assert "UNAUTHENTICATED" in no_auth.text

        wrong = await _request(
            stack.app, "POST", "/mcp", json={"probe": 1},
            headers={"Authorization": "Bearer wrong"},
        )
        assert wrong.status_code == 401

        ok = await _request(
            stack.app, "POST", "/mcp", json={"probe": 1},
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert ok.status_code != 401  # past gate; later errors not auth

    try:
        asyncio.run(_with_lifespan(stack.app, body))
    finally:
        stack.executor.shutdown()


def test_health_layers_detail_behind_token(tmp_path: Path):
    probe = FakeDialogProbe(
        [WindowInfo(title="另存为 C:\\secret\\gear.sldprt", class_name="#32770",
                    rect=(1, 2, 3, 4), modal=True)]
    )
    stack = _stack(tmp_path, probe=probe, auth_token=TOKEN)
    try:
        r = asyncio.run(_request(stack.app, "GET", "/health"))
        body = r.json()
        assert r.status_code == 200  # /health never 401
        assert body["blocker"] is True  # coarse still gives blocker
        assert "detail" not in body and "gear.sldprt" not in r.text  # detail not leaked

        r2 = asyncio.run(
            _request(stack.app, "GET", "/health", headers={"Authorization": f"Bearer {TOKEN}"})
        )
        detail = r2.json()["detail"]
        assert "gear.sldprt" in json.dumps(detail["windows"], ensure_ascii=False)
        assert detail["detector_error"] is None

        r3 = asyncio.run(
            _request(stack.app, "GET", "/health", headers={"Authorization": "Bearer nope"})
        )
        assert r3.status_code == 200 and "detail" not in r3.json()  # bad token = unauthenticated
    finally:
        stack.executor.shutdown()


def test_insecure_mode_passes_through_but_honors_token(tmp_path: Path):
    stack = _stack(tmp_path, probe=FakeDialogProbe([]), auth_token=TOKEN, require_auth=False)

    async def body():
        r = await _request(stack.app, "POST", "/mcp", json={"probe": 1})
        assert r.status_code != 401  # not blocked (--allow-insecure)
        r2 = await _request(
            stack.app, "GET", "/health", headers={"Authorization": f"Bearer {TOKEN}"}
        )
        assert "detail" in r2.json()  # token unlocks detail
        r3 = await _request(stack.app, "GET", "/health")
        assert "detail" not in r3.json()

    try:
        asyncio.run(_with_lifespan(stack.app, body))
    finally:
        stack.executor.shutdown()


# ---------- CLI bind semantics (§11.2) ----------


def _audit_events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _stub_uvicorn(monkeypatch) -> None:
    """Stub uvicorn import in serve (no real port)."""
    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=lambda *a, **k: None))


def test_serve_loopback_enforces_auth_by_default(tmp_path: Path, monkeypatch, capsys):
    _stub_uvicorn(monkeypatch)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    import cadmcp.cli as cli_mod

    captured: dict = {}
    real = cli_mod.build_stack

    def spy(**kw):
        captured.update(kw)
        return real(**kw)

    monkeypatch.setattr(cli_mod, "build_stack", spy)
    audit_file = tmp_path / "audit.jsonl"
    code = main(["serve", "--audit-log", str(audit_file), "--workspace", str(tmp_path / "ws")])
    assert code == 0

    token = (tmp_path / "cadmcp" / TOKEN_FILENAME).read_text(encoding="utf-8").strip()
    assert captured["auth_token"] == token  # auto token on first start (item 3)
    assert captured["require_auth"] is True  # auth default (item 2)
    err = capsys.readouterr().err
    assert token not in err  # token value not in stderr

    start = next(e for e in _audit_events(audit_file) if e["event"] == "serve_start")
    assert start["auth"] is True
    assert token not in audit_file.read_text(encoding="utf-8")  # token not in audit


def test_serve_default_mode_refuses_when_token_unwritable(tmp_path: Path, monkeypatch, capsys):
    blocker = tmp_path / "cadmcp"  # config dir blocked → mkdir fails
    blocker.write_text("occupied", encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    code = main(["serve", "--workspace", str(tmp_path / "ws")])
    assert code == 2  # no token → refuse (fail-closed, item 3)
    err = capsys.readouterr().err
    assert "INSECURE_BIND_REJECTED" in err and "token file unavailable" in err


def test_serve_allow_insecure_rejected_on_non_loopback(tmp_path: Path, capsys):
    audit_file = tmp_path / "audit.jsonl"
    code = main(["serve", "--host", "0.0.0.0", "--allow-insecure", "--audit-log", str(audit_file)])
    assert code == 2  # item 2: flag loopback-only
    err = capsys.readouterr().err
    assert "INSECURE_BIND_REJECTED" in err and "only for loopback bind" in err
    assert any(e["event"] == "insecure_bind_rejected" for e in _audit_events(audit_file))


def test_serve_stdio_mode_never_touches_token_file(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    import cadmcp.cli as cli_mod

    called: dict = {}
    monkeypatch.setattr(cli_mod, "_run_stdio", lambda server: called.setdefault("server", server))
    code = main(
        ["serve", "--transport", "stdio", "--workspace", str(tmp_path / "ws"),
         "--audit-log", str(tmp_path / "a.jsonl")]
    )
    assert code == 0 and "server" in called
    assert not (tmp_path / "cadmcp" / TOKEN_FILENAME).exists()  # stdio: no token file
