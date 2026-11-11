# cadmcp

**Languages:** [English](README.md) · [简体中文](README.zh-CN.md) · [Deutsch](README.de.md) · [日本語](README.ja.md)

CAD MCP server: one process, a dedicated STA executor, and an offline-testable
Fake backend — **SolidWorks backend first**.

> **Not affiliated with Dassault Systèmes.** SolidWorks® is a trademark of
> Dassault Systèmes or its subsidiaries. This project is an independent
> community MCP server.

[![CI](https://github.com/pakupaku5260/cad-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/pakupaku5260/cad-mcp/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/pycadmcp.svg)](https://pypi.org/project/pycadmcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Requirements

| Mode | Needs |
|---|---|
| **Fake backend (default for CI)** | Python 3.11+, Windows/macOS/Linux |
| **SolidWorks backend** | Windows + SolidWorks **2025** (ProgID `SldWorks.Application` / `SOLIDWORKS_2025`) + `pywin32` |

The full offline test suite runs against **FakeBackend** — you do **not** need
SolidWorks installed to develop or verify locally.

## Install

```bash
pip install pycadmcp
```

For development (editable + test tools):

```bash
git clone https://github.com/pakupaku5260/cad-mcp.git
cd cad-mcp
python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

CLI entry point: `cadmcp`.

## Quick start

Health check (Fake):

```bash
cadmcp doctor --backend fake
```

### Use with an MCP client

Editors/agents spawn the server over **stdio** (recommended). After
`pip install pycadmcp`:

```bash
cadmcp install --client cursor      # or: claude | vscode | opencode
cadmcp install --client cursor --dry-run
```

That writes a server entry named `solidworks`. Equivalent manual JSON:

```json
{
  "mcpServers": {
    "solidworks": {
      "command": "cadmcp",
      "args": ["serve", "--transport", "stdio", "--backend", "solidworks", "--profile", "part"]
    }
  }
}
```

Use `"--backend", "fake"` when SolidWorks is not installed. HTTP transport is
for advanced local debugging only; MCP clients should use stdio.

Once connected, call tools from the client (for example copy
`examples/box_recipe.json` into the workspace and run `replay_recipe`).

Stdio serve (manual / scripts):

```bash
cadmcp serve --transport stdio --backend fake --profile part
```

For real SolidWorks, use `--backend solidworks` on Windows with SolidWorks running.

## Capability matrix

**134 tools** across 9 toolsets (see [docs/TOOL_INVENTORY.md](docs/TOOL_INVENTORY.md)):

| Toolset | Count | Focus |
|---|---|---|
| core | 45 | Documents, sketches, basic features, queries |
| features_adv | 25 | Thread, helix, sweep, surfaces, feature ops |
| assembly | 20 | Insert, mates, component ops |
| drawing | 16 | Views, annotations, DrawingSpec |
| sketch_adv | 12 | Splines, offset/trim, constraints, dims |
| sheetmetal | 7 | Base/flange/hem, flat pattern |
| selection | 6 | Face/edge pick helpers |
| view | 2 | Orientations / screenshots |
| export | 1 | STEP/STL/PDF/DXF |

Skills (`solidworks-modeling`, `solidworks-assembly`, `solidworks-recovery`)
ship as `cadmcp://skill/...` resources.

## Architecture (summary)

- **Protocol layer** shared by Fake and SolidWorks backends.
- **SolidWorks COM** runs only on a dedicated **STA** thread; business code
  never creates COM connections itself.
- Tool results use a typed OpResult envelope (`ok` / `error.code` / `delta` /
  `state_version`).

Details: [ARCHITECTURE.md](ARCHITECTURE.md). Naming history: [docs/naming.md](docs/naming.md).

## Testing

Offline (default):

```bash
ruff check .
pytest -q
python scripts/tool_inventory.py --check
```

Real SolidWorks (destructive):

```bash
# WARNING: closes all open SolidWorks documents WITHOUT saving.
set CADMCP_REAL_SW=1
pytest -q -m sw
```

Only run real-SW tests on disposable sessions.

## Known limitations

| Limitation | Notes |
|---|---|
| Mold Core/Cavity | Blocked pending reliable parting-surface / license context — [#1](https://github.com/pakupaku5260/cad-mcp/issues/1) |
| Native InsertThread API | Helix + sweep cut path is used instead — [#2](https://github.com/pakupaku5260/cad-mcp/issues/2) |
| SolidWorks Toolbox | Not integrated — [#3](https://github.com/pakupaku5260/cad-mcp/issues/3) |
| Part in-context edit (`EditPart2`) | Not supported; subassembly edit is — [#4](https://github.com/pakupaku5260/cad-mcp/issues/4) |
| Axial screw-in / feed mate motion | Not supported |

## License

[MIT](LICENSE) — Copyright (c) 2026 pakupaku5260.

Not affiliated with Dassault Systèmes. SolidWorks® is a trademark of
Dassault Systèmes or its subsidiaries.
