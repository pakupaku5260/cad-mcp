# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
once public tags are cut.

## [0.4.0] - 2026-11-19（release-prep；公开发布待第二次放行）

### Added

- Session dialog tools: `session_dialogs` / `session_respond` with fail-closed
  whitelist (`restart` / `save_all` / `low_memory` / `progress`).
- Additive `list_components_lite` for large assemblies; `CADMCP_TOOL_TIMEOUTS`
  env override for per-tool budgets.
- Sketch profile conflict precheck (`SKETCH_PROFILE_CONFLICT`); task-layer
  `fix_components` for mate repair.
- `verify_model` grouped partial results (`partial_on_timeout`, bounded retries);
  `check_interference` additive `volume_unit` / converted `volume`.
- `verify_step_readback` tool + Fake contracts (live SW2025 STEP import remains
  an environment limitation — see Known Limitations).

### Changed

- Active-document path: silent `SaveAs3` Options=1 so `GetPathName` propagates.
- Token quotas raised (TOTAL 25000; sheetmetal profile 9500); tool count **170**.
- Datum-plane UV mapping documentation corrected via geometric probe.

### Known Limitations

- Live STEP readback into SolidWorks 2025: `LoadFile4` / `OpenDoc` return
  `err=1` for any STEP (including a minimal self-export); still fails after a
  controlled restart. Tool + Fake contracts are present; do not treat as a
  verified live round-trip.

## [0.3.0] - 2026-11-18


### Added

- Persistent entity references (`ref_id`) on face/edge/vertex handles with
  `REF_STALE` / `REF_UNSUPPORTED` remediation.
- `verify_model` (toolset `verification`): geometry, features, mass/bbox,
  assembly interference, and drawing completeness checks.
- Error remediation metadata on the catalog; `cadmcp://help/errors` lists
  per-code auto/action/confirmation guidance.
- Transaction skeleton (`tx_begin` / `tx_status` / `tx_commit` / `tx_rollback`):
  L1 checkpoint + journal, and L2 reload/discard/compensate paths. All rollback
  modes verified on real SolidWorks, including a `ROLLBACK_FAILED` injection.
- `COM_LOST` detection and STA `reattach()` with at-most-once executor retry.
  Both reconnect branches verified on real SolidWorks: DispatchEx auto-launch
  and user manual-restart (GetActiveObject) reattach.
- Document context guards: optional `expect_title` / `expect_path` on mutating
  tools, `WRONG_DOCUMENT`, and `list_open_documents`.
- Numeric fingerprint mode and `scripts/bench.py` baseline regression gate.
- Tiered tool-description budgets (6000/4000) with 20% headroom, profile caps,
  TOTAL gate, and inventory status-card drift checks.
- DesignSpec validate + planner (`design_spec_validate` / `design_run`):
  topological feature runs, `$param` substitution, L1 checkpoints with
  `resume_from`, declared outputs export, and design-table `variant` rows.
- Task layer: `batch`, `task_status`, `task_list`, and tool `layer`
  (`primitive` / `domain` / `task`).
- Rules engine (`check_rules`) with ten machine-checkable model rules.
- Assembly DOF heuristic (`check_assembly_dof`).
- DrawingSpec text preflight (`check_drawing_spec`) before `create_drawing`.
- Pure bend-allowance estimate (`calc_bend_allowance`) from explicit K-factor
  parameters (not a live flat-pattern).
- Doctor report matrix (`check_doctor_matrix`) interpreting `cadmcp doctor`
  JSON without live probes.
- Part strategy catalog (`list_part_strategies`) over `examples/*.json`
  recipes (metadata only; does not execute recipes).
- Advanced assembly operations: `set_suppressed` / `set_flexible` /
  `replace_component`, plus gear/width mate types on `mate`. The cam mate
  type is frozen as BLOCKED (S0) — see `docs/internal/cam-capability-matrix.md`.
- Mold parting line now defaults to the pull-face edge loop.

### Changed

- Version frozen at 0.3.0 for m1 close-out; public release waits for m2+m3
  (this card closes m3 documentation).

## [0.2.0] - 2026-11-13

### Added

- Expanded `solidworks-modeling` skill with three short cases and matching
  offline recipes under `examples/skill_case_*.json`.
- Deterministic Agensi skill package builder
  (`scripts/build_skill_package.py`) with core tool-schema digest.
- Public export gates: `scripts/export_public.py --ref` / `--check` /
  `--verify`, plus architecture coverage.
- Release version gate (`scripts/check_release.py`).

### Changed

- Skill body size limit raised to 4096 bytes (single source in
  `cadmcp.skills`).
- `write_mcpb_manifest` takes version from `cadmcp.__version__`.

### Fixed

- Moved internal backend notes (`structural_changes.md`,
  `com_sequence_baseline_diff.md`) out of the package tree so they are no
  longer shipped in public export / sdist.

## [0.1.0] - 2026-11-10

First public release on GitHub and PyPI (`pip install pycadmcp`;
import/CLI remain `cadmcp`).

### Added

- Public project facade: MIT license, four-language READMEs, CONTRIBUTING,
  SECURITY, ARCHITECTURE, CHANGELOG, and CI workflow.
- Three usage skills (`solidworks-modeling`, `solidworks-assembly`,
  `solidworks-recovery`) as `cadmcp://skill/*` resources.
- `replay_recipe` / `examples/box_recipe.json` for offline recipe playback.
- `part_parameters` / parametric update path and mutation `verification`
  payloads on geometry-changing tools.
- Whitelist public export script and naming gate
  (`tests/architecture/test_naming.py`, [docs/naming.md](docs/naming.md)).
- README MCP client usage (install helper + manual stdio JSON).

### Changed

- Product identity is **cadmcp** (distribution, import, CLI). SolidWorks COM
  backend lives under `cadmcp.backend.solidworks` with `--backend solidworks`.
- Resource URIs use `cadmcp://`; environment variables use `CADMCP_*`.
- Public GitHub home is https://github.com/pakupaku5260/cad-mcp
  (copyright / authors / security contact: `pakupaku5260`).

### Removed

- Compatibility shims for the pre-rename package name (`backend/base.py`,
  `com_backend.py`, `fake_backend.py`, `compat/`). See [docs/naming.md](docs/naming.md).

## [Unreleased]
