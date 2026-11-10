"""Wave 7 dist: install_client idempotent and legacy-key migration."""
from __future__ import annotations

import json
from pathlib import Path

from cadmcp.install_client import install_client, write_mcpb_manifest


def test_install_client_idempotent(tmp_path: Path, monkeypatch):
    cfg = tmp_path / "mcp.json"
    monkeypatch.setattr(
        "cadmcp.install_client._config_path",
        lambda client: cfg,
    )
    r1 = install_client("cursor")
    assert r1["changed"] is True
    assert cfg.is_file()
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert "solidworks" in data.get("mcpServers", {})
    # Keep existing entries
    data["mcpServers"]["other"] = {"command": "echo"}
    cfg.write_text(json.dumps(data), encoding="utf-8")
    r2 = install_client("cursor")
    assert r2["changed"] is False
    data2 = json.loads(cfg.read_text(encoding="utf-8"))
    assert "other" in data2["mcpServers"]
    assert data2["mcpServers"]["solidworks"]["command"] == "cadmcp"
    assert data2["mcpServers"]["solidworks"]["args"] == [
        "serve", "--transport", "stdio", "--backend", "solidworks", "--profile", "part",
    ]


def test_install_client_migrates_legacy_entry(tmp_path: Path, monkeypatch):
    cfg = tmp_path / "mcp.json"
    monkeypatch.setattr(
        "cadmcp.install_client._config_path",
        lambda client: cfg,
    )
    cfg.write_text(
        json.dumps({"mcpServers": {"swmcp": {"command": "swmcp"}}}),  # naming-gate: allow-legacy
        encoding="utf-8",
    )
    result = install_client("cursor")
    assert result["migrated_from"] == "swmcp"  # naming-gate: allow-legacy
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert "swmcp" not in data["mcpServers"]  # naming-gate: allow-legacy
    assert data["mcpServers"]["solidworks"]["command"] == "cadmcp"
    assert cfg.with_name(cfg.name + ".bak").is_file()


def test_write_mcpb_manifest(tmp_path: Path):
    path = write_mcpb_manifest(tmp_path)
    assert path.is_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["name"] == "cadmcp"
    assert "cursor" in data["clients"]
