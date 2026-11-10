# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
once public tags are cut.

## [Unreleased]

### Added

- Public project facade: MIT license, four-language READMEs, CONTRIBUTING,
  SECURITY, ARCHITECTURE, CHANGELOG, and CI workflow.
- `examples/box_recipe.json` for `replay_recipe` quick start.
- Naming gate (`tests/architecture/test_naming.py`) and [docs/naming.md](docs/naming.md).

### Changed

- Product identity is **cadmcp** (distribution, import, CLI). SolidWorks COM
  backend lives under `cadmcp.backend.solidworks` with `--backend solidworks`.
- Resource URIs use `cadmcp://`; environment variables use `CADMCP_*`.

### Removed

- Compatibility shims for the pre-rename package name (`backend/base.py`,
  `com_backend.py`, `fake_backend.py`, `compat/`). See [docs/naming.md](docs/naming.md).

## [0.1.0] — TBD

First public source release (GitHub). PyPI packaging is deferred.
