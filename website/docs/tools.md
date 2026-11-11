# Tools

**134** tools across **9** toolsets. Fake and live CAD backends share the same
protocol surface; profiles select which toolsets a session exposes.

## Toolset matrix

| Toolset | Count | Focus |
|---|---|---|
| `core` | 45 | Documents, sketches, basic features, queries |
| `features_adv` | 25 | Thread, helix, sweep, surfaces, feature ops |
| `assembly` | 20 | Insert, mates, component operations |
| `drawing` | 16 | Views, annotations, DrawingSpec |
| `sketch_adv` | 12 | Splines, offset/trim, constraints, dimensions |
| `sheetmetal` | 7 | Base/flange/hem, flat pattern |
| `selection` | 6 | Face/edge pick helpers |
| `view` | 2 | Orientations / screenshots |
| `export` | 1 | STEP / STL / PDF / DXF |

## What agents typically call

- **Part modeling** — `new_part`, sketch tools, `extrude`, fillets, holes, threads
- **Inspect** — mass properties, bbox, feature tree, face/edge queries
- **Assemblies** — insert components, mates, component ops
- **Drawings & sheet metal** — views, annotations, flange / flat pattern
- **Export** — STEP, STL, PDF, DXF from the conversation

## Skills

Usage skills ship as resources:

- `cadmcp://skill/solidworks-modeling`
- `cadmcp://skill/solidworks-assembly`
- `cadmcp://skill/solidworks-recovery`

## Full inventory

The complete per-tool table (names, params, mutating flags) is generated from
the registry — see
[`docs/TOOL_INVENTORY.md`](https://github.com/pakupaku5260/cad-mcp/blob/main/docs/TOOL_INVENTORY.md)
in the repository. Verify locally with:

```bash
python scripts/tool_inventory.py --check
```
