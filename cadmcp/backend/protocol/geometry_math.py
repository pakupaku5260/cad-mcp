"""Protocol layer · pure math (CAD-agnostic)."""
from __future__ import annotations

import math

from cadmcp.errors import fail

from .constants import REVOLVE_AXES


def rotation_matrix_axis(
    axis: str, angle_rad: float
) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
    if axis not in REVOLVE_AXES:
        raise fail(
            "INVALID_ARGUMENT",
            f"Unknown rotation axis: {axis!r}",
            f"axis: {', '.join(REVOLVE_AXES)}",
            requested=axis,
        )
    signed = float(angle_rad) if axis[0] == "+" else -float(angle_rad)
    c, s = math.cos(signed), math.sin(signed)
    letter = axis[1]
    if letter == "z":
        return ((c, -s, 0.0), (s, c, 0.0), (0.0, 0.0, 1.0))
    if letter == "x":
        return ((1.0, 0.0, 0.0), (0.0, c, -s), (0.0, s, c))
    return ((c, 0.0, s), (0.0, 1.0, 0.0), (-s, 0.0, c))


def rotation_matrix_dir(
    axis: tuple[float, float, float], angle_rad: float
) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
    x, y, z = axis
    n = math.sqrt(x * x + y * y + z * z)
    if n < 1e-15:
        raise fail("INVALID_ARGUMENT", "Rotation axis has zero length", "Provide a non-zero direction")
    x, y, z = x / n, y / n, z / n
    c, s = math.cos(float(angle_rad)), math.sin(float(angle_rad))
    c1 = 1.0 - c
    return (
        (c + x * x * c1, x * y * c1 - z * s, x * z * c1 + y * s),
        (y * x * c1 + z * s, c + y * y * c1, y * z * c1 - x * s),
        (z * x * c1 - y * s, z * y * c1 + x * s, c + z * z * c1),
    )


def apply_matrix3(
    matrix: tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]],
    vec: tuple[float, float, float],
) -> tuple[float, float, float]:
    return (
        matrix[0][0] * vec[0] + matrix[0][1] * vec[1] + matrix[0][2] * vec[2],
        matrix[1][0] * vec[0] + matrix[1][1] * vec[1] + matrix[1][2] * vec[2],
        matrix[2][0] * vec[0] + matrix[2][1] * vec[1] + matrix[2][2] * vec[2],
    )


def matmul3(
    a: tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]],
    b: tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]],
) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
    return (
        (
            a[0][0] * b[0][0] + a[0][1] * b[1][0] + a[0][2] * b[2][0],
            a[0][0] * b[0][1] + a[0][1] * b[1][1] + a[0][2] * b[2][1],
            a[0][0] * b[0][2] + a[0][1] * b[1][2] + a[0][2] * b[2][2],
        ),
        (
            a[1][0] * b[0][0] + a[1][1] * b[1][0] + a[1][2] * b[2][0],
            a[1][0] * b[0][1] + a[1][1] * b[1][1] + a[1][2] * b[2][1],
            a[1][0] * b[0][2] + a[1][1] * b[1][2] + a[1][2] * b[2][2],
        ),
        (
            a[2][0] * b[0][0] + a[2][1] * b[1][0] + a[2][2] * b[2][0],
            a[2][0] * b[0][1] + a[2][1] * b[1][1] + a[2][2] * b[2][1],
            a[2][0] * b[0][2] + a[2][1] * b[1][2] + a[2][2] * b[2][2],
        ),
    )


def rotate_point_about_axis(
    point: tuple[float, float, float],
    origin: tuple[float, float, float],
    axis: str,
    angle_rad: float,
) -> tuple[float, float, float]:
    delta = (point[0] - origin[0], point[1] - origin[1], point[2] - origin[2])
    rotated = apply_matrix3(rotation_matrix_axis(axis, angle_rad), delta)
    return (origin[0] + rotated[0], origin[1] + rotated[1], origin[2] + rotated[2])
    