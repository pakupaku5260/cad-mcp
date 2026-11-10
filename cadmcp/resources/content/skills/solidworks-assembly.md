---
name: solidworks-assembly
description: Assembly insert/mate stop conditions, first checks, common errors, and forbidden ops.
---

# SolidWorks assembly

Use this skill for rigid assemblies: insert parts/subassemblies, mates, patterns, interference.
Read `cadmcp://help/workflow` and `cadmcp://help/selectors` for mate entity syntax.

Start with `--profile assembly` (or `open_toolbox` for `assembly` + `selection` + `view` +
`export` if the server was launched with the default `part` profile). Prefer
`list_toolboxes` / `search_tools` over guessing tool names.

## When to stop

- Stop when mates solve and `get_component` origins/bboxes match the intended pose.
- Stop after `check_interference` reports no `interfere` pairs (contact-only is usually OK).
- Stop after `get_bom` / `save_document` (and optional `export` of the assembly STEP).
- Stop if `move_component` / `rotate_component` fails without `force` — that is expected when mates constrain the part; do not blindly pass `force`.

## Check first

1. `get_active_document` — must be an assembly (`new_assembly` if needed).
2. `list_components` before mating; use returned instance names (`part-1`).
3. Resolve faces/edges with `get_component_faces` / `get_component_edges` (optional `kind`).
4. Prefer kind refs: `part-1#cylinder:0`, `part-1#plane:0` — refresh after any move or pattern.
5. After mates, re-read `get_component` — pose must be the **solved** pose, not the insert offset.
6. Subassembly in-context: `edit_component` → work → `end_edit`; confirm with `get_edit_target`.

## Common errors

| Code | Next action |
|---|---|
| `NO_ACTIVE_DOCUMENT` | `new_assembly` or `open_document` |
| `INVALID_ARGUMENT` | Wrong mate `type` params (`distance`/`angle_deg`/`pitch` are mutually exclusive) |
| `FEATURE_CREATE_FAILED` | Mate geometry incompatible, or move blocked by mates (omit `force`) |
| `FEATURE_NOT_FOUND` | Bad component/mate name — `list_components` / `list_mates` |
| `PATH_NOT_FOUND` | Component path must be inside the workspace |
| `REF_NOT_FOUND` / `REF_AMBIGUOUS` | Re-query component faces with coordinates |
| `SELECT_FAILED` | Entity not selectable in current edit target |

One mate tool: `mate(type=concentric|coincident|distance|angle|tangent|screw, ...)`.

## Forbidden

- Do not use `force=true` on move/rotate unless intentionally breaking mate intent.
- Do not attempt part in-context edit (`EditPart2`) — only subassembly `edit_component`.
- Do not expect axial feed / screw-in motion from `mate(type=screw)`.
- Do not suppress components; lightweight toggle is `set_lightweight` only.
- Do not insert Toolbox fasteners; use saved `.sldprt` + configurations instead.
