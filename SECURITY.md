# Security Policy

## Supported versions

Security fixes are applied to the latest commit on the default branch of the
public repository. There is no long-term support branch yet.

## Reporting a vulnerability

Please email **shiyang19822000@gmail.com** with:

- a description of the issue
- steps to reproduce
- impact assessment if known

Do **not** open a public GitHub issue for security reports.

You should receive an acknowledgement within a few days. Please allow time for
investigation before any disclosure.

## Scope notes

- `cadmcp` can drive SolidWorks via COM and write files under a configured
  workspace. Treat the MCP server as a privileged local automation agent.
- Prefer `stdio` transport or loopback HTTP with a token. Avoid binding to
  non-loopback addresses without a reverse proxy and authentication.
- Real SolidWorks integration tests (`-m sw` with `CADMCP_REAL_SW=1`) close
  open documents without saving. Run them only on disposable sessions.
