"""CLI: cadmcp serve / cadmcp doctor (v4 §11/§17 W4-13).

serve:
- Transport (v4 §16.5 follow-up): `--transport http|stdio` (default http). stdio = subprocess
  channel spawned by the client, no network listen; `--allow-insecure` does not apply on stdio
  (exit code 2). stdout carries protocol frames only; runtime output goes to stderr.
- Auth (v4 §11.2 items 2–3, ahead of smoke gate): HTTP defaults to token auth — first start
  auto-generates `token` under user config (POSIX 600), client sends `Authorization: Bearer`;
  unwritable token refuses startup. `--allow-insecure` only on loopback bind (non-loopback +
  flag = refuse startup, INSECURE_BIND_REJECTED exit 2); stdio has no network/token surface.
- Audit (v4 §11/§11.2): on start, wires to user config `audit.jsonl` (`--audit-log` override);
  unauthenticated bind (--allow-insecure) must audit and **refuses start if audit is unwritable**
  (fail-closed); serve_start/serve_stop include `transport` and `auth`; write failure degrades to
  stderr warning.
- `--backend fake|solidworks`: fake runs everywhere (dev/CI); solidworks is the real backend (W3-10 document domain).

doctor:
- Prints health JSON (Python/platform/backend availability & revision/executor/tools surface),
  never raises stack; exit 0=healthy, 1=unhealthy. Real-machine template path probe with the solidworks backend.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import platform
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from cadmcp import __version__
from cadmcp.auth import TOKEN_FILENAME, load_or_create_token
from cadmcp.backend.protocol.protocol import CADBackend
from cadmcp.errors import CadMcpError, SideEffect, fail
from cadmcp.executor import Executor
from cadmcp.probe import DialogProbe
from cadmcp.registry import TOOLSET_PROFILES, resolve_toolsets
from cadmcp.safety import audit, default_output_root, set_audit_path
from cadmcp.server import build_stack
from cadmcp.toolsets.core import core_registry

DEFAULT_PORT = 8756


def _is_loopback(host: str) -> bool:
    if host in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _user_config_dir() -> Path:
    """User config dir (v4 §11: audit here, not cwd): Windows=%APPDATA%, else ~/.config."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "cadmcp"


def _default_audit_path() -> Path:
    return _user_config_dir() / "audit.jsonl"


def _audit(event: str, **fields: object) -> OSError | None:
    """Write audit; returns OSError on failure for caller strictness, does not raise."""
    try:
        audit(event, **fields)
    except OSError as exc:
        return exc
    return None


def _probe_for(kind: str) -> DialogProbe | None:
    """Window probe wiring (W8 row1/row3): solidworks uses real probe; fake does not fabricate
    windows (tests inject FakeDialogProbe). Probe is COM-independent; import failure → None."""
    if kind != "solidworks":
        return None
    try:
        from cadmcp.backend.solidworks.probe import Win32DialogProbe
    except ImportError:
        return None
    return Win32DialogProbe()


def _make_factory(kind: str) -> Callable[[], CADBackend]:
    if kind == "fake":
        from cadmcp.backend.fake.backend import FakeBackend

        return FakeBackend
    if kind == "solidworks":

        def factory() -> CADBackend:
            try:
                from cadmcp.backend.solidworks.backend import ComBackend
            except (ImportError, AttributeError) as exc:
                raise fail(
                    "NOT_IMPLEMENTED",
                    f"solidworks backend unavailable (requires Windows + pywin32): {exc}",
                    "Install pywin32 on Windows and start SolidWorks; use --backend fake for dev/CI",
                    side_effect=SideEffect.NONE,
                ) from exc
            return ComBackend.attach()

        return factory
    raise ValueError(f"Unknown backend: {kind}")


def cmd_serve(args: argparse.Namespace) -> int:
    set_audit_path(args.audit_log or _default_audit_path())
    try:
        return _serve(args)
    finally:
        set_audit_path(None)  # reset process state (main may be called repeatedly, e.g. tests)


def _serve(args: argparse.Namespace) -> int:
    if args.transport == "stdio" and args.allow_insecure:
        print(
            "stdio transport does not use the network; --allow-insecure does not apply — "
            "remove that flag and retry "
            "(non-loopback bind gate applies only to --transport http, v4 §11.2)",
            file=sys.stderr,
        )
        return 2

    insecure_bind = not _is_loopback(args.host)
    if insecure_bind and args.allow_insecure:
        # v4 §11.2 item 2 (after token): --allow-insecure only on loopback — non-loopback needs token
        err = _audit(
            "insecure_bind_rejected", host=args.host, port=args.port, transport=args.transport
        )
        if err is not None:
            print(f"Warning: failed to write rejection event to audit log: {err}", file=sys.stderr)
        print(
            f"INSECURE_BIND_REJECTED: --allow-insecure is only for loopback bind; "
            f"non-loopback {args.host!r} requires token auth — remove the flag to start (v4 §11.2 item 2)",
            file=sys.stderr,
        )
        return 2

    workspace = Path(args.workspace) if args.workspace else default_output_root()
    workspace.mkdir(parents=True, exist_ok=True)

    try:
        toolsets = resolve_toolsets(
            args.toolsets.split(",") if args.toolsets else None,
            profile=args.profile,
        )
    except ValueError as exc:
        print(f"TOOLSETS_INVALID: {exc}", file=sys.stderr)
        return 2

    use_auth = args.transport == "http"
    token: str | None = None
    if use_auth:
        token_path = _user_config_dir() / TOKEN_FILENAME
        if args.allow_insecure:
            err = _audit("insecure_bind", host=args.host, port=args.port, backend=args.backend)
            if err is not None:
                # v4 §11.2: unauthenticated bind must be auditable — refuse start if not writable
                print(
                    f"INSECURE_BIND_REJECTED: audit log not writable ({err}) — "
                    f"unauthenticated bind must audit per §11.2; set --audit-log to a writable path",
                    file=sys.stderr,
                )
                return 2
            print(
                f"Warning: --allow-insecure binding {args.host!r}:{args.port} without auth — "
                "any local process can call all tools (v4 §11.2, audit written; "
                "remove the flag to enable token auth)",
                file=sys.stderr,
            )
            try:
                token = load_or_create_token(token_path)  # still try: valid token unlocks /health detail
            except OSError as exc:
                print(
                    f"Warning: token file unavailable ({exc}) — continuing without auth; "
                    "/health detail locked",
                    file=sys.stderr,
                )
        else:
            try:
                token = load_or_create_token(token_path)
            except OSError as exc:
                print(
                    f"INSECURE_BIND_REJECTED: token file unavailable ({exc}) — HTTP serve requires a token "
                    f"(v4 §11.2 item 3); check config dir permissions, or use --allow-insecure for dev (loopback only)",
                    file=sys.stderr,
                )
                return 2
            if insecure_bind:
                print(
                    f"Warning: bound to non-loopback {args.host!r}:{args.port}; token auth enabled — "
                    f"token file: {token_path} (client sends Authorization: Bearer <token>; "
                    "plaintext on wire — put a reverse proxy in front for production, v4 §11.2 item 5)",
                    file=sys.stderr,
                )

    try:
        stack = build_stack(
            workspace=workspace,
            backend_factory=_make_factory(args.backend),
            allow_remote=not _is_loopback(args.host),
            probe=_probe_for(args.backend),
            auth_token=token,
            require_auth=use_auth and not args.allow_insecure,
            transport=args.transport,
            toolsets=toolsets,
        )
    except CadMcpError as exc:
        print(f"{exc.code}: {exc.message}\nhint: {exc.hint}", file=sys.stderr)
        return 1

    err = _audit(
        "serve_start",
        host=args.host,
        port=args.port,
        backend=args.backend,
        workspace=str(workspace),
        transport=args.transport,
        auth=use_auth and not args.allow_insecure,
    )
    if err is not None:
        print(f"Warning: failed to write serve_start to audit log: {err}", file=sys.stderr)

    try:
        if args.transport == "stdio":
            _run_stdio(stack.server)
        else:
            import uvicorn  # noqa: PLC0415 — only serve needs it; doctor avoids import cost

            uvicorn.run(stack.app, host=args.host, port=args.port, log_level="info")
    finally:
        _audit("serve_stop")
        stack.executor.shutdown()
    return 0


def _run_stdio(server) -> None:
    """stdio transport (v4 §16.5 follow-up): stdin/stdout carry JSON-RPC; client closes pipe to exit.

    stdout is protocol-only: runtime logs go to stderr (Python logging default); after serve starts
    the service must not print — anything on stdout corrupts the protocol stream.
    """
    import asyncio

    from mcp.server.stdio import stdio_server  # noqa: PLC0415 — lazy import by transport

    async def _serve() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(_serve())


def cmd_doctor(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace) if args.workspace else default_output_root()
    registry = core_registry()
    report: dict = {
        "ok": False,
        "cadmcp_version": __version__,
        "python": platform.python_version(),
        "platform": f"{platform.system()}-{platform.machine()}",
        "workspace": str(workspace),
        "backend": {"kind": args.backend, "available": False, "revision": None, "error": None},
        "executor": None,
        "registry": {
            "tools": len(registry),
            "toolsets": {t: len(registry.by_toolset(t)) for t in sorted({s.toolset for s in registry})},
        },
        "notes": [
            "solidworks backend covers document/sketch/feature/query/assembly/drawing/sheet metal; see docs/TOOL_INVENTORY.md",
            "Tool surface: preload with --profile / --toolsets; adjust per session with open_toolbox / close_toolbox",
        ],
    }

    executor = Executor(_make_factory(args.backend), probe=_probe_for(args.backend))
    try:
        executor.start(wait_s=15)
        backend = executor.backend()
        report["backend"] = {
            "kind": args.backend,
            "available": True,
            "revision": backend.revision(),
            "error": None,
        }
        # detail=True: doctor is local; include window list and blockers (W8 real-machine smoke entry)
        report["executor"] = executor.health(detail=True).model_dump()
        report["ok"] = True
    except CadMcpError as exc:
        report["backend"]["error"] = f"{exc.code}: {exc.message}"
    except Exception as exc:  # noqa: BLE001 — doctor never raises stack
        report["backend"]["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        executor.shutdown()

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def cmd_install(args: argparse.Namespace) -> int:
    from cadmcp.install_client import install_client, write_mcpb_manifest

    try:
        report = install_client(args.client, dry_run=bool(args.dry_run))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    # Write MCPB manifest at repo root (idempotent on repeat)
    repo = Path(__file__).resolve().parents[1]
    if (repo / "pyproject.toml").is_file() and not args.dry_run:
        manifest = write_mcpb_manifest(repo)
        report["mcpb_manifest"] = str(manifest)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cadmcp", description="CAD MCP server")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Start MCP server (--transport http|stdio, default http)")
    serve.add_argument("--transport", choices=["http", "stdio"], default="http",
                       help="http=Streamable HTTP listener; stdio=client-spawned subprocess channel (v4 §16.5)")
    serve.add_argument("--host", default="127.0.0.1", help="Loopback by default; non-loopback needs --allow-insecure")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.add_argument("--backend", choices=["fake", "solidworks"], default="fake")
    serve.add_argument("--workspace", default=None, help="Sandbox workspace root (default under user home)")
    serve.add_argument("--allow-insecure", action="store_true",
                       help="No-auth mode (loopback only, --transport http); "
                            "non-loopback + this flag = refused startup (v4 §11.2 item 2)")
    serve.add_argument("--audit-log", default=None,
                       help="Audit log path (default user config audit.jsonl, v4 §11)")
    serve.add_argument(
        "--profile",
        choices=sorted(TOOLSET_PROFILES),
        default="part",
        help="Tool surface profile: part / assembly / drawing / sheetmetal / full "
             "(default part; sets initial visible toolsets; open_toolbox per session; "
             "use --profile full for all tools)",
    )
    serve.add_argument(
        "--toolsets",
        default=None,
        help="Comma-separated toolsets overriding --profile, e.g. core,assembly,selection",
    )
    serve.set_defaults(func=cmd_serve)

    doctor = sub.add_parser("doctor", help="Print health JSON (version, backend, executor)")
    doctor.add_argument("--backend", choices=["fake", "solidworks"], default="solidworks")
    doctor.add_argument("--workspace", default=None)
    doctor.set_defaults(func=cmd_doctor)

    install = sub.add_parser(
        "install",
        help="Write cadmcp into client MCP config (claude|vscode|opencode|cursor; idempotent)",
    )
    install.add_argument(
        "--client",
        choices=["claude", "vscode", "opencode", "cursor"],
        required=True,
        help="Target client",
    )
    install.add_argument(
        "--dry-run",
        action="store_true",
        help="Print paths and whether they would change, without writing",
    )
    install.set_defaults(func=cmd_install)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
