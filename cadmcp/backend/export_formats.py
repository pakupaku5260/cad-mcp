"""Export format and document-type contract (shared by tools and both backends)."""
from __future__ import annotations

from pathlib import Path

from cadmcp.errors import fail

# Extension to format; .stp and .step are equivalent.
EXPORT_SUFFIXES: dict[str, str] = {
    ".step": "step",
    ".stp": "step",
    ".stl": "stl",
    ".pdf": "pdf",
    ".dxf": "dxf",
}

# Active document types allowed per format (part / assembly / drawing).
ALLOWED_DOC_TYPES: dict[str, frozenset[str]] = {
    "step": frozenset({"part", "assembly"}),
    "stl": frozenset({"part", "assembly"}),
    "pdf": frozenset({"drawing"}),
    "dxf": frozenset({"drawing"}),
}

_EXPECTED = {
    "step": "part or assembly",
    "stl": "part or assembly",
    "pdf": "drawing",
    "dxf": "drawing",
}

_DOC_LABEL = {"part": "part", "assembly": "assembly", "drawing": "drawing"}


def format_for_path(path: str | Path) -> str:
    """Resolve export format from extension; unknown extensions fail (no silent fallback)."""
    suffix = Path(path).suffix.lower()
    fmt = EXPORT_SUFFIXES.get(suffix)
    if fmt is None:
        allowed = ", ".join(sorted(EXPORT_SUFFIXES))
        raise fail(
            "INVALID_ARGUMENT",
            f"Unsupported export extension: {suffix or '(none)'}",
            f"Use one of these extensions: {allowed}",
            extension=suffix,
        )
    return fmt


def ensure_doc_type(fmt: str, doc_type: str) -> None:
    """Ensure active document type matches export format; mismatch yields INVALID_ARGUMENT."""
    allowed = ALLOWED_DOC_TYPES.get(fmt)
    if allowed is None:
        raise fail(
            "INVALID_ARGUMENT",
            f"Unknown export format: {fmt}",
            f"Available formats: {', '.join(sorted(ALLOWED_DOC_TYPES))}",
        )
    if doc_type not in allowed:
        raise fail(
            "INVALID_ARGUMENT",
            f"{fmt} export requires a {_EXPECTED[fmt]} document; current type is {_DOC_LABEL.get(doc_type, doc_type)}",
            f"Switch to a {_EXPECTED[fmt]} document, or use a matching extension",
            doc_type=doc_type,
            format=fmt,
        )


# EXP3: STEP AP / STL quality. AP242 still writes AP203 on SW2025 local probe, so not exposed.
STEP_AP_ALLOWED: frozenset[int] = frozenset({203, 214})
STL_QUALITY_CODES: dict[str, int] = {"coarse": 1, "fine": 2}


def validate_export_options(
    fmt: str,
    *,
    step_ap: int | None = None,
    stl_quality: str | None = None,
) -> None:
    """Validate optional export options against the format."""
    if step_ap is not None:
        if fmt != "step":
            raise fail(
                "INVALID_ARGUMENT",
                "step_ap applies only to .step/.stp export",
                "Remove step_ap, or use a .step extension",
                format=fmt,
            )
        if int(step_ap) not in STEP_AP_ALLOWED:
            raise fail(
                "INVALID_ARGUMENT",
                f"Unsupported STEP AP: {step_ap}",
                "step_ap must be 203 or 214",
                step_ap=step_ap,
            )
    if stl_quality is not None:
        if fmt != "stl":
            raise fail(
                "INVALID_ARGUMENT",
                "stl_quality applies only to .stl export",
                "Remove stl_quality, or use a .stl extension",
                format=fmt,
            )
        key = str(stl_quality).strip().lower()
        if key not in STL_QUALITY_CODES:
            raise fail(
                "INVALID_ARGUMENT",
                f"Unsupported STL quality: {stl_quality}",
                "stl_quality must be coarse or fine",
                stl_quality=stl_quality,
            )
