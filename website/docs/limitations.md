---
description: What cadmcp does not do yet — mold core/cavity, Toolbox, part in-context edit, screw-in motion — and when another approach fits better.
---

# Limitations

Five product limits are open today. Each is tracked as a GitHub issue unless
noted; the right-hand column is what agents fall back to.

| Limitation | Current state | Workaround | Issue |
|---|---|---|---|
| Mold core/cavity | Blocked — reliable parting surfaces need license and parting context | Split the mold manually, outside the agent loop | [#1](https://github.com/pakupaku5260/cad-mcp/issues/1) |
| Thread Feature profiles / edge pick | Native geometry threads ship as `create_thread` (`IThreadFeatureData`); needs Thread Profiles + circular rim | Use `create_thread` for cut/extrude geometry; `insert_cosmetic_thread` for callouts only | [#2](https://github.com/pakupaku5260/cad-mcp/issues/2) |
| SolidWorks Toolbox | Not integrated | Insert standard parts as normal components | [#3](https://github.com/pakupaku5260/cad-mcp/issues/3) |
| Part in-context edit (`EditPart2`) | Not supported; subassembly edit-in-place is | Edit the part in its own window, then rebuild the assembly | [#4](https://github.com/pakupaku5260/cad-mcp/issues/4) |
| Axial screw-in / feed mate motion | Not supported | Use a distance mate for the assembled state | — |
| Part-view drawing BOM | **WONTFIX** (permanent) — BOM is assembly-view only; no part-view BOM tool will ship | Assembly `insert_bom`; part docs may `get_bom` as a single property rollup | — |
| Weld symbol coverage | Subset FILL/BUTT/BUSV/SPOT only; no full ASME weld table | Use `verify_weld_symbol` for shipped symbols; expand only with probe+golden | — |

## When not to use cadmcp

- **ISO tolerance-zone CAM threads.** `create_thread` builds SolidWorks Thread
  Feature geometry (cut/extrude); it is not a full ISO tolerance-zone CAM mesh.
  Use `insert_cosmetic_thread` when you only need callouts / `THREAD_*` props.
- **Parallel multi-document export.** `export_batch` is same-process serial
  (open→export→close); it is not a multi-SW / MES scheduler.
- **STEP-embedded custom properties.** P0 ships properties in
  `*.step.meta.json` sidecars; AP203/214 do not promise CPM inside STEP entities.
  AP242 needs SOLIDWORKS MBD (`PublishSTEP242File`); check `cadmcp doctor`
  → `mbd_step242`.
- **CAD other than SolidWorks.** Only SolidWorks 2025 on Windows is implemented
  today, although the protocol is backend-neutral.
- **Unattended hosts without an interactive desktop.** SolidWorks needs a
  running GUI session; a modal dialog blocks COM until it is cleared.

## Drawing: deferred until triggers fire

Release checklist is `inspect_drawing` + `verify_model(groups=["drawing"])`
(see `docs/recipes/drawing-release.md`). The following stay out until the
stated trigger is met — tell product when a trigger becomes true:

| Deferred | Trigger to reopen |
|---|---|
| Surface roughness | Controlled `.drwdot` has roughness fields; no-modal insert + reopen probe green |
| More weld symbols | Beyond FILL/BUTT/BUSV/SPOT — each needs SetText + type-8 probe + golden |
| “Full” ASME | Never as complete; only customer-named symbol subsets with probe+golden each batch |
| Auto layout | Optional external advisor only; DrawingSpec keeps explicit placement |
| Draft / thickness CHK | No-modal Draft/Thickness analysis API on a newer SW, or STEP→external DFM |

Part-view BOM is **not deferred** — it is permanently out (see table above).
Weld **insert** is shipped (`insert_weld_symbol`); remaining limits are readback caveats in the Limitations table.

## Reporting a limit

If a workflow is blocked, open an issue with the tool call, the error code from
the OpResult envelope, and the `cadmcp doctor` JSON. The error codes are
documented in [Troubleshooting](troubleshooting.md).
