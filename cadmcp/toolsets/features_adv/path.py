"""features_adv · helix, sweep, and loft.

Split from toolsets/features_adv.py by domain; handlers and ToolSpec unchanged.
"""

from __future__ import annotations

import math

from cadmcp.errors import fail
from cadmcp.kernel import OpContext
from cadmcp.registry import ToolSpec, make_schema

from ._common import _UNIT_DESC, _UNIT_ENUM, _unit_ctx


def create_helix(
    ctx: OpContext,
    pitch: float,
    revolutions: float = 1.0,
    height: float | None = None,
    start_angle_deg: float = 0.0,
    clockwise: bool = False,
    unit: str = "mm",
) -> dict:
    # Validate at tool layer so invalid args are not masked by backend NOT_IMPLEMENTED (phase B)
    if pitch <= 0:
        raise fail("INVALID_ARGUMENT", "Pitch must be positive", "Pass pitch > 0")
    if height is None and revolutions <= 0:
        raise fail("INVALID_ARGUMENT", "Revolutions must be positive", "Pass revolutions > 0, or pass height")
    if height is not None and height <= 0:
        raise fail("INVALID_ARGUMENT", "Helix height must be positive", "Pass height > 0")
    uc = _unit_ctx(ctx, unit)
    h = uc.to_m(height) if height is not None else None
    info = ctx.backend.create_helix(
        uc.to_m(pitch), revolutions, h, math.radians(start_angle_deg), clockwise
    )
    return {"name": info.name, "unit": uc.external_unit}


def sweep(ctx: OpContext, profile_sketch: str | None = None, path_sketch: str | None = None) -> dict:
    feat = ctx.backend.sweep(profile_sketch, path_sketch)
    return {"name": feat.name, "kind": feat.kind}


def sweep_cut(
    ctx: OpContext, profile_sketch: str | None = None, path_sketch: str | None = None
) -> dict:
    feat = ctx.backend.sweep_cut(profile_sketch, path_sketch)
    return {"name": feat.name, "kind": feat.kind}


def loft(
    ctx: OpContext,
    profiles: list[str] | None = None,
    guides: list[str] | None = None,
    centerline: str | None = None,
) -> dict:
    feat = ctx.backend.loft(profiles, guides=guides, centerline=centerline)
    out = {"name": feat.name, "kind": feat.kind}
    if guides:
        out["guides"] = list(guides)
    if centerline:
        out["centerline"] = centerline
    return out


def loft_cut(
    ctx: OpContext,
    profiles: list[str] | None = None,
    guides: list[str] | None = None,
    centerline: str | None = None,
) -> dict:
    feat = ctx.backend.loft_cut(profiles, guides=guides, centerline=centerline)
    out = {"name": feat.name, "kind": feat.kind}
    if guides:
        out["guides"] = list(guides)
    if centerline:
        out["centerline"] = centerline
    return out


SPECS: list[ToolSpec] = [
    ToolSpec(
        name="create_helix",
        toolset="features_adv",
        description=(
            "Create a helix/spiral from the last ended circular sketch "
            "(start_sketch → sketch_circle → end_sketch → create_helix). "
            "Omit height to define by pitch+revolutions; set height to define by height+pitch."
        ),
        input_schema=make_schema(
            {
                "pitch": {"type": "number", "description": "Pitch > 0."},
                "revolutions": {"type": "number", "default": 1.0},
                "height": {"type": "number", "description": "If set, define by height+pitch."},
                "start_angle_deg": {"type": "number", "default": 0.0},
                "clockwise": {"type": "boolean", "default": False},
                "unit": {"type": "string", "enum": _UNIT_ENUM, "description": _UNIT_DESC},
            },
            ["pitch"],
        ),
        handler=create_helix,
        mutating=True,
        verify_delta=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="sweep",
        toolset="features_adv",
        description=(
            "Swept boss from two sketches (path first, then profile). Path may be a single "
            "line, a connected chain of lines/arcs in one ended sketch, or a helix name. "
            "Omit names to use the last two ended sketches."
        ),
        input_schema=make_schema(
            {
                "profile_sketch": {"type": "string", "description": "Optional profile sketch name."},
                "path_sketch": {"type": "string", "description": "Optional path sketch or helix name."},
            }
        ),
        handler=sweep,
        mutating=True,
        verify_delta=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="sweep_cut",
        toolset="features_adv",
        description=(
            "Swept cut from two sketches (path first, then profile). Path may be a line, a "
            "connected chain of lines/arcs, or a helix. Omit names to use the last two ended sketches."
        ),
        input_schema=make_schema(
            {
                "profile_sketch": {"type": "string", "description": "Optional profile sketch name."},
                "path_sketch": {"type": "string", "description": "Optional path sketch or helix name."},
            }
        ),
        handler=sweep_cut,
        mutating=True,
        verify_delta=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="loft",
        toolset="features_adv",
        description=(
            "Solid loft through ended sketches. Optional guides, or one open centerline; "
            "do not combine them."
        ),
        input_schema=make_schema(
            {
                "profiles": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Ended sketch names; omit for the last two.",
                },
                "guides": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Open-curve sketches that pierce every profile.",
                },
                "centerline": {
                    "type": "string",
                    "description": "One open-curve sketch. Segments are selected; not with guides.",
                },
            }
        ),
        handler=loft,
        mutating=True,
        verify_delta=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="loft_cut",
        toolset="features_adv",
        description="Lofted cut. Needs a solid. Optional guides or one open centerline.",
        input_schema=make_schema(
            {
                "profiles": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Ended sketch names; omit for the last two.",
                },
                "guides": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Open-curve sketches that pierce every profile.",
                },
                "centerline": {
                    "type": "string",
                    "description": "One open-curve sketch. Segments are selected; not with guides.",
                },
            }
        ),
        handler=loft_cut,
        mutating=True,
        verify_delta=True,
        timeout_class="slow",
    ),
]
