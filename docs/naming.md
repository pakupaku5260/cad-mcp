# Naming

Effective 2026-11-10. One name for the product, one name per backend, no
compatibility aliases.

## Names

| Thing | Name |
|---|---|
| Distribution, import package, CLI | `cadmcp` |
| Package docstring | "CAD MCP server; SolidWorks backend first." |
| CAD-neutral layer | `cadmcp/backend/protocol/` |
| Fake backend | `cadmcp/backend/fake/` |
| SolidWorks backend | `cadmcp/backend/solidworks/` |
| `--backend` values | `fake`, `solidworks` |
| MCP client server key written by `cadmcp install` | `solidworks` |
| Skill / help resource URIs | `cadmcp://skill/...`, `cadmcp://help/...` |
| Environment variables | `CADMCP_REAL_SW`, `CADMCP_VIS` |

Skill ids (`solidworks-modeling`, `solidworks-assembly`,
`solidworks-recovery`) keep the backend name: they describe SolidWorks
procedures, not the product.

## What changed

| Before | After |
|---|---|
| `swmcp` (dist / import / CLI) | `cadmcp` |
| `swmcp.backend.com` | `cadmcp.backend.solidworks` |
| `swmcp.backend.com_backend` | `cadmcp.backend.solidworks.backend` |
| `swmcp.backend.fake_backend` | `cadmcp.backend.fake.backend` |
| `SwMcpError` | `CadMcpError` |
| `SwBackend` | `CADBackend` |
| `swmcp/backend/base.py`, `com_backend.py`, `fake_backend.py`, `swmcp/compat/` | deleted |
| `--backend com` | `--backend solidworks` |
| client server key `swmcp` | `solidworks` |
| `SWMCP_REAL_SW` / `SWMCP_VIS` | `CADMCP_REAL_SW` / `CADMCP_VIS` |
| `swmcp://...` resources | `cadmcp://...` |

There is no shim: the old import paths, the `com` backend value, the old
server key and the old environment variables are gone. Tests that imported the
old modules were deleted or updated in the same change.

## Manually configured clients

Hand-written MCP client entries must use:

```json
{
  "mcpServers": {
    "solidworks": {
      "command": "cadmcp",
      "args": ["serve", "--transport", "stdio", "--backend", "solidworks", "--profile", "part"]
    }
  }
}
```

Running `cadmcp install --client …` performs the same update. If a legacy
`swmcp` entry exists, it is removed first; its config file is copied to
`<config>.bak` before the write.

## Historical names that stay

`tests/architecture/test_naming.py` fails on `swmcp` or `solidworks-mcp` in
any tracked file. These are exempt by design:

- `docs/naming.md` and `tests/architecture/test_naming.py` — must name the
  legacy tokens to document / enforce the gate.
- `cadmcp/backend/api_baseline_s0.json` — frozen S0 evidence.
- `cadmcp/backend/migration_map.yaml`, `migration_scope.yaml` — `original:`
  fields record pre-rename module paths; only `target:` paths are live.
- Dated design docs, handoff notes, `archive/`, `deliverables/`,
  `internal-evidence/` — historical records, not rewritten.
- `docs/参考项目研读笔记.md` — notes on third-party projects that are
  themselves named `solidworks-mcp`.
- Lines marked `naming-gate: allow-legacy` — only the legacy client-key
  constant in `cadmcp/install_client.py` and its test.

`scripts/snapshot_api_s0.py` was deleted with the monolithic backend: it
imported the removed modules and its output is frozen, so it can never run
again. `scripts/snapshot_com_sequence.py` keeps only `--compare` against the
frozen S0 baseline.
