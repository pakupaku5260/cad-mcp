"""View toolset: standard view orientation and screenshot."""

from __future__ import annotations

from cadmcp.backend.protocol.constants import STANDARD_VIEWS
from cadmcp.kernel import OpContext
from cadmcp.registry import ToolSpec, make_schema
from cadmcp.safety import ensure_output_path
from cadmcp.toolsets.core._common import PNG_EXTS


def set_view(ctx: OpContext, view: str) -> dict:
    ctx.backend.set_view(view)
    return {"view": view}


def screenshot(
    ctx: OpContext, path: str = "screenshot.png", view: str = "isometric", overwrite: bool = False
) -> dict:
    resolved = ensure_output_path(path, roots=ctx.workspace, extensions=PNG_EXTS, overwrite=overwrite)
    ctx.backend.screenshot(resolved, view)
    return {"path": str(resolved), "view": view}


SPECS: list[ToolSpec] = [
    ToolSpec(
        name="set_view",
        toolset="view",
        description="Switch the model view to a standard orientation before screenshot.",
        input_schema=make_schema(
            {"view": {"type": "string", "enum": list(STANDARD_VIEWS)}}, ["view"]
        ),
        handler=set_view,
        timeout_class="fast",
    ),
    ToolSpec(
        name="screenshot",
        toolset="view",
        description="Screenshot the active document from a standard view (.png/.jpg).",
        input_schema=make_schema(
            {
                "path": {"type": "string", "description": "Output .png/.jpg."},
                "view": {"type": "string", "enum": list(STANDARD_VIEWS)},
                "overwrite": {"type": "boolean", "description": "Allow overwrite."},
            }
        ),
        handler=screenshot,
    ),
]
