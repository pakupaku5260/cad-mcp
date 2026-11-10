"""MCP server wiring (v4 §9/§17 W4-11): registry → tools/list, kernel+executor → tools/call.

Boundaries (§5: server registers and dispatches only):
- tools/list exposes ToolRegistry specs—same inputSchema as contract tests; visibility via ToolVisibility;
- tools/call uses executor.run(kernel.dispatch) except bypass_queue (status + toolbox): inline on caller thread;
  health must stay readable when STUCK/busy; executor.health() is short-lock, no COM;
- Domain errors as OpResult JSON in isError=true text (MCP tool errors, not protocol errors);
- /health on same Starlette app, never 500; Bearer tiers detail vs coarse blocker; /health never 401;
- Bearer middleware on MCP when require_auth; --allow-insecure loopback still unlocks /health detail with token.

resources/list + resources/read share content with help(topic); unknown URI → protocol error + catalog;
open_toolbox / close_toolbox → notifications/tools/list_changed.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Collection
from pathlib import Path
from types import SimpleNamespace

from mcp import MCPError, types
from mcp.server.lowlevel import Server
from mcp.server.lowlevel.server import NotificationOptions
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from cadmcp import __version__
from cadmcp.auth import BearerAuthMiddleware, bearer_matches
from cadmcp.backend.protocol.protocol import CADBackend
from cadmcp.errors import fail
from cadmcp.executor import Executor
from cadmcp.kernel import Kernel
from cadmcp.probe import DialogProbe
from cadmcp.registry import ToolRegistry
from cadmcp.resources import iter_resources, known_uris, read_resource
from cadmcp.resources.content import MIME_TYPE
from cadmcp.result import OpResult, fail_result
from cadmcp.toolbox import TOOLBOX_MUTATORS, ToolVisibility
from cadmcp.toolsets.core import core_registry

log = logging.getLogger(__name__)


async def call_through_executor(
    kernel: Kernel,
    executor: Executor,
    registry: ToolRegistry,
    name: str,
    arguments: dict | None,
    *,
    visibility: ToolVisibility | None = None,
) -> OpResult:
    """Sole tools/call path: unknown tool rejected here; bypass_queue inline, else executor.

    status / toolbox are bypass_queue: must answer when STUCK/busy. Closed toolset → TOOLSET_CLOSED.
    """
    spec = registry.get(name)
    if spec is None:
        return fail_result(
            fail("INVALID_ARGUMENT", f"Unknown tool: {name}", "Call tools/list or search_tools", tool=name)
        )
    if visibility is not None and not visibility.is_visible(spec):
        return fail_result(
            fail(
                "TOOLSET_CLOSED",
                f"Tool {name} belongs to closed toolset {spec.toolset!r}",
                f'Call open_toolbox(toolsets=["{spec.toolset}"]), refresh tools/list, retry',
                tool=name,
                toolset=spec.toolset,
            )
        )
    if spec.bypass_queue:
        return kernel.dispatch(name, arguments or {})
    return await executor.run(
        lambda: kernel.dispatch(name, arguments or {}),
        tool=name,
        mutating=spec.mutating,
        timeout_class=spec.timeout_class,  # type: ignore[arg-type]
    )


def _bind_tools_changed_capability(server: Server) -> None:
    """HTTP/stdio: create_initialization_options defaults tools.listChanged on."""
    original = server.create_initialization_options

    def create_initialization_options(
        notification_options: NotificationOptions | None = None,
        experimental_capabilities: dict | None = None,
    ):
        opts = notification_options or NotificationOptions(tools_changed=True)
        if not opts.tools_changed:
            opts = NotificationOptions(
                prompts_changed=opts.prompts_changed,
                resources_changed=opts.resources_changed,
                tools_changed=True,
            )
        return original(
            notification_options=opts,
            experimental_capabilities=experimental_capabilities,
        )

    server.create_initialization_options = create_initialization_options  # type: ignore[method-assign]


def _make_server(
    kernel: Kernel,
    executor: Executor,
    registry: ToolRegistry,
    visibility: ToolVisibility,
) -> Server:
    async def on_list_tools(ctx, params):
        specs = visibility.visible_specs(registry)
        return types.ListToolsResult(
            tools=[
                types.Tool(name=s.name, description=s.description, input_schema=s.input_schema)
                for s in specs
            ]
        )

    async def on_call_tool(ctx, params):
        result = await call_through_executor(
            kernel, executor, registry, params.name, params.arguments, visibility=visibility
        )
        if result.ok and params.name in TOOLBOX_MUTATORS:
            try:
                await ctx.session.send_tool_list_changed()
            except Exception:  # noqa: BLE001 — notification failure must not hide result
                log.warning("tools/list_changed send failed (client may not support)", exc_info=True)
        return types.CallToolResult(
            is_error=not result.ok,
            content=[types.TextContent(type="text", text=result.model_dump_json())],
        )

    async def on_list_resources(ctx, params):
        return types.ListResourcesResult(
            resources=[
                types.Resource(uri=uri, name=name, description=description, mime_type=MIME_TYPE)
                for uri, name, description in iter_resources()
            ]
        )

    async def on_read_resource(ctx, params):
        uri = str(params.uri)
        try:
            text = read_resource(uri)
        except KeyError:
            raise MCPError(
                -32602,
                f"Unknown resource URI: {uri}",
                {"available": sorted(known_uris())},
            ) from None
        return types.ReadResourceResult(
            contents=[types.TextResourceContents(uri=uri, mime_type=MIME_TYPE, text=text)]
        )

    server = Server(
        "cadmcp",
        version=__version__,
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
        on_list_resources=on_list_resources,
        on_read_resource=on_read_resource,
    )
    _bind_tools_changed_capability(server)
    return server


def _health_route(executor: Executor, token: str | None = None) -> Route:
    async def health(request: Request) -> JSONResponse:
        try:
            detail = bearer_matches(request.headers.get("authorization"), token)
            h = executor.health(detail=detail)
            payload = {
                "ok": h.state != "STUCK" and h.thread_alive,
                "state": h.state,
                "tool": h.tool,
                "elapsed_s": h.elapsed_s,
                "queue_depth": h.queue_depth,
                "thread_alive": h.thread_alive,
                "backend_ready": h.backend_ready,
                "stuck_reason": h.stuck_reason,
                "late_results": h.late_results,
                "jobs_total": h.jobs_total,
                "blocker": h.blocker,
            }
            if detail:
                payload["detail"] = {
                    "windows": [w.model_dump() for w in (h.windows or [])],
                    "detector_error": h.detector_error,
                }
            return JSONResponse(payload)
        except Exception as exc:  # noqa: BLE001 — /health never 500
            log.exception("/health internal error")
            return JSONResponse(
                {"ok": False, "state": "UNKNOWN", "error": f"{type(exc).__name__}: {exc}"},
                status_code=503,
            )

    return Route("/health", health)


def build_stack(
    *,
    workspace: Path,
    backend_factory: Callable[[], CADBackend],
    allow_remote: bool = False,
    probe: DialogProbe | None = None,
    auth_token: str | None = None,
    require_auth: bool = True,
    transport: str = "http",
    toolsets: Collection[str] | None = None,
) -> SimpleNamespace:
    """Wire registry + executor + kernel + MCP server + ASGI app (cli and tests).

    toolsets: initial visibility (None = all open). Registry always full; toolbox only toggles visibility.
    executor.start() blocks until backend init (failure → CadMcpError, use doctor).
    probe: dialog probe for W8; None → blocker null on /health.
    auth_token: /health tiers; require_auth adds 401 on MCP.
    transport: status detail tier—stdio trusted; http needs auth+token per request for window detail.
    """
    registry = core_registry()
    visibility = ToolVisibility(None if toolsets is None else toolsets)
    executor = Executor(backend_factory, probe=probe)
    executor.start()
    status_detail = transport == "stdio" or (require_auth and auth_token is not None)
    kernel = Kernel(
        registry,
        executor.backend(),
        workspace=workspace,
        health_provider=lambda: executor.health(detail=status_detail),
        visibility=visibility,
    )
    server = _make_server(kernel, executor, registry, visibility)
    security = (
        TransportSecuritySettings(enable_dns_rebinding_protection=False) if allow_remote else None
    )
    app = server.streamable_http_app(
        json_response=True,
        custom_starlette_routes=[_health_route(executor, token=auth_token)],
        transport_security=security,
    )
    if auth_token and require_auth:
        app.add_middleware(BearerAuthMiddleware, token=auth_token)
    return SimpleNamespace(
        server=server,
        app=app,
        executor=executor,
        kernel=kernel,
        registry=registry,
        visibility=visibility,
        security=security,
        auth_token=auth_token,
        require_auth=require_auth,
    )
