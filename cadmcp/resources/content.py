"""Static help content (v4 §8 boundary): MCP resources and help(topic) share one source.

§8 hard rule (from SolidPilot ADR-069→077): near-static bulk docs that live as
MCP resources must also keep an equivalent tool entry — resources sit in the
client action space, not the model's; clients without a resource bridge can
only reach the same text via the help tool. Therefore:

- Store each topic's body once here; resources/read and help(topic) both read it
  (never duplicate — drift is a bug; same-source assertion tests guard this);
- URI shape ``cadmcp://help/<topic>`` with no version (bumping breaks pointers in
  tool descriptions);
- Content is model-facing: short, actionable — when to call what, how to read
  results, how to self-correct — not implementation detail; prefer fewer tokens
  over completeness.

Topics cover conventions models get wrong most often: modeling order, units,
error envelope, and reference handles.
"""
from __future__ import annotations

from collections.abc import Callable

from cadmcp.errors import render_errors_help

MIME_TYPE = "text/markdown"


class Topic:
    """One topic: one-line resources/list description + Markdown body.

    ``text`` may be a static string or a zero-arg loader (F3: errors help from CATALOG).
    ``help(topic)`` / ``resources/read`` both read ``.text`` — same source.
    """

    __slots__ = ("description", "_text", "_text_loader")

    def __init__(
        self,
        description: str,
        text: str | None = None,
        *,
        text_loader: Callable[[], str] | None = None,
    ) -> None:
        if text is None and text_loader is None:
            raise ValueError("Topic requires text or text_loader")
        if text is not None and text_loader is not None:
            raise ValueError("Topic accepts either text or text_loader, not both")
        self.description = description
        self._text = text
        self._text_loader = text_loader

    @property
    def text(self) -> str:
        if self._text_loader is not None:
            return self._text_loader()
        assert self._text is not None
        return self._text


TOPICS: dict[str, Topic] = {
    "workflow": Topic(
        description="Canonical modeling sequence, verify_delta/state_version semantics, retry rules.",
        text="""# Modeling workflow

Canonical sequence for a new part:

1. `new_part` (or `open_document`)
2. `start_sketch(plane)` -> sketch entities (`sketch_rectangle` / `sketch_circle` / `sketch_line` / `sketch_arc`) -> `end_sketch`.
   `list_planes` lists defaults plus `create_plane` names (`Plane1`). Offset a plane with
   `create_plane(reference, offset)`; angle with `mode=angle` plus `axis` (from `create_axis`
   or `+x/+y/+z`) and `angle_deg`; three points with `mode=points` and `points=[[x,y,z],...]`.
   `create_axis` takes two planes or a line `edge`.
   `list_sketch_entities` / `sketch_status` inspect the open sketch; `edit_sketch(name)` re-enters a finished one.
   Draw a spline with `sketch_spline(points, closed)`; offset a contour with
   `sketch_offset(distance, inward)`; fillet two segments with
   `sketch_trim(entity1, entity2, radius)` (CreateFillet); mirror about a line with `sketch_mirror(axis)`.
   Sketch tools do **not** create driving dimensions. Call `add_sketch_dimension`
   before `end_sketch` whenever PARAM / RECIPE will later change the profile size
   (`set_dimension` / `update_parameters`); otherwise `list_dimensions` only shows
   feature dims (e.g. extrude depth), not sketch width/diameter.
   On Top Plane, sketch +Y is model +Z (COM CreateLine +Y is model −Z; the backend flips it).
3. `extrude` / `revolve` (add material) or `extrude_cut` (remove material);
   `extrude`/`extrude_cut` take `direction` (blind/midplane/both/through_all/up_to_next/up_to_surface/up_to_vertex),
   optional `depth2`, `reverse`, `end_face` (get_faces index, required for up_to_surface),
   `end_vertex` (get_vertices index, required for up_to_vertex),
   and `thin`+`thickness` (`thin_type=one|mid|both`; not with up_to_*).
   Omit depth for through_all / up_to_*. Those need an existing solid. `revolve` may pass `edge` from `get_edges` (line on the sketch plane).
   Change a feature or sketch dimension with `list_dimensions` then `set_dimension`
   (e.g. `D1@Boss-Extrude1`, `D1@Sketch1`; revolve angles in degrees).
   Drive sizes with `set_equation` / `list_equations` (global `"D" = 80`, then bind a dimension).
4. optional detail: `fillet` / `chamfer` / `shell` / `linear_pattern` / `circular_pattern` /
   `mirror` / `loft` (two ended sketches; optional `guides` that pierce every profile; `loft_cut` needs a solid);
   3D sketch: `start_sketch(plane=3D)` then `sketch_line` with z1/z2 (path for `sweep`; no 2D circle/rect in 3D);
   surfaces: `extrude_surface` then `thicken` (closed contour) or `knit` (two sheets; open knit cannot thicken);
   `fill_surface` caps a sheet-body edge; `boundary_surface` from two ended sketches;
   `rib(thickness)` from an ended line sketch; `draft(angle_deg, faces, neutral)` with get_faces indexes;
   `combine(op=add|cut|common)` on multi-body parts (disjoint extrudes);
   `split_body(plane)` cuts a solid with a reference plane into multiple bodies;
   `parting_line(pull_face, edges?)` mold parting line
   (omit edges = pull-face boundary loop; pass edges for a custom closed chain);
   `parting_surface(parting_line?, radiate?, offset?)` mold parting surface
   (Live: radiate=true + offset>0 recommended; tree-visible only);
   `tooling_split(sketch?, depth1?, depth2?, angle_deg?)` mold tooling split / 切削分割
   (needs parting_line + parting_surface sheets + mold-block sketch);

   `hole_wizard(face, diameter, end=through_all|blind)` ISO drill on a planar face
   (omit x,y to place at the face centroid; blind needs `depth`);
   sheet metal: `base_flange(thickness)` from a closed sketch, `edge_flange(edge, length)`
   on a `get_edges` outline index, then `sheet_metal_unfold` for flat length/width
   (`fillet`/`chamfer` take `radius`/`distance` plus optional `target` or `edges`;
   `chamfer` also takes `angle_deg` default 45;
   `shell` takes optional `faces` indexes for openings; omit for a closed shell)
5. optional: `set_material` (part grade) / `set_configuration(name, create=true)`
6. verify: `get_mass_properties` or `get_geometry`
7. `save_document` (set `overwrite=true` explicitly to replace an existing file)
8. optional drawing: `new_drawing` then `create_drawing_view(path, view=front)`;
   `insert_model_items` (model dimensions), `create_section_view`, `insert_balloons`
   (assembly views), then `export`
9. assembly: `insert_component` (.sldprt or .sldasm) then `mate(type=coincident|concentric|...)`
   (solved pose on `get_component` / `list_components`;
   `children=true` flattens `p1-1@sub-1`). `move_component` / `rotate_component`
   (`relative` for deltas; `about=origin|world` or `pivot`; `absolute` replaces orientation;
   `force` writes through mates and breaks mate intent). `list_components` / `get_component`;
   `pattern_component` writes a circular (`axis`) or linear (`dx`/`dy`/`dz`)
   component pattern (count includes the seed; delete the feature to drop copies).
   `edit_component` enters in-context edit of a **subassembly** instance (`Edit Assembly`);
   `get_edit_target` reports the instance or `editing=false` at the top;
   `end_edit` returns to the parent. Part in-context edit is not supported.
   `set_lightweight` / `set_suppressed` / `set_flexible` (subasm only); pose echoes
   `lightweight`/`suppressed`/`flexible`. `mate` adds `gear` (ratio_*) and `width` (entity3).
   `explode_view` creates an exploded view; `show_exploded(show)` collapses or shows it;
   `list_exploded_views` lists names. Axial feed / screw-in is not supported.
   `get_faces(kind, query)` picks max_z planes or axis_z cylinders without guessing indexes.
   `set_color` / `get_color` on parts (RGB 0–1). `get_bom` after inserting.

Rules:

- One open sketch at a time. `extrude`, `revolve` and `extrude_cut` consume the LAST
  finished sketch unless you pass `sketch=<name>`.
- Mutating tools with `verify_delta` return `delta` (before/after geometry fingerprint;
  `changed` lists what actually moved) and `rebuild` (SolidWorks rebuild health).
  Results may carry `warnings` - advisory flags on suspicious geometry changes (e.g.
  volume up after a cut, unchanged after an extrude); when one appears, read
  `get_geometry` and reason about it before continuing.
- `state_version` is echoed by every result and increments on each successful mutation
  made through this server. A value that differs from your last read means out-of-order
  or replayed calls: re-read state before mutating again.
- `state_version` does NOT see edits made by a human in the SolidWorks GUI; for those,
  compare `get_geometry` fingerprints (volume, area, bbox, face/edge counts).
- Retry policy: read-only tools are always safe to retry. Retry a mutation only when
  `error.side_effect == "none"`; if it is `applied`, the change happened - re-read
  state instead of retrying.
""",
    ),
    "units": Topic(
        description="Which unit each field is in, and how unit conversion is applied.",
        text="""# Units

- Length-bearing inputs take `unit` (default `mm`; enum listed in each schema).
  Every call converts independently: you may use different units in different calls,
  but numbers inside one call must be consistent.
- Results echo their unit family in `length_unit` / `area_unit` / `volume_unit`
  (e.g. mm, mm2, mm3). `mass_kg` is kilograms regardless of the length unit.
- Coordinates returned by `get_entities` / `get_selection` are in that response's
  `length_unit`; feed them back unchanged when re-referencing geometry.
- Internally the engine is SI; raw SI values never appear in responses.
""",
    ),
    "errors": Topic(
        description=(
            "OpResult envelope: ok/result/error shape, hint, side_effect retry rules, "
            "and per-code remediation (auto/action/requires_confirmation)."
        ),
        # Lazy: generated from CATALOG so help(errors) ≡ resources/read(cadmcp://help/errors).
        text_loader=render_errors_help,
    ),
    "selectors": Topic(
        description="Face/edge handle format, exact/proximity tolerance rules, staleness.",
        text="""# Faces and edges: handles

Two tools list geometry references; both return `index` plus coordinates in
`length_unit`:

- `get_entities` - every face (`centroid`) and edge (`midpoint`) of the active document.
- `get_selection` - entities the user manually picked in the SolidWorks GUI, re-validated
  and mapped to the same form; each item reports `quality`.

A handle is the pair (index, coordinates). Resolution is redone fresh on every call,
never cached:

1. An `index` hit counts as `quality: "exact"` only if its stored coordinates match
   within 0.5 mm - a stale index that shifted fails this check instead of matching
   the wrong entity.
2. Otherwise the nearest entity within 2 mm wins (`quality: "proximity"`): usable, but
   verify `kind` and coordinates before acting on it.
3. Nothing within tolerance -> `REF_NOT_FOUND` (the error states the nearest distance);
   two candidates tied within numerical epsilon -> `REF_AMBIGUOUS` listing candidate
   indexes. The server never guesses between candidates.

Indexes shift after ANY geometry change (extrude, fillet, shell, pattern, ...). After
mutating, re-run `get_entities` / `get_faces(kind, query)` and carry back the CURRENT
index and coordinates together - the pair is what makes a handle verifiable.
Never call `select_face` / `select_edge` with only a remembered index after a
mutation; always include `x,y,z` from the latest query (or re-query by semantics).

Bring coordinates back on `select_face` / `select_edge` as optional `x,y,z`, or on
mates as `'instance#face:N:x,y,z'` / `'#edge:N:x,y,z'` (same `length_unit`, default mm).
Kind-relative refs `'#cylinder:N'` / `'#plane:N'` / `'#cone:N'` / `'#circle:N'` count only matching
faces or edges (N is 0-based in that subset). `get_component_faces` / `get_component_edges`
accept optional `kind` and still return the global `index`. `list_mates` / `delete_mate`
inspect and remove mates by name. `check_interference` reports overlapping components
(`interfere` / `contact` / `unknown`); coincident faces are not interference unless
`coincident_as_interference` is true. Thread-mesh contact may be `unknown` when the
API cannot tell contact from solid overlap.
""",
    ),
    "task_layer": Topic(
        description="Three call layers (primitive/domain/task) and synchronous task limits.",
        text="""# Task layer

## Layers (`TOOL_LAYERS`)

- **primitive** — backend atomic call (single COM/API step).
- **domain** — domain capability (default for most tools).
- **task** — one MCP call carries a full intent (`design_run`, `batch`, `task_status`,
  `task_list`). Call-granularity is atomic; internals are **not** transaction-atomic
  (wrap with `tx_*` when rollback is required).

## Synchronous only

The task layer is **synchronous**. There is **no** cancel, priority, per-document
lock/epoch, or async job queue in this release. `task_status` / `task_list` read an
in-process ledger (last 100 jobs, FIFO); state does not survive process restart.

## Tools

- `batch` — serial tool steps with step/duration caps
- `design_run` — DesignSpec controlled run (also layer=task)
- `task_status(job_id)` / `task_list(limit, offset)` — read-only job queries
""",
    ),
    "design_spec": Topic(
        description="DesignSpec schema_version 1: kind/doc/params/variants/features/checkpoints/verify/outputs.",
        text="""# DesignSpec (schema_version 1)

Declarative modeling intent. Validate with `design_spec_validate` (read-only).
Execute with `design_run` (optional `variant` selects a design-table row).

## Required

- `schema_version`: must be `1`
- `kind`: `part` | `assembly` | `drawing`
- `doc.title`: non-empty string
- `doc.units`: `mm` | `inch`
- `features`: non-empty array of objects with:
  - `name` (unique, non-empty)
  - `tool` (non-empty string; registry check at run time)
  - `args` (object)

## Optional

- `params`: map of number | bool | string (base design-table row)
- `variants`: object map `{row_name: {param: scalar}}` — compact design table.
  Each row overrides matching `params` keys when `design_run(variant=row_name)`.
  Omit `variant` or leave `variants` empty → base `params` only (current behaviour).
  Unknown `variant` / empty table with a name → `INVALID_ARGUMENT` (precheck, zero
  side effects). Payload does **not** echo the selected variant.
- `features[].assert`: object; keys ⊆ `ok` | `error_code` | `result_keys` | `delta_changed`
- `features[].depends_on`: array of feature names (must exist, no cycles)
- `checkpoints`: subset of feature names; successful steps capture L1 snapshots
- `verify.groups`: subset of `geometry` | `features` | `mass_bbox` | `assembly` | `drawing`
- `verify.thresholds`: object (same vocabulary as `verify_model`)
- `outputs[]`: `{kind: step|stl|pdf|dxf, path}` — kind must match file suffix;
  exported after steps+verify (`overwrite=false`)

## Param placeholders (design_run)

Anywhere inside `features[].args`, replace a value with `{"$param": "<name>"}` to
pull from effective params (base ∪ selected variant). Nested objects/arrays are
walked recursively. Unknown names or non-scalar `$param` values → `INVALID_ARGUMENT`
with a JSON path (e.g. `design_spec.features[1].args.diameter`).

## Tools

- `design_spec_validate` — read-only load + validate
- `design_run` — topological execute (not atomic; use `tx_*` for rollback). Optional
  `variant` selects a design-table row.

## Minimal example

```json
{
  "schema_version": 1,
  "kind": "part",
  "doc": {"title": "Base plate", "units": "mm"},
  "params": {"thickness": 8.0},
  "variants": {"thick": {"thickness": 12.0}, "thin": {"thickness": 4.0}},
  "features": [
    {"name": "base", "tool": "extrude", "args": {"depth": {"$param": "thickness"}}, "assert": {"ok": true}},
    {"name": "holes", "tool": "hole_wizard", "args": {"diameter": 6.0}, "depends_on": ["base"]}
  ],
  "checkpoints": ["base"],
  "verify": {"groups": ["geometry", "features"], "thresholds": {}},
  "outputs": [{"kind": "step", "path": "out/base.step"}]
}
```

Errors use `INVALID_ARGUMENT` with a JSON path (e.g. `design_spec.features[2].tool`
or `design_spec.variants.thick.thickness`) or path sandbox codes from
`ensure_input_path`.
""",
    ),
    "rules": Topic(
        description="Machine-checkable model rules via check_rules (not doctor).",
        text="""# Model rules (`check_rules`)

Read-only domain tool (`toolset=rules`, `bypass_queue`). Collects a fact snapshot
via inline dispatch of existing query tools, then evaluates pure rules in
`cadmcp.rules`. Reuses the `Verification` carrier (`status`/`checks`/`evidence`);
does **not** change outer `OpResult.ok`.

This is **not** `cmd_doctor` / install diagnostics (#23).

## Tool

`check_rules(rules=null)` — `rules=null` runs all ten; a string array runs a
subset. Unknown names → `INVALID_ARGUMENT`. Payload keys:
`{verification, rules_run, skipped}` (no raw facts, no timestamps).

## Skip semantics

When a required fact is unavailable (query failed / not applicable), the rule
goes to `skipped: [{name, reason}]` and is **not** a failed check. Non-assembly
documents skip `no_interference` with reason `not an assembly`.

## Rules (fixed list of 10)

| name | fact keys | pass when |
|---|---|---|
| `active_document` | `active_document` | fact present |
| `units_declared` | `active_document.units` | `mm` or `inch` |
| `feature_tree_present` | `active_document` + `features` | part/assembly and feature count ≥ 1 |
| `positive_dimensions` | `part_parameters.dimensions` | every `value` > 0 |
| `equations_nonempty` | `part_parameters.equations` | every equation RHS non-empty |
| `configuration_present` | `part_parameters.configurations` | count ≥ 1 |
| `sketches_constrained` | `sketch_statuses[].state` | no `under_defined` |
| `no_unsaved_edits` | `active_document.modified` | `modified == false` |
| `no_interference` | `interference.count` | assembly and `count == 0` |
| `document_saved` | `active_document.saved` | `saved == true` |

Fact sources (readonly only; never `verify_model`): `get_active_document`,
`list_features`, `part_parameters`, `sketch_status`, `check_interference`.
""",
    ),
    "assembly_dof": Topic(
        description="Heuristic assembly DOF estimate via check_assembly_dof (not a true solver).",
        text="""# Assembly DOF (`check_assembly_dof`)

Read-only domain tool (`toolset=assembly`, `bypass_queue`). Collects
`get_active_document` / `list_components` / `list_mates`, then evaluates pure
heuristics in `cadmcp.assembly_dof`. Reuses the `Verification` carrier; does
**not** change outer `OpResult.ok`. Never calls `verify_model`.

**risk: unverified** — heuristic lower bound, **not** a SolidWorks DOF solver.
Overconstraint, redundancy, and constraint coupling are not modeled.

## Non-assembly / empty

If the active document is missing or not an assembly, the tool returns
`status=not_applicable` **without** calling `list_mates` / `list_components`
(avoids `INVALID_ARGUMENT` from those tools). An assembly with zero components
is also `not_applicable` (verification `unverified`).

## Mate-type weights (heuristic)

| mate_type | constrained DOF | note |
|---|---|---|
| coincident | 3 | 1 translation + 2 rotation |
| concentric | 4 | 2 translation + 2 rotation |
| distance | 1 | 1 translation |
| angle | 1 | 1 rotation |
| tangent | 1 | 1 translation |
| screw | 2 | translation/rotation coupling |

Unknown `mate_type` → `constrained_dof=null`, listed in `unknown_mate_types`
(contributes 0).

## remaining formula

`total_dof = 6 × n_components`  
`constrained = Σ MATE_DOF[t]`  
`remaining = max(0, total_dof − constrained)`

`unmated_components` is a coarse spanning-tree deficit
`max(0, n_components − 1 − n_mates)` because `list_mates` does not expose
mate↔component links (do not treat it as exact).

## assembly_order

`order` = `list_components` enumeration order (`basis:
component_enumeration_order`). This is an insertion / GetComponents proxy,
**not** a mate-graph topological order (would need `MateInfo.components`).

## Payload keys

`status`, `verification`, `dof_estimate`, `assembly_order`, `mates`,
`unknown_mate_types`, `assumptions`, `risk`.
""",
    ),
    "drawing_preflight": Topic(
        description="DrawingSpec text preflight via check_drawing_spec (not verify_model).",
        text="""# DrawingSpec preflight (`check_drawing_spec`)

Read-only domain tool (`toolset=drawing`, `bypass_queue`). Parses a DrawingSpec
JSON with `load_drawing_spec`, then runs pure checks in `cadmcp.drawing_preflight`.
Reuses the `Verification` carrier; does **not** change outer `OpResult.ok`.
Never opens/creates a drawing and never calls `verify_model`.

**Not** `verify_model` `drawing.completeness` (publish readiness of an existing
drawing) and **not** `inspect_drawing` (live drawing fact snapshot).

**risk: unverified** — text self-consistency only; does not guarantee
`create_drawing` succeeds on live SolidWorks.

## Skip semantics

Optional fields omitted → that check goes to `skipped: [{name, reason}]` and is
**not** a failed check (same idea as F16 rules).

## Checks (fixed list of 8)

| name | pass when | skip when |
|---|---|---|
| `spec_loadable` | `load_drawing_spec` succeeded | — |
| `has_sheets` | `sheets` length ≥ 1 | `sheets` omitted (L2 form) |
| `has_views` | ≥1 view across sheets / top-level | `views` omitted |
| `valid_view_orientations` | each `orient`/`orientation` ∈ front/back/left/right/top/bottom/isometric | views omitted |
| `valid_gdt_symbols` | each `gdt.symbol` ∈ `GDT_SYMBOLS` | `gdts` omitted |
| `valid_bom_types` | `bom.type` ∈ `BOM_TYPES` | `bom` omitted |
| `title_block_keys_wellformed` | keys ⊆ `TITLE_BLOCK_DEFAULT_KEYS`, no dupes | `title_block` omitted |
| `no_duplicate_sheet_names` | sheet names unique | `sheets` omitted |

Enum sources: `cadmcp.backend.protocol.constants` (`GDT_SYMBOLS`, `BOM_TYPES`,
`TITLE_BLOCK_DEFAULT_KEYS`) plus `VIEW_ORIENTATIONS` aligned with `drawing_spec`.

## Payload keys

`status`, `verification`, `checks_run`, `skipped`, `assumptions`, `risk`.
""",
    ),
    "bend_allowance": Topic(
        description="Pure bend-allowance estimate via calc_bend_allowance (not unfold).",
        text="""# Bend allowance (`calc_bend_allowance`)

Read-only domain tool (`toolset=sheetmetal`, `bypass_queue`). Computes a
neutral-axis bend allowance from **explicit** thickness, K-factor, and bend
angle/radius parameters in `cadmcp.sheetmetal_calc`. Reuses the `Verification`
carrier; does **not** change outer `OpResult.ok`. Never reads the model and
never calls `sheet_metal_unfold` or `sheet_metal_bend_table`.

**Not** a SolidWorks flat-pattern / unfold. **risk: unverified**.

## Formula (SI meters inside the pure module)

`BA = radians(angle_deg) × (radius + k_factor × thickness)`

Tool layer converts lengths with `unit` (default mm) to/from meters.

## Checks (fixed list of 6)

| name | pass when |
|---|---|
| `thickness_positive` | thickness > 0 |
| `k_factor_in_range` | 0 < k_factor < 1 |
| `bends_nonempty` | ≥ 1 bend |
| `angles_in_range` | every bend 0 < angle_deg ≤ 180 |
| `radii_nonnegative` | every bend radius ≥ 0 |
| `values_finite` | all numeric inputs finite |

If any check fails → `status=failed` and `bend_allowances=[]` (no partial BA).

## Assumptions

- Formula estimate only; not a live SolidWorks unfold / flat-pattern
- K-factor commonly 0.3–0.5 for mild steel; caller supplies the value
- radius is the inside bend radius
- flat length ≈ straight segments + `total_bend_allowance` (straights not summed here)

## Payload keys

`status`, `verification`, `bend_allowances`, `total_bend_allowance`, `unit`,
`assumptions`, `risk`.
""",
    ),
    "doctor_matrix": Topic(
        description="Interpret cadmcp doctor JSON via check_doctor_matrix (not live doctor).",
        text="""# Doctor matrix (`check_doctor_matrix`)

Read-only domain tool (`toolset=diagnostics`, `bypass_queue`, profile **full** only).
Interprets a caller-supplied `cadmcp doctor` JSON object with the declarative
matrix in `cadmcp.doctor_matrix`. Reuses the `Verification` carrier; does **not**
change outer `OpResult.ok`.

**Does not** run `cadmcp doctor`, Executor, backend, or COM. **Not** the
`status` / `/health` live executor snapshot.

**risk: unverified** — report interpretation only.

## Skip semantics

Missing `source_path` → that row goes to `skipped: [{name, reason}]` and is
**not** a failed Verification check.

## Severity

`blocker` / `warning` / `info` appear on each `matrix[]` row as metadata only.
Severity does **not** change `Verification` / `status` calculation.

## Checks (fixed list of 14)

| id | source_path | pass when |
|---|---|---|
| `env.python` | `python` | nonempty |
| `env.platform` | `platform` | nonempty |
| `env.workspace` | `workspace` | nonempty |
| `version.cadmcp_version` | `cadmcp_version` | nonempty |
| `backend.available` | `backend.available` | `True` |
| `backend.revision` | `backend.revision` | nonempty |
| `backend.mbd_step242` | `backend.mbd_step242` | `True` |
| `backend.error` | `backend.error` | empty (`null` or `""`) |
| `executor.backend_ready` | `executor.backend_ready` | `True` |
| `executor.not_stuck` | `executor.state` | `!= "STUCK"` |
| `executor.no_blocker` | `executor.blocker` | `null` |
| `registry.tools` | `registry.tools` | ≥ 1 |
| `registry.toolsets` | `registry.toolsets` | ≥ 1 entries |
| `notes` | `notes` | field present |

## Payload keys

`status`, `verification`, `checks_run`, `skipped`, `matrix`, `assumptions`,
`risk`.
""",
    ),
    "part_strategies": Topic(
        description="Part-type strategy catalog via list_part_strategies (not a generator).",
        text="""# Part strategies (`list_part_strategies`)

Read-only domain tool (`toolset=design`, `bypass_queue`). Returns a catalog of
part-type strategies backed by `examples/*.json` recipes in
`cadmcp.part_strategies`. **Does not** run recipes, `design_run`, or
`replay_recipe`.

## Catalog (4)

| id / part_type | source_recipe | required_toolsets |
|---|---|---|
| `plate` | `examples/skill_case_1_plate.json` | core |
| `box` | `examples/box_recipe.json` | core |
| `fillet_pattern` | `examples/skill_case_2_fillet_pattern.json` | core, sketch_adv |
| `surface_thicken` | `examples/skill_case_3_surface_thicken.json` | core, features_adv |

Each row also has `description`, `feature_tools` (registered tool names), and
`key_params` (illustrative dimensions from the recipe).

## Filter

`part_type=null` (default) → all four. Unknown `part_type` → empty `strategies`
(still `ok=true`, `count=0`).

## Payload keys

`ok`, `strategies`, `count`.
""",
    ),
    "limits": Topic(
        description="Out of scope: drawing BOM table insert, Toolbox, axial feed.",
        text="""# Scope limits

This server covers prismatic and revolved parts, solid loft (`loft` / `loft_cut`),
sheet metal (`base_flange` / `edge_flange` / `sheet_metal_unfold`),
ISO drill holes (`hole_wizard` on a planar `get_faces` index),
cosmetic threads (`insert_cosmetic_thread` + `THREAD_*` properties),
native Thread Features (`create_thread` via `IThreadFeatureData` / cut|extrude),
assembly mates (including in-context subassembly edit via `edit_component` /
`end_edit` / `get_edit_target`), exploded views (`explode_view` / `show_exploded` /
`list_exploded_views`), part materials (`set_material` / `get_material`), configurations
(`list_configurations` / `set_configuration`), drawings (`new_drawing` /
`create_drawing_view` / `create_section_view` / `insert_model_items` /
`insert_balloons` / `export`), assembly BOM rollup (`get_bom`), and drawing BOM
tables (`insert_bom` on an assembly drawing view, then `get_bom`).

Still **no tools** in this project (frozen):

- Toolbox / standard parts
- A bolt or nut generator; axial feed / screw-in motion

Note: SW2025 has no COM member named `InsertThread`; geometry threads use
`create_thread` (official Thread Feature). Call `help` with `workflow` /
`selectors` for what this server actually does.
""",
    ),
}
