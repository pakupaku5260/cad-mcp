"""Core toolset · help, status, recipe replay, and toolbox visibility.

screenshot moved to the view toolset (core budget).
"""

from __future__ import annotations

from cadmcp.errors import fail
from cadmcp.kernel import OpContext
from cadmcp.recipe import load_recipe, replay_recipe
from cadmcp.registry import ToolSpec, make_schema
from cadmcp.resources import known_topics, topic_entry
from cadmcp.safety import ensure_input_path

_RECIPE_EXTS = {".json"}


def help_topic(ctx: OpContext, topic: str) -> dict:
    """§8 boundary rules tool entry; same content source as MCP resources (resources.content)."""
    entry = topic_entry(topic)
    if entry is None:
        raise fail(
            "INVALID_ARGUMENT",
            f"Unknown topic: {topic}",
            f"Available topics: {', '.join(known_topics())}",
            topic=topic,
        )
    uri, text = entry
    return {"topic": topic, "uri": uri, "text": text}


def status(ctx: OpContext) -> dict:
    """Health snapshot tool facade (§11.2 item 3 + §16.5 stdio status query tool).

    Detail level is bound at build_stack wiring; coarse view matches /health — no windows/detector_error.
    """
    if ctx.health is None:
        raise fail(
            "INTERNAL_ERROR",
            "Health channel not wired (ctx.health is None)",
            "Incomplete server startup; server defect — check server logs",
            tool="status",
        )
    data = ctx.health().model_dump()
    if data.get("windows") is None:
        data.pop("windows", None)
        data.pop("detector_error", None)
    return {"health": data}


def replay_recipe_tool(ctx: OpContext, path: str) -> dict:
    """Replay a JSON recipe (wave 7 RECIPE). Inner steps use ctx.dispatch on the same kernel."""
    if ctx.dispatch is None:
        raise fail(
            "INTERNAL_ERROR",
            "Recipe replay dispatch not wired",
            "Server defect; start with a Kernel.dispatch wiring path",
            tool="replay_recipe",
        )
    resolved = ensure_input_path(path, roots=ctx.workspace, extensions=_RECIPE_EXTS)
    recipe = load_recipe(resolved)
    # Light Kernel shell for replay_recipe(kernel, ...); real dispatch via ctx.dispatch
    class _Proxy:
        def dispatch(self, name: str, args: dict | None = None):
            return ctx.dispatch(name, args)

    report = replay_recipe(_Proxy(), recipe)  # type: ignore[arg-type]
    report["path"] = str(resolved)
    return report


def _require_visibility(ctx: OpContext, tool: str):
    if ctx.visibility is None or ctx.registry is None:
        raise fail(
            "INTERNAL_ERROR",
            f"{tool} ToolVisibility not wired",
            "Incomplete server startup; use build_stack",
            tool=tool,
        )
    return ctx.visibility, ctx.registry


def list_toolboxes(ctx: OpContext) -> dict:
    visibility, registry = _require_visibility(ctx, "list_toolboxes")
    return visibility.list_toolboxes(registry)


def open_toolbox(ctx: OpContext, toolsets: list[str]) -> dict:
    visibility, _registry = _require_visibility(ctx, "open_toolbox")
    return visibility.open(toolsets)


def close_toolbox(ctx: OpContext, toolsets: list[str]) -> dict:
    visibility, _registry = _require_visibility(ctx, "close_toolbox")
    return visibility.close(toolsets)


def search_tools(ctx: OpContext, query: str, limit: int = 20) -> dict:
    visibility, registry = _require_visibility(ctx, "search_tools")
    return visibility.search_tools(registry, query, limit=limit)


SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="help",
        description="Long-form help for one topic; call it instead of guessing.",
        input_schema=make_schema(
            {"topic": {"type": "string",
                       "description": "selectors | workflow | units | errors | limits"}},
            ["topic"],
        ),
        handler=help_topic,
    ),
    ToolSpec(
        name="status",
        description="Executor health: state, stuck reason, queue depth, modal blocker.",
        input_schema=make_schema({}),
        handler=status,
        timeout_class="fast",
        bypass_queue=True,  # Inline: no queue — readable while STUCK/busy (server docstring)
    ),
    ToolSpec(
        name="replay_recipe",
        description=(
            "Replay a JSON design recipe (ordered tool calls + per-step asserts). "
            "Only registered tool names; no branches/loops."
        ),
        input_schema=make_schema(
            {"path": {"type": "string", "description": "Workspace-relative .json recipe."}},
            ["path"],
        ),
        handler=replay_recipe_tool,
        timeout_class="slow",
    ),
    ToolSpec(
        name="list_toolboxes",
        description="List toolsets with open state and tool names. Use before open_toolbox.",
        input_schema=make_schema({}),
        handler=list_toolboxes,
        timeout_class="fast",
        bypass_queue=True,
    ),
    ToolSpec(
        name="open_toolbox",
        description="Open toolset(s) so their real tools appear in tools/list.",
        input_schema=make_schema(
            {
                "toolsets": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Toolset names from list_toolboxes.",
                }
            },
            ["toolsets"],
        ),
        handler=open_toolbox,
        timeout_class="fast",
        bypass_queue=True,
    ),
    ToolSpec(
        name="close_toolbox",
        description="Close toolset(s) to shrink tools/list. Cannot close core.",
        input_schema=make_schema(
            {
                "toolsets": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Toolset names to close (not core).",
                }
            },
            ["toolsets"],
        ),
        handler=close_toolbox,
        timeout_class="fast",
        bypass_queue=True,
    ),
    ToolSpec(
        name="search_tools",
        description="Find tools by name/description substring; shows owning toolset and open state.",
        input_schema=make_schema(
            {
                "query": {"type": "string", "description": "Substring, e.g. flange or mate."},
                "limit": {"type": "integer", "description": "Max hits (1–50, default 20)."},
            },
            ["query"],
        ),
        handler=search_tools,
        timeout_class="fast",
        bypass_queue=True,
    ),
)
