---
description: How cadmcp is put together — protocol and backends, the STA executor for COM, layering rules, and API stability.
---

# Architecture

Product runtime constraints for `cadmcp`: what any CAD COM maintainer must
preserve. This is not an internal agent playbook.

## Glossary

| Term | Meaning |
|---|---|
| **MCP host** | The application that starts or connects to the server and exposes its tools to a model: Cursor, Claude Desktop, VS Code, OpenCode. |
| **Agent** | The model loop inside the host. It picks a tool, reads the result, and decides the next call. |
| **Tool** | One typed MCP operation such as `extrude` or `hole_wizard`, with a JSON schema. |
| **Toolset** | A named group of tools (`core`, `assembly`, `drawing`, …). Nine in total. |
| **Profile** | A preset list of toolsets a session exposes (`part` by default). See [Tools](tools.md). |
| **Backend** | The implementation behind the protocol: `fake` or `solidworks`. |
| **Executor** | The one dedicated thread that runs every backend call. Reports `IDLE` / `BUSY` / `STUCK`. |
| **STA** | Single-Threaded Apartment — the COM threading model SolidWorks requires. |
| **OpResult** | The typed envelope every tool returns: `ok` / `error.code` / `delta` / `state_version`. |
| **Skill** | Markdown usage guidance served as `cadmcp://skill/...`. |

## Backends

| Backend | Role |
|---|---|
| Protocol | Shared models, validators, `CADBackend` surface |
| Fake | Offline engine for CI and local verification |
| Live CAD | Real application automation (SolidWorks 2025 on Windows today) |

Fake and live CAD are peer implementations of the same protocol. Business
mixins must not open their own COM connections or import composition modules
casually across domains.

## STA (live CAD / COM)

All COM work runs on a dedicated Single-Threaded Apartment (STA) thread:

1. Every COM call goes through the STA executor.
2. Business mixins must not open their own COM connections.
3. COM objects must not be used from other threads.
4. COM objects must not be passed across threads.
5. COM init / attach / release / exception mapping stay on the STA lifecycle.
6. Thread start / stop / ready / error state remain explicit.
7. COM reference release is audited carefully.

Business code reaches COM only through `infrastructure.py`, the sole
business-side facade over `sta.py`.

## Layering

```text
toolsets / kernel / executor
        ↓
backend protocol models
        ↓
fake   ┃  live CAD (solidworks)
       ┃     ↓
       ┃  infrastructure → sta
```

- Naming / feature aliases and sketch lifecycle stay in their owning modules.
- COM failure codes are mapped in `sta.py` only.
- Tool results use a typed OpResult envelope (`ok` / `error.code` / `delta` /
  `state_version`).

## API stability

Do not casually rename public tools, change default arguments, reorder COM
call sequences, or alter OpResult / error envelopes.

## Skills and resources

Skills under `cadmcp/resources/content/skills/` are exposed as
`cadmcp://skill/...` (and related `cadmcp://help/...` topics).
