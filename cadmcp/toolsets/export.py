"""Export domain: STEP/STL (part or assembly) and PDF/DXF (drawing).

Format follows the file extension; one tool covers all exports.
EXP3: optional step_ap (203/214) and stl_quality (coarse/fine).
"""
from __future__ import annotations

from pathlib import Path

from cadmcp.backend.export_formats import format_for_path, validate_export_options
from cadmcp.kernel import OpContext
from cadmcp.registry import ToolSpec, make_schema
from cadmcp.safety import ensure_output_path


def export_document(
    ctx: OpContext,
    path: str,
    overwrite: bool = False,
    step_ap: int | None = None,
    stl_quality: str | None = None,
) -> dict:
    fmt = format_for_path(path)
    validate_export_options(fmt, step_ap=step_ap, stl_quality=stl_quality)
    suffix = Path(path).suffix.lower()
    resolved = ensure_output_path(
        path, roots=ctx.workspace, extensions={suffix}, overwrite=overwrite
    )
    quality = None if stl_quality is None else str(stl_quality).strip().lower()
    ctx.backend.export_document(
        resolved, fmt, step_ap=step_ap, stl_quality=quality
    )
    out: dict = {"saved": True, "path": str(resolved)}
    if step_ap is not None:
        out["step_ap"] = int(step_ap)
    if quality is not None:
        out["stl_quality"] = quality
    return out


EXPORT_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="export",
        toolset="export",
        description=(
            "Export the active document; format follows the extension. "
            ".step/.stp/.stl export a part or assembly; .pdf/.dxf export a drawing. "
            "Optional step_ap=203|214 for STEP; stl_quality=coarse|fine for STL."
        ),
        input_schema=make_schema(
            {
                "path": {"type": "string", "description": "Output path relative to workspace."},
                "overwrite": {"type": "boolean", "default": False},
                "step_ap": {
                    "type": "integer",
                    "enum": [203, 214],
                    "description": "STEP application protocol; only for .step/.stp.",
                },
                "stl_quality": {
                    "type": "string",
                    "enum": ["coarse", "fine"],
                    "description": "STL tessellation quality; only for .stl.",
                },
            },
            ["path"],
        ),
        handler=export_document,
        mutating=True,
        timeout_class="slow",
    ),
]
