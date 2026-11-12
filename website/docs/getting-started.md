---
description: Install pycadmcp, run a health check, and wire Cursor, Claude Desktop, VS Code, or OpenCode to a Fake or live SolidWorks backend.
---

# Getting started

Install `cadmcp`, wire an MCP client, and run a health check. The same CLI drives
an offline **Fake** backend and a live **SolidWorks** backend.

## Requirements

| Mode | Needs |
|---|---|
| Fake (try MCP without CAD) | Python 3.11+ on Windows, macOS, or Linux |
| Live CAD | Windows + SolidWorks **2025** running + Python 3.11+ + `pywin32` |

## Install

```bash
pip install pycadmcp
```

The CLI entry point is `cadmcp`.

## Health check

```bash
cadmcp doctor --backend fake
```

With SolidWorks already running:

```bash
cadmcp doctor --backend solidworks
```

`doctor` prints one JSON report and exits non-zero when the backend cannot start.
Trimmed output from a Fake run:

```json
{
  "ok": true,
  "cadmcp_version": "0.1.0",
  "platform": "Windows-AMD64",
  "backend": { "kind": "fake", "available": true, "revision": "33.0", "error": null },
  "executor": { "state": "IDLE", "thread_alive": true, "backend_ready": true, "blocker": null },
  "registry": { "tools": 134 }
}
```

`executor.state` is `IDLE`, `BUSY`, or `STUCK`; `backend.error` carries the
`error.code` and message when attach fails. See [Troubleshooting](troubleshooting.md)
when `ok` is `false`.

## Connect an MCP client (stdio)

One command writes a server entry named `solidworks`, keeps every other entry in
the file, and is safe to re-run:

```bash
cadmcp install --client cursor      # or: claude | vscode | opencode
cadmcp install --client cursor --dry-run
```

| Client | `--client` | Config file it writes |
|---|---|---|
| Cursor | `cursor` | `~/.cursor/mcp.json` (Windows: `%USERPROFILE%\.cursor\mcp.json`) |
| Claude Desktop | `claude` | `%APPDATA%\Claude\claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`) |
| VS Code | `vscode` | `%APPDATA%\Code\User\mcp.json` (Linux/macOS: `~/.config/Code/User/mcp.json`) |
| OpenCode | `opencode` | `~/.config/opencode/mcp.json` |

`--dry-run` reports the path and whether the entry would change, without writing.

Manual equivalent:

```json
{
  "mcpServers": {
    "solidworks": {
      "command": "cadmcp",
      "args": [
        "serve",
        "--transport", "stdio",
        "--backend", "solidworks",
        "--profile", "part"
      ]
    }
  }
}
```

Use `"--backend", "fake"` when no CAD application is available. The default
`--profile part` exposes the part-modeling toolsets; [Tools](tools.md) lists the
other profiles.

## First result

Restart the client, open a chat, and ask for a simple part — for example the
100×50×10 mm plate with four Ø6 holes from the [home page](index.md). The agent
will call `new_part`, sketch tools, `extrude`, and `hole_wizard`.

If the agent reports a stuck executor, clear any dialog in SolidWorks and run
`cadmcp doctor` again. The recovery skill `cadmcp://skill/solidworks-recovery`
walks through the same steps inside the chat.

## HTTP transport (optional)

For URL-based clients, or to watch one long-running server:

```bash
cadmcp serve --transport http --backend solidworks
# MCP endpoint: http://127.0.0.1:8756/mcp
```

- HTTP is authenticated by default. A token is created at
  `%APPDATA%\cadmcp\token` (Windows) or `~/.config/cadmcp/token` (POSIX); send
  `Authorization: Bearer <token>`.
- `--host` / `--port` change the bind. `--allow-insecure` disables auth on
  loopback only — a non-loopback bind always requires the token.
- `GET /health` returns executor state without auth, which makes it a cheap
  liveness probe.

URL-based client entry:

```json
{
  "mcpServers": {
    "solidworks": {
      "url": "http://127.0.0.1:8756/mcp",
      "headers": { "Authorization": "Bearer <token>" }
    }
  }
}
```

## Upgrade and uninstall

```bash
pip install --upgrade pycadmcp
cadmcp install --client cursor      # refresh the entry after an upgrade
```

There is no uninstall subcommand: remove the `solidworks` entry from the client
config by hand, then `pip uninstall pycadmcp`. If you used the HTTP transport,
also delete the token file if you no longer need it.

## Next steps

- [Tools](tools.md) — profiles, toolset matrix, full inventory
- [Architecture](architecture.md) — STA, protocol, backends
- [Troubleshooting](troubleshooting.md) — when doctor says no
