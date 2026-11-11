# Contributing

Thanks for helping improve **cadmcp**.

## Where to send changes

Open a pull request against **this repository** for bug fixes, docs, and
examples. Maintainers may rework commits before they land in a release; do not
rely on PR commit SHAs staying unchanged on `main`.

## Development setup

```bash
git clone https://github.com/pakupaku5260/cad-mcp.git
cd cad-mcp
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -e ".[dev]"   # or: uv sync
```

Offline checks (no SolidWorks required):

```bash
ruff check .
pytest -q
python scripts/tool_inventory.py --check
```

Architecture gate (structural invariants):

```bash
pytest -q tests/architecture/
```

## HTTP transport (local debugging)

`cadmcp serve --transport http` starts a Streamable HTTP listener on
`127.0.0.1:8756` by default — MCP endpoint `http://127.0.0.1:8756/mcp`,
health monitoring at `/health`. HTTP mode is authenticated by default: a
bearer token is auto-created at `%APPDATA%\cadmcp\token` (Windows) or
`~/.config/cadmcp/token` (POSIX); send it as `Authorization: Bearer <token>`.
`--allow-insecure` disables auth on loopback only — non-loopback binds
always require the token. MCP clients should prefer stdio; HTTP is for
local debugging and monitoring.

## Real SolidWorks tests (destructive)

```bash
# WARNING: closes all open SolidWorks documents WITHOUT saving.
set CADMCP_REAL_SW=1
pytest -q -m sw
```

Only run real-SW tests on disposable sessions.

## Coding rules (short)

- Keep tool names, schemas, and COM call order stable unless the PR is an
  intentional breaking change.
- SolidWorks COM must stay on the STA path — see [ARCHITECTURE.md](ARCHITECTURE.md).
- Prefer asserting `error.code` over brittle message substrings.
- Do not add compatibility aliases for removed legacy package names
  (see [docs/naming.md](docs/naming.md)).

## Pull requests

1. One concern per PR when practical.
2. Include offline test results in the description.
3. Update [CHANGELOG.md](CHANGELOG.md) for user-visible changes.
4. DE/JA README edits should keep chapter structure aligned with `README.md`
   (English is authoritative).

## Security

See [SECURITY.md](SECURITY.md). Do not file public issues for vulnerabilities.
