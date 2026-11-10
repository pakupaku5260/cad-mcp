"""Protocol layer · parameter and business-rule validation."""
from __future__ import annotations

import re
from collections.abc import Sequence

from cadmcp.errors import fail

from .constants import (
    EXTRUDE_DIRECTIONS,
    PLANE_MODES,
    THIN_BLOCKED_DIRECTIONS,
    THIN_TYPES,
)


def validate_create_plane(
    mode: str,
    reference: str | None,
    offset_given: bool,
    angle_rad: float | None,
    axis: str | None,
    points_m: Sequence[tuple[float, float, float]] | None,
) -> None:
    if mode not in PLANE_MODES:
        raise fail(
            "INVALID_ARGUMENT",
            f"Unknown reference-plane mode: {mode!r}",
            f"mode: {', '.join(PLANE_MODES)}",
            requested=mode,
        )
    if mode == "offset":
        if not reference:
            raise fail("INVALID_ARGUMENT", "Offset plane requires reference", "Pass a plane name from list_planes")
        if not offset_given:
            raise fail("INVALID_ARGUMENT", "Offset plane requires offset", "Pass offset (may be 0)")
        return
    if mode == "angle":
        if not reference:
            raise fail("INVALID_ARGUMENT", "Angled plane requires reference", "Pass the plane to rotate")
        if axis is None or not str(axis).strip():
            raise fail("INVALID_ARGUMENT", "Angled plane requires axis", "Call create_axis first, or pass +x/+y/+z")
        if angle_rad is None:
            raise fail("INVALID_ARGUMENT", "Angled plane requires angle_deg", "Pass angle relative to the reference plane")
        return
    if points_m is None or len(points_m) != 3:
        raise fail("INVALID_ARGUMENT", "Three-point plane needs exactly three points", "Pass points=[[x,y,z],[x,y,z],[x,y,z]]")


def validate_extrude_options(
    direction: str,
    depth2_m: float | None,
    end_face: int | None = None,
    end_vertex: int | None = None,
    end_body: int | None = None,
) -> None:
    if direction not in EXTRUDE_DIRECTIONS:
        raise fail(
            "INVALID_ARGUMENT",
            f"Unknown extrude direction: {direction!r}",
            f"direction: {', '.join(EXTRUDE_DIRECTIONS)}",
            requested=direction,
        )
    if direction == "both":
        if depth2_m is None or depth2_m <= 0:
            raise fail(
                "INVALID_ARGUMENT",
                "Two-sided extrude requires second depth depth2 > 0",
                "Pass direction=both with depth2 > 0",
            )
    elif depth2_m is not None:
        raise fail(
            "INVALID_ARGUMENT",
            "depth2 is only for direction=both",
            "Remove depth2, or use direction=both",
        )
    if direction == "up_to_surface":
        if end_face is None:
            raise fail(
                "INVALID_ARGUMENT",
                "Up-to-surface extrude requires end_face",
                "Call get_faces first, then pass the terminating face index",
            )
    elif end_face is not None:
        raise fail(
            "INVALID_ARGUMENT",
            "end_face is only for direction=up_to_surface",
            "Remove end_face, or use direction=up_to_surface",
        )
    if direction == "up_to_vertex":
        if end_vertex is None:
            raise fail(
                "INVALID_ARGUMENT",
                "Up-to-vertex extrude requires end_vertex",
                "Call get_vertices first, then pass the terminating vertex index",
            )
    elif end_vertex is not None:
        raise fail(
            "INVALID_ARGUMENT",
            "end_vertex is only for direction=up_to_vertex",
            "Remove end_vertex, or use direction=up_to_vertex",
        )
    if direction == "up_to_body":
        if end_body is None:
            raise fail(
                "INVALID_ARGUMENT",
                "Up-to-body extrude requires end_body",
                "Pass terminating body index (0 for a single-body part); implemented as up-to-face internally",
            )
    elif end_body is not None:
        raise fail(
            "INVALID_ARGUMENT",
            "end_body is only for direction=up_to_body",
            "Remove end_body, or use direction=up_to_body",
        )


def validate_thin_options(
    thin: bool,
    thickness_m: float | None,
    thin_type: str,
    direction: str,
) -> None:
    if not thin:
        if thickness_m is not None:
            raise fail(
                "INVALID_ARGUMENT",
                "thickness is only for thin=true",
                "Remove thickness, or pass thin=true",
            )
        return
    if thickness_m is None or thickness_m <= 0:
        raise fail(
            "INVALID_ARGUMENT",
            "Thin wall requires thickness > 0",
            "Pass thin=true with thickness > 0",
        )
    if thin_type not in THIN_TYPES:
        raise fail(
            "INVALID_ARGUMENT",
            f"Unknown thin-wall type: {thin_type!r}",
            f"thin_type: {', '.join(THIN_TYPES)}",
            requested=thin_type,
        )
    if direction in THIN_BLOCKED_DIRECTIONS:
        raise fail(
            "INVALID_ARGUMENT",
            "Thin wall is not combined with up-to-surface / up-to-next in this phase",
            "Remove thin, or use blind / midplane / both / through_all",
        )


def validate_equation_rhs(expression: str, known: set[str]) -> None:
    """RHS may only use numbers, arithmetic, and known dimension/variable names (quoted allowed). No VBA."""
    raw = str(expression).strip()
    if not raw:
        raise fail("INVALID_ARGUMENT", "Equation RHS cannot be empty", "e.g. 80 or \"D\"")
    if "=" in raw or "'" in raw:
        raise fail("INVALID_ARGUMENT", "Equation RHS contains illegal characters", "Write only the right-hand side: numbers or existing variable names")
    known_l = {k.lower(): k for k in known}

    def _quoted(match: re.Match[str]) -> str:
        inner = match.group(1).strip()
        if inner not in known and inner.lower() not in known_l:
            raise fail(
                "INVALID_ARGUMENT",
                f"Equation references unknown name {inner!r}",
                "Define globals with set_equation first, or use short names from list_dimensions",
                name=inner,
            )
        return " 1 "

    numeric = re.sub(r'"([^"]*)"', _quoted, raw)
    for name in sorted(known, key=len, reverse=True):
        if "@" in name:
            continue
        numeric = re.sub(rf"\b{re.escape(name)}\b", " 1 ", numeric, flags=re.IGNORECASE)
    if re.search(r"[A-Za-z_]", numeric):
        raise fail(
            "INVALID_ARGUMENT",
            "Equation RHS contains illegal identifiers",
            "Only numbers, + - * / ( ) and existing variable/dimension names are allowed",
        )
    if not re.fullmatch(r"[-+*/().0-9\s]+", numeric) or not re.search(r"\d", numeric):
        raise fail("INVALID_ARGUMENT", "Equation RHS cannot be evaluated", "e.g. 80 or \"D\" * 2")


def fail_if_component_mated(name: str, mate_names: Sequence[str]) -> None:
    """Pose tools do not solve mates: fail clearly when the component is already mated."""
    if not mate_names:
        return
    shown = ", ".join(str(n) for n in mate_names[:4])
    extra = "…" if len(mate_names) > 4 else ""
    raise fail(
        "FEATURE_CREATE_FAILED",
        f"Component {name!r} is mate-constrained: {shown}{extra}",
        "Call delete_mate before move/rotate; pose tools do not solve mates",
        component=name,
        mates=list(mate_names),
    )
