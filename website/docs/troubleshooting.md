---
description: Diagnose a stuck executor, COM attach failures, HTTP 401s, port conflicts, and missing tools — with the exact commands and error codes.
---

# Troubleshooting

Almost everything starts with one command, which prints a JSON report and exits
non-zero when the backend cannot start:

```bash
cadmcp doctor --backend solidworks   # or --backend fake
```

| Symptom | Look at |
|---|---|
| Tools never appear in the client | [Client does not see the tools](#client-does-not-see-the-tools) |
| `COM_ATTACH_FAILED` | [Attach failures](#com_attach_failed) |
| `EXEC_STUCK` / `EXECUTOR_BUSY` | [Stuck executor](#stuck-executor) |
| `401` or connection refused | [HTTP transport](#http-transport) |
| A dialog keeps the session blocked | [Modal dialogs](#modal-dialogs) |

## Read the doctor report

- `ok` — `false` means the backend never became ready; the reason is in
  `backend.error` as `CODE: message`.
- `backend.available` / `backend.revision` — whether the backend attached and
  which revision it reports.
- `executor.state` — `IDLE`, `BUSY`, or `STUCK`; `stuck_reason` names the tool
  that hung.
- `executor.blocker` — `true` when a modal dialog was detected (solidworks
  backend only).

## `COM_ATTACH_FAILED`

The STA thread could not attach to or start SolidWorks. Common causes, in order:

1. **SolidWorks is not running.** Start it, sign in, close the Start screen, then
   run `doctor` again.
2. **`pywin32` is missing.** `pip install pywin32`, then reinstall `pycadmcp` if
   the environment changed.
3. **SolidWorks is still loading.** First start can take longer than the 30 s STA
   readiness window; wait for the full UI, then retry.
4. **License or activation dialog.** A blocking dialog means COM never returns —
   clear it manually (see [Modal dialogs](#modal-dialogs)).
5. **DCOM / permissions.** When the server starts SolidWorks itself, the account
   needs permission to launch it; starting SolidWorks first avoids this path.

## Stuck executor

`EXEC_STUCK` means a tool exceeded its timeout and COM cannot be interrupted.
The executor refuses further calls until the block is cleared — by design it
never kills SolidWorks for you.

1. Switch to SolidWorks and close the dialog on screen (dimension prompt,
   rebuild confirmation, license warning, save prompt).
2. Run `cadmcp doctor --backend solidworks`; `executor.state` should return to
   `IDLE`.
3. Retry the call. In chat, the `cadmcp://skill/solidworks-recovery` skill walks
   through the same steps.

`EXECUTOR_BUSY` is different: a mutating call is in flight, and mutating calls
are never queued. Wait for `elapsed_s` to finish; read-only tools still work. If
it never clears, treat it as stuck.

## HTTP transport

```bash
cadmcp serve --transport http --backend solidworks
curl http://127.0.0.1:8756/health
```

- **`401 Unauthorized`** — the request is missing the bearer token. The token is
  created on first start at `%APPDATA%\cadmcp\token` (Windows) or
  `~/.config/cadmcp/token` (POSIX). Send
  `Authorization: Bearer <token>`.
- **Connection refused** — the server is not listening. Check the port
  (`--port 8757` if 8756 is taken) and that `serve` is still running.
- **Startup exits with `INSECURE_BIND_REJECTED`** — `--allow-insecure` was used
  on a non-loopback host, or the audit log is unwritable. Bind to loopback or
  drop the flag and use the token.
- **`/health` returns `503`** — the executor raised while building the report;
  the payload carries the exception type. Re-run `doctor`.

`GET /health` needs no auth and returns the coarse state. Send the bearer token
to unlock `detail.windows`, the list of detected dialogs.

## Client does not see the tools

1. Fully restart the client — most hosts read MCP config only at startup.
2. `cadmcp install --client <name> --dry-run` prints the exact path and whether
   the `solidworks` entry would change. Compare it with the table in
   [Getting started](getting-started.md#connect-an-mcp-client-stdio).
3. Check that the server starts by hand:
   `cadmcp serve --transport stdio --backend solidworks` should wait silently.
   On stdio, stdout carries protocol frames only; a wrapper script that prints to
   stdout will break the session.

## Modal dialogs

Any modal dialog in SolidWorks blocks the STA thread. Typical offenders: license
expiry, "rebuild now?", missing references, and file-save prompts. Clear them in
the UI — `doctor` cannot click buttons for you, it only reports `blocker: true`.

## Logs

- Server logs go to **stderr**; stdout is reserved for MCP frames on stdio.
- Audit events (`serve_start`, `serve_stop`) are appended to
  `%APPDATA%\cadmcp\audit.jsonl` or `~/.config/cadmcp/audit.jsonl`. Override with
  `--audit-log <path>`.
