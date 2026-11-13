# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
once public tags are cut.

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
