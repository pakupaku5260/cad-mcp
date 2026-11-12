---
description: License, trademark notice, and privacy notes for cadmcp.
---

# Legal

## License

`cadmcp` is released under the [MIT License](https://github.com/pakupaku5260/cad-mcp/blob/main/LICENSE),
Copyright (c) 2026 pakupaku5260. You may use, modify, and redistribute it,
including commercially, provided the copyright notice and permission notice are
kept.

## Trademarks

`cadmcp` is an independent community project. It is **not affiliated with,
endorsed by, or sponsored by** Dassault Systèmes. SOLIDWORKS® is a registered
trademark of Dassault Systèmes SolidWorks Corporation. The name is used only to
describe which CAD application this server can drive; no Dassault logos, icons,
or other brand assets are included.

## Privacy

- **No telemetry.** The server sends nothing to the project or to third parties.
- **Local by default.** HTTP binds `127.0.0.1` and requires a bearer token; the
  token is generated on first start and stored at `%APPDATA%\cadmcp\token`
  (Windows) or `~/.config/cadmcp/token` (POSIX).
- **Local files.** `cadmcp` writes a workspace under your user directory
  (override with `--workspace`) and an audit log at
  `%APPDATA%\cadmcp\audit.jsonl` or `~/.config/cadmcp/audit.jsonl`
  (`--audit-log` overrides it). The audit log records serve start/stop events.
- **Your client is separate.** Tool calls and results are exchanged with the MCP
  client and its model provider under their own terms, not this project's.
