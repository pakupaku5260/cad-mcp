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

from typing import NamedTuple

MIME_TYPE = "text/markdown"


class Topic(NamedTuple):
    """One topic: one-line resources/list description + Markdown body."""

    description: str
    text: str


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
   `parting_line(pull_face, edges?)` mold parting line (omit edges = all solid edges);
   `parting_surface(parting_line?)` mold parting surface from a parting line;

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
   `set_lightweight(component, lightweight)` toggles lightweight vs fully resolved
   (`list_components` / `get_component` echo `lightweight`). Does not suppress.
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
        description="OpResult envelope: ok/result/error shape, hint, side_effect retry rules.",
        text="""# Result and error envelope

Every tool answers one JSON envelope; a domain error is a normal result carrying
`isError=true` and `ok=false` (not a protocol failure).

- `ok=true` -> `result` holds the payload; the envelope may also carry `delta`,
  `rebuild`, `state_version`, `warnings`.
- `ok=false` -> `error = {code, message, hint, side_effect, context}`:
  - `message` explains why; `hint` is the next action, written to be actionable
    (it often names the exact tool or argument to change) - follow it.
  - `side_effect`: `none` = nothing happened, safe to retry as-is;
    `applied` = the change happened but a complete result was not read back - do NOT
    retry blindly, re-read state (`get_geometry` / `list_features`) first.
  - `context` = machine-readable detail (nearest distance, candidate indexes, ...).

Frequent codes: `INVALID_ARGUMENT` (fix the argument per hint), `NO_ACTIVE_DOCUMENT`
(call `new_part` or `open_document` first), `NO_ACTIVE_SKETCH`, `EXECUTOR_BUSY`
(one operation runs at a time; wait briefly, then retry), `REF_NOT_FOUND` /
`REF_AMBIGUOUS` (refresh handles via `get_entities`), `PATH_OUTSIDE_SANDBOX` /
`PATH_OVERWRITE_DENIED` (workspace sandbox: file paths stay inside the workspace,
overwrite only with explicit `overwrite=true`).
""",
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
    "limits": Topic(
        description="Out of scope: drawing BOM table insert, Toolbox, axial feed.",
        text="""# Scope limits

This server covers prismatic and revolved parts, solid loft (`loft` / `loft_cut`),
sheet metal (`base_flange` / `edge_flange` / `sheet_metal_unfold`),
ISO drill holes (`hole_wizard` on a planar `get_faces` index),
approximate threads (helix plus a 60° sweep cut via `insert_thread`), assembly mates
(including in-context subassembly edit via `edit_component` / `end_edit` / `get_edit_target`),
exploded views (`explode_view` / `show_exploded` / `list_exploded_views`),
part materials (`set_material` / `get_material`), configurations
(`list_configurations` / `set_configuration`), drawings (`new_drawing` /
`create_drawing_view` / `create_section_view` / `insert_model_items` /
`insert_balloons` / `export`), assembly BOM rollup (`get_bom`), and drawing BOM
tables (`insert_bom` on an assembly drawing view, then `get_bom`).

Still **no tools** in this project (frozen):

- Toolbox / standard parts
- Native SolidWorks `InsertThread` (not in the type library)
- A bolt or nut generator; axial feed / screw-in motion

Call `help` with `workflow` / `selectors` for what this server actually does.
""",
    ),
}
