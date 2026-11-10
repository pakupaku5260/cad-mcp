---
name: solidworks-recovery
description: Recover from errors, modal blockers, stale handles, and partial mutations.
---

# SolidWorks recovery

Use this skill when a call failed, the model looks wrong, or the executor reports busy/stuck.
Read `cadmcp://help/errors` for the OpResult envelope.

## When to stop

- Stop retrying after two identical failures with the same args — change the plan.
- Stop and ask the user if `status` shows a modal blocker or `EXEC_BLOCKED` / `EXEC_STUCK`.
- Stop stacking features on a part whose `rebuild.ok` is already false.
- Stop when `side_effect=applied` and you have not yet re-read geometry — never blind-retry.

## Check first

1. Call `status` — if busy, wait; if stuck/blocker, do not keep mutating.
2. If the tool name is missing from `tools/list`, call `list_toolboxes` / `open_toolbox`
   (default profile is `part`; assembly/drawing tools may be closed).
3. `get_active_document` — confirm doc type and that the expected file is still active.
4. `get_geometry` + `list_features` — establish ground truth after any `applied` failure.
5. Refresh selectors: `get_entities` / `get_faces` / `get_edges` with current
   coordinates; never reuse bare indexes after a mutation — pass `x,y,z`.
6. For sketch trouble: `sketch_status`, `list_sketch_entities`, or `edit_sketch` then fix.
7. For path errors: stay inside the workspace; use `overwrite=true` only when intended.

## Common errors

| Code | Next action |
|---|---|
| `EXECUTOR_BUSY` / `QUEUE_FULL` | Wait, then retry once |
| `EXEC_TIMEOUT` / `EXEC_STUCK` | Call `status`; do not launch parallel mutating tools |
| `EXEC_BLOCKED` | Modal dialog — user must dismiss in SolidWorks GUI |
| `COM_CALL_FAILED` / `COM_ATTACH_FAILED` | Check SolidWorks is running; run `cadmcp doctor` |
| `STATE_VERSION_MISMATCH` | Re-read state; do not replay an old mutation sequence |
| `DOCUMENT_CHANGED_EXTERNALLY` | GUI edit detected — re-fingerprint with `get_geometry` |
| `REBUILD_FAILED` | Inspect `rebuild.feature_errors`; `delete_feature` or fix dims |
| `BATCH_PARTIAL_FAILURE` | Some steps applied — continue from current geometry, not from step 0 |

## Forbidden

- Do not kill the SolidWorks process from the agent.
- Do not expose or call raw `_call` / COM escape hatches.
- Do not assume `ok=true` means geometry is correct — read `delta.changed` and `warnings`.
- Do not default unverified work to “verified”; if checks were not run, say so.
- Do not retry `applied` errors with the same mutation; re-read, then choose a new step.
