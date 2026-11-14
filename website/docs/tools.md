---
description: Profiles and toolsets exposed by cadmcp, with the tool count for each.
---

# Tools

Fake and live CAD backends share the same protocol surface. A **profile** decides
which toolsets a session exposes, so the agent only sees the tools that match the
document it is working on.

## Toolset matrix

--8<-- "_generated/toolset-matrix.md"

## Profiles

`--profile` sets the initial tool surface. Pick the one that matches the job:

| Profile | Toolsets | Use when |
|---|---|---|
| `part` (default) | `core`, `sketch_adv`, `features_adv`, `selection`, `view`, `export` | Part modeling, inspection, export |
| `assembly` | `core`, `assembly`, `selection`, `view`, `export` | Assemblies, components, mates |
| `drawing` | `core`, `drawing`, `view`, `export` | Drawings and annotations |
| `sheetmetal` | `core`, `sheetmetal`, `selection`, `view`, `export` | Sheet metal parts and flat patterns |
| `full` | all nine | Exploration; the largest surface |

Smaller surfaces are cheaper for the model and easier to audit. Change the
surface mid-session with `open_toolbox` / `close_toolbox`, or override the
profile with an explicit list:

```bash
cadmcp serve --transport stdio --backend solidworks --profile assembly
cadmcp serve --transport stdio --backend solidworks --toolsets core,drawing
```

## What agents typically call

- **Part modeling** — `new_part`, sketch tools, `extrude`, fillets, holes, threads
- **Inspect** — mass properties, bbox, feature tree, face/edge queries
- **Assemblies** — insert components, mates, component ops
- **Drawings & sheet metal** — views, annotations, flange / flat pattern
- **Export** — STEP, STL, PDF, DXF from the conversation

## Skills

Usage skills ship as MCP resources and teach an agent when to stop, what to query
first, and which operations to avoid:

- `cadmcp://skill/solidworks-modeling`
- `cadmcp://skill/solidworks-assembly`
- `cadmcp://skill/solidworks-recovery`

`solidworks-modeling` is also published standalone on
[Agensi](https://www.agensi.io/skills/solidworks-modeling).

## Full inventory

The per-tool table (names, parameters, mutating flags) is generated from the
registry and lives in the repository:
[docs/TOOL_INVENTORY.md](https://github.com/pakupaku5260/cad-mcp/blob/main/docs/TOOL_INVENTORY.md).

Both that file and the matrix above are checked in CI, so they cannot drift from
the code. Verify locally with:

```bash
python scripts/tool_inventory.py --check
```
