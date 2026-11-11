# Getting started

Install `cadmcp`, wire an MCP client, and run a health check. The same CLI
supports an offline **Fake** backend and a live **CAD** backend (SolidWorks 2025
on Windows today).

## Requirements

| Mode | Needs |
|---|---|
| Fake (try MCP without CAD) | Python 3.11+ on Windows, macOS, or Linux |
| Live CAD | Windows + SolidWorks **2025** running + Python 3.11+ + `pywin32` |

## Install

```bash
pip install pycadmcp
```

CLI entry point: `cadmcp`.

## Health check

```bash
cadmcp doctor --backend fake
```

With SolidWorks running:

```bash
cadmcp doctor --backend solidworks
```

## Connect an AI client (stdio)

One command writes a server entry for Cursor, Claude Desktop, VS Code, or OpenCode:

```bash
cadmcp install --client cursor      # or: claude | vscode | opencode
cadmcp install --client cursor --dry-run
```

That writes a server named `solidworks`. Manual equivalent:

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

Use `"--backend", "fake"` when no CAD application is available.

Restart the client, open a chat, and ask for a simple part (for example a plate
with corner holes). If the agent reports a stuck executor, run `cadmcp doctor`
again — recovery guidance is also available as
`cadmcp://skill/solidworks-recovery`.

## HTTP transport (optional)

For URL-based clients or local debugging:

```bash
cadmcp serve --transport http --backend solidworks
# MCP endpoint: http://127.0.0.1:8756/mcp
```

HTTP auth uses a token under `%APPDATA%\cadmcp\token` (Windows) or
`~/.config/cadmcp/token` (POSIX). Send `Authorization: Bearer <token>`.
`GET /health` reports executor state without auth.

## Next steps

- Browse the [tool matrix](tools.md)
- Read [architecture](architecture.md) (STA, protocol, backends)
- See [FAQ](faq.md) for limits and trademark notes
