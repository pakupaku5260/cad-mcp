# Contributing

Thanks for helping improve **cadmcp**.

## Where to send changes

| Kind of change | Where |
|---|---|
| Public bug fixes, docs, examples | Open a **GitHub** pull request against the public repo |
| Day-to-day product development | Happens on the **internal Gitee** tree (whitelist export → GitHub) |

Do **not** treat the GitHub mirror as the primary development remote. Maintainers
merge GitHub PRs, then **patch-back** the diff onto Gitee (`gh pr diff` /
`git format-patch` → apply on Gitee → green tests → next Sync export).
Commit SHAs are **not** shared between the two remotes.

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
