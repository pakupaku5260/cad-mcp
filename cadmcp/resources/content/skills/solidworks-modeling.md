---
name: solidworks-modeling
description: Part modeling stop conditions, first checks, common errors, and forbidden ops.
---

# SolidWorks modeling

Use this skill for single-part prismatic / revolved / loft / sheet-metal work.
Read `cadmcp://help/workflow` for the canonical call order; do not invent parallel APIs.

Default server profile is `part` (`cadmcp serve` / install). If a needed tool is missing from
`tools/list`, call `list_toolboxes` then `open_toolbox` (e.g. `features_adv`, `sheetmetal`,
`selection`, `view`). Use `--profile full` only when you intentionally want every toolset.

## When to stop

- Stop after `get_geometry` / `get_mass_properties` shows the expected volume and face count.
- Stop if `rebuild.ok` is false or `rebuild.feature_errors` is non-empty — fix or delete the bad feature before adding more.
- Stop if a cut/extrude returns `ok` but volume is unchanged — the sketch likely missed the solid; re-sketch, do not stack blind retries.
- Stop when the part is saved (`save_document`) and optionally exported (`export` to `.step`/`.stl`).

## Check first

1. `get_active_document` — must be a part.
2. `list_planes` / `list_features` / `list_sketch_entities` before editing.
3. After ANY geometry change, re-run `get_faces` / `get_edges` / `get_vertices` —
   bare indexes go stale. Pass `x,y,z` on `select_face`/`select_edge`
   (`cadmcp://help/selectors`). Prefer `get_faces(kind, query)` over remembered indexes.
4. Sketch tools create **no** driving dims. Before `end_sketch`, call
   `add_sketch_dimension` if PARAM/RECIPE will `set_dimension`/`update_parameters`
   the profile. Then `list_dimensions` → `set_dimension` or `set_equation`.

## Common errors

| Code | Next action |
|---|---|
| `NO_ACTIVE_DOCUMENT` | `new_part` or `open_document` |
| `NO_ACTIVE_SKETCH` | `start_sketch` before draw tools |
| `SKETCH_NOT_FOUND` | Use `list_sketch_entities` / finished sketch name |
| `FEATURE_CREATE_FAILED` | Check sketch closed, end condition, or missing solid for cuts |
| `FEATURE_NOT_FOUND` | Refresh names via `list_features` / `list_planes` |
| `INVALID_ARGUMENT` | Follow `error.hint`; do not retry with the same args |
| `REF_NOT_FOUND` / `REF_AMBIGUOUS` | Re-fetch handles with coordinates from `get_entities` |
| `PATH_OVERWRITE_DENIED` | Pass `overwrite=true` only when intentional |

Retry a mutation only when `error.side_effect == "none"`. If `applied`, re-read geometry.

## Forbidden

- Do not call Toolbox / native `InsertThread` / bolt generators — not available.
- Do not use `thin` together with `up_to_surface` / `up_to_next` / `up_to_vertex`.
- Do not put non-zero `z`/`cz` on a 2D sketch; use `start_sketch(plane=3D)` for 3D paths.
- Do not treat approximate `insert_thread` as a tolerance-class standard thread.
- Do not write unimplemented tool names into plans; check `help` topic `limits`.
- Do not reuse face/edge indexes after mutations without re-fetching coords.
- Do not expect sketch sizes in `list_dimensions` without `add_sketch_dimension`.

## Cases

### 1. Simple plate
Pre: `new_part` if no part.
Seq: `start_sketch` → `sketch_rectangle` → `end_sketch` → `extrude` → `get_mass_properties`.
Stop: volume matches; `examples/skill_case_1_plate.json`.
Recover: `NO_ACTIVE_SKETCH` → start; `FEATURE_CREATE_FAILED` → close profile.

### 2. Constraint + fillet pattern
Pre: open `sketch_adv` if `add_sketch_relation` missing.
Seq: sketch → `add_sketch_relation` → `extrude` → `fillet` → `linear_pattern` → `get_geometry`.
Stop: counts stable; `examples/skill_case_2_fillet_pattern.json`.
Recover: `FEATURE_NOT_FOUND` → `list_features`; stale edges → re-`get_edges`.

### 3. Surface + thicken
Pre: `list_toolboxes` → `open_toolbox` (`features_adv`).
Seq: closed sketch → `extrude_surface` → `thicken` → `get_mass_properties`.
Stop: volume > 0; `examples/skill_case_3_surface_thicken.json`.
Recover: open sheet → thicken fails; use closed profile.
