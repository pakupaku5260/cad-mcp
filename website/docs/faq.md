---
description: Short answers about cadmcp — what it is, whether you need SolidWorks, which clients work, and where the source lives.
---

# FAQ

## What is cadmcp?

An MCP server that bridges AI clients and CAD design tools. Agents call
modeling tools over MCP; a dedicated executor runs the CAD side. SolidWorks
2025 on Windows is supported today; the protocol is built so additional CAD
backends can follow the same surface.

## Do I need SolidWorks to try it?

No. Use `--backend fake` for install, client wiring, and offline checks on any
OS. Real geometry in SolidWorks requires Windows, SolidWorks 2025 running, and
`--backend solidworks`.

## Which AI clients work?

Any MCP host that can spawn a stdio server or connect over Streamable HTTP —
including Cursor, Claude Desktop, VS Code, and OpenCode. `cadmcp install --client`
writes the entry for those four; see [Getting started](getting-started.md).

## What are the known limits?

Mold core/cavity, native threads, Toolbox, part in-context edit, and screw-in
motion each have a documented workaround or a reason they are unsupported. The
full list lives on [Limitations](limitations.md).

## Something is stuck. Where do I look?

[Getting started](getting-started.md) covers setup; [Troubleshooting](troubleshooting.md)
covers a stuck executor, COM attach failures, ports, and tokens.

## Where is the source / license?

- Repository: [pakupaku5260/cad-mcp](https://github.com/pakupaku5260/cad-mcp)
- Package: [pycadmcp on PyPI](https://pypi.org/project/pycadmcp/)
- License and trademark notes: [Legal](legal.md)
