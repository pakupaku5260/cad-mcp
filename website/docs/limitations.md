---
description: What cadmcp does not do yet — mold core/cavity, native threads, Toolbox, part in-context edit, screw-in motion — and when another approach fits better.
---

# Limitations

Five product limits are open today. Each is tracked as a GitHub issue unless
noted; the right-hand column is what agents fall back to.

| Limitation | Current state | Workaround | Issue |
|---|---|---|---|
| Mold core/cavity | Blocked — reliable parting surfaces need license and parting context | Split the mold manually, outside the agent loop | [#1](https://github.com/pakupaku5260/cad-mcp/issues/1) |
| Native `InsertThread` API | Not usable through the API; `insert_thread` builds the thread as helix + profile cut | Treat threads as approximate; no ISO tolerance zone | [#2](https://github.com/pakupaku5260/cad-mcp/issues/2) |
| SolidWorks Toolbox | Not integrated | Insert standard parts as normal components | [#3](https://github.com/pakupaku5260/cad-mcp/issues/3) |
| Part in-context edit (`EditPart2`) | Not supported; subassembly edit-in-place is | Edit the part in its own window, then rebuild the assembly | [#4](https://github.com/pakupaku5260/cad-mcp/issues/4) |
| Axial screw-in / feed mate motion | Not supported | Use a distance mate for the assembled state | — |

## When not to use cadmcp

- **Manufacturing output.** Threads are modeled as helix + profile cut, with no
  ISO tolerance zone; the tool surface is not a CAM or tolerance stack-up tool.
- **Batch jobs across many documents.** One process runs one serial executor by
  design; mutating calls are never queued.
- **CAD other than SolidWorks.** Only SolidWorks 2025 on Windows is implemented
  today, although the protocol is backend-neutral.
- **Unattended hosts without an interactive desktop.** SolidWorks needs a
  running GUI session; a modal dialog blocks COM until it is cleared.

## Reporting a limit

If a workflow is blocked, open an issue with the tool call, the error code from
the OpResult envelope, and the `cadmcp doctor` JSON. The error codes are
documented in [Troubleshooting](troubleshooting.md).
