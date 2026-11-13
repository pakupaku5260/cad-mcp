"""Client config install (wave 7 DIST): idempotent MCP config merge, preserving existing entries.

The server key is the CAD backend it drives (`solidworks`), so a second CAD
backend can register alongside it instead of overwriting the entry.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from cadmcp import __version__

CLIENTS = ("claude", "vscode", "opencode", "cursor")

_SERVER_NAME = "solidworks"
_COMMAND = "cadmcp"
_ARGS = ["serve", "--transport", "stdio", "--backend", "solidworks", "--profile", "part"]
# Pre-rename client entry (server key and command both `swmcp`); removed on install.  # naming-gate: allow-legacy
_LEGACY_SERVER_NAME = "swmcp"  # naming-gate: allow-legacy


def _config_path(client: str) -> Path:
    home = Path.home()
    if client == "claude":
        if sys.platform == "win32":
            base = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
            return base / "Claude" / "claude_desktop_config.json"
        return home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if client == "vscode":
        if sys.platform == "win32":
            base = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
            return base / "Code" / "User" / "mcp.json"
        return home / ".config" / "Code" / "User" / "mcp.json"
    if client == "cursor":
        if sys.platform == "win32":
            base = Path(os.environ.get("USERPROFILE") or home)
            return base / ".cursor" / "mcp.json"
        return home / ".cursor" / "mcp.json"
    if client == "opencode":
        return home / ".config" / "opencode" / "mcp.json"
    raise ValueError(client)


def _server_entry() -> dict[str, Any]:
    return {
        "command": _COMMAND,
        "args": list(_ARGS),
    }


def install_client(client: str, *, dry_run: bool = False) -> dict[str, Any]:
    if client not in CLIENTS:
        raise ValueError(f"Unknown client {client!r}; choose {', '.join(CLIENTS)}")
    path = _config_path(client)
    existing: dict[str, Any] = {}
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
    if not isinstance(existing, dict):
        existing = {}

    # Claude Desktop (mcpServers) vs Cursor/VS Code (mcpServers or servers)
    key = "mcpServers"
    if "mcpServers" not in existing and "servers" in existing:
        key = "servers"
    servers = existing.setdefault(key, {})
    if not isinstance(servers, dict):
        servers = {}
        existing[key] = servers

    before = json.dumps(servers.get(_SERVER_NAME), sort_keys=True) if _SERVER_NAME in servers else None
    servers[_SERVER_NAME] = _server_entry()
    after = json.dumps(servers[_SERVER_NAME], sort_keys=True)
    changed = before != after

    migrated_from = None
    legacy = servers.get(_LEGACY_SERVER_NAME)
    if isinstance(legacy, dict) and legacy.get("command") == _LEGACY_SERVER_NAME:
        del servers[_LEGACY_SERVER_NAME]
        migrated_from = _LEGACY_SERVER_NAME

    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        if migrated_from and path.is_file():
            shutil.copy2(path, path.with_name(path.name + ".bak"))
        path.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    # Minimal in-repo MCPB manifest for packaging
    return {
        "client": client,
        "path": str(path),
        "changed": changed,
        "server": _SERVER_NAME,
        "migrated_from": migrated_from,
        "dry_run": dry_run,
    }


def write_mcpb_manifest(repo_root: Path) -> Path:
    """Write mcpb/manifest.json (not published to Smithery)."""
    dest = repo_root / "mcpb" / "manifest.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": "cadmcp",
        "version": __version__,
        "description": "CAD MCP server (SolidWorks backend via dedicated STA COM executor)",
        "command": _COMMAND,
        "args": list(_ARGS),
        "clients": list(CLIENTS),
    }
    dest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return dest


__all__ = ["CLIENTS", "install_client", "write_mcpb_manifest"]
