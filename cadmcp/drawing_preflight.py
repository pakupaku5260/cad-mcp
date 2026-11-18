"""DrawingSpec text preflight (F18). Pure logic — no COM/dispatch/backend calls.

Checks DrawingSpec JSON self-consistency before create_drawing. This is **not**
``verify_model`` drawing.completeness (publish readiness of an existing drawing)
and **not** ``inspect_drawing`` (live drawing fact snapshot).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cadmcp.backend.protocol.constants import (
    BOM_TYPES,
    GDT_SYMBOLS,
    TITLE_BLOCK_DEFAULT_KEYS,
)
from cadmcp.drawing_spec import load_drawing_spec
from cadmcp.result import VerificationCheck
from cadmcp.verification import build_task_verification

# Same vocabulary as drawing_spec._VIEWS / create_drawing_view aliases (orient field).
VIEW_ORIENTATIONS: frozenset[str] = frozenset(
    {"front", "back", "left", "right", "top", "bottom", "isometric"}
)

ASSUMPTIONS: tuple[str, ...] = (
    "preflight checks DrawingSpec text self-consistency only; "
    "it does not guarantee create_drawing will succeed on live SolidWorks",
    "view orientations and GDT/BOM/title-block enums come from "
    "cadmcp.backend.protocol.constants (and VIEW_ORIENTATIONS aligned with drawing_spec)",
    "not verify_model drawing.completeness (publish readiness) and not inspect_drawing",
)

CheckFn = Callable[[dict[str, Any]], VerificationCheck | str]


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    description: str
    check: CheckFn


def _all_views(spec: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Collect view dicts across sheets or top-level; None if views field(s) absent."""
    sheets = spec.get("sheets")
    if isinstance(sheets, list):
        found = False
        out: list[dict[str, Any]] = []
        for sh in sheets:
            if not isinstance(sh, dict):
                continue
            if "views" not in sh:
                continue
            found = True
            views = sh.get("views")
            if isinstance(views, list):
                out.extend(v for v in views if isinstance(v, dict))
        return out if found else None
    if "views" not in spec:
        return None
    views = spec.get("views")
    if not isinstance(views, list):
        return []
    return [v for v in views if isinstance(v, dict)]


def _view_orient(view: dict[str, Any]) -> str:
    raw = view.get("orientation", view.get("orient", ""))
    return str(raw or "").strip().lower()


def _check_spec_loadable(spec: dict[str, Any]) -> VerificationCheck | str:
    return VerificationCheck(name="spec_loadable", ok=True, detail="spec loaded")


def _check_has_sheets(spec: dict[str, Any]) -> VerificationCheck | str:
    if "sheets" not in spec:
        return "missing sheets (L2 single-sheet form)"
    sheets = spec.get("sheets")
    if not isinstance(sheets, list):
        return VerificationCheck(
            name="has_sheets", ok=False, detail="sheets is not an array"
        )
    count = len(sheets)
    ok = count >= 1
    return VerificationCheck(name="has_sheets", ok=ok, detail=f"sheet_count={count}")


def _check_has_views(spec: dict[str, Any]) -> VerificationCheck | str:
    views = _all_views(spec)
    if views is None:
        return "missing views"
    count = len(views)
    ok = count >= 1
    return VerificationCheck(name="has_views", ok=ok, detail=f"view_count={count}")


def _check_valid_view_orientations(spec: dict[str, Any]) -> VerificationCheck | str:
    views = _all_views(spec)
    if views is None:
        return "missing views"
    if not views:
        return VerificationCheck(
            name="valid_view_orientations",
            ok=False,
            detail="no views to validate",
        )
    bad = [_view_orient(v) for v in views if _view_orient(v) not in VIEW_ORIENTATIONS]
    ok = not bad
    return VerificationCheck(
        name="valid_view_orientations",
        ok=ok,
        detail="all orientations known" if ok else f"unknown orientations: {bad}",
    )


def _check_valid_gdt_symbols(spec: dict[str, Any]) -> VerificationCheck | str:
    if "gdts" not in spec:
        return "missing gdts"
    gdts = spec.get("gdts")
    if not isinstance(gdts, list):
        return VerificationCheck(
            name="valid_gdt_symbols", ok=False, detail="gdts is not an array"
        )
    allowed = set(GDT_SYMBOLS)
    bad: list[str] = []
    for item in gdts:
        if not isinstance(item, dict):
            continue
        if str(item.get("kind", "")).strip().lower() != "gdt":
            continue
        symbol = str(item.get("symbol") or "").strip().lower()
        if symbol not in allowed:
            bad.append(symbol)
    ok = not bad
    return VerificationCheck(
        name="valid_gdt_symbols",
        ok=ok,
        detail="all gdt symbols known" if ok else f"unknown symbols: {bad}",
    )


def _check_valid_bom_types(spec: dict[str, Any]) -> VerificationCheck | str:
    if "bom" not in spec:
        return "missing bom"
    bom = spec.get("bom")
    allowed = set(BOM_TYPES)
    if isinstance(bom, str):
        bom_type = bom.strip().lower()
    elif isinstance(bom, dict):
        bom_type = str(bom.get("type") or bom.get("bom_type") or "").strip().lower()
    else:
        return VerificationCheck(
            name="valid_bom_types",
            ok=False,
            detail="bom must be a string or object with type",
        )
    ok = bom_type in allowed
    return VerificationCheck(
        name="valid_bom_types",
        ok=ok,
        detail=f"bom_type={bom_type!r}" if ok else f"unknown bom_type={bom_type!r}",
    )


def _check_title_block_keys(spec: dict[str, Any]) -> VerificationCheck | str:
    if "title_block" not in spec:
        return "missing title_block"
    title = spec.get("title_block")
    if not isinstance(title, dict):
        return VerificationCheck(
            name="title_block_keys_wellformed",
            ok=False,
            detail="title_block is not an object",
        )
    allowed = set(TITLE_BLOCK_DEFAULT_KEYS)
    keys = [str(k) for k in title]
    unknown = [k for k in keys if k not in allowed]
    dupes = sorted({k for k in keys if keys.count(k) > 1})
    ok = not unknown and not dupes
    if ok:
        detail = f"title_block_keys={keys}"
    elif unknown and dupes:
        detail = f"unknown={unknown}; duplicates={dupes}"
    elif unknown:
        detail = f"unknown keys: {unknown}"
    else:
        detail = f"duplicate keys: {dupes}"
    return VerificationCheck(name="title_block_keys_wellformed", ok=ok, detail=detail)


def _check_no_duplicate_sheet_names(spec: dict[str, Any]) -> VerificationCheck | str:
    if "sheets" not in spec:
        return "missing sheets"
    sheets = spec.get("sheets")
    if not isinstance(sheets, list):
        return VerificationCheck(
            name="no_duplicate_sheet_names",
            ok=False,
            detail="sheets is not an array",
        )
    names = [str(sh.get("name") or "") for sh in sheets if isinstance(sh, dict)]
    dupes = sorted({n for n in names if n and names.count(n) > 1})
    ok = not dupes
    return VerificationCheck(
        name="no_duplicate_sheet_names",
        ok=ok,
        detail="sheet names unique" if ok else f"duplicate sheet names: {dupes}",
    )


PREFLIGHT_CHECKS: tuple[PreflightCheck, ...] = (
    PreflightCheck(
        name="spec_loadable",
        description="DrawingSpec JSON loaded successfully",
        check=_check_spec_loadable,
    ),
    PreflightCheck(
        name="has_sheets",
        description="Spec declares at least one sheet (skipped for L2 form without sheets)",
        check=_check_has_sheets,
    ),
    PreflightCheck(
        name="has_views",
        description="Spec declares at least one view across sheets or top-level",
        check=_check_has_views,
    ),
    PreflightCheck(
        name="valid_view_orientations",
        description="Every view orient/orientation is a known standard view",
        check=_check_valid_view_orientations,
    ),
    PreflightCheck(
        name="valid_gdt_symbols",
        description="Every gdt.symbol is in GDT_SYMBOLS (skipped if gdts omitted)",
        check=_check_valid_gdt_symbols,
    ),
    PreflightCheck(
        name="valid_bom_types",
        description="Declared bom.type is in BOM_TYPES (skipped if bom omitted)",
        check=_check_valid_bom_types,
    ),
    PreflightCheck(
        name="title_block_keys_wellformed",
        description="title_block keys ⊆ TITLE_BLOCK_DEFAULT_KEYS with no duplicates",
        check=_check_title_block_keys,
    ),
    PreflightCheck(
        name="no_duplicate_sheet_names",
        description="Sheet names are unique (skipped if sheets omitted)",
        check=_check_no_duplicate_sheet_names,
    ),
)


def evaluate_spec(
    spec: dict[str, Any],
) -> tuple[list[VerificationCheck], list[dict[str, str]]]:
    """Run the eight preflight checks against an in-memory spec dict."""
    checks: list[VerificationCheck] = []
    skipped: list[dict[str, str]] = []
    for item in PREFLIGHT_CHECKS:
        result = item.check(spec)
        if isinstance(result, str):
            skipped.append({"name": item.name, "reason": result})
        else:
            checks.append(result)
    return checks, skipped


def evaluate_preflight(
    spec_path: str | Path,
) -> tuple[list[VerificationCheck], list[dict[str, str]]]:
    """Load DrawingSpec from path then run preflight checks.

    Load failures (PATH_NOT_FOUND / INVALID_ARGUMENT) propagate unchanged.
    """
    spec = load_drawing_spec(Path(spec_path))
    return evaluate_spec(spec)


def assess(spec_path: str | Path) -> dict[str, Any]:
    """Full preflight payload for check_drawing_spec."""
    checks, skipped = evaluate_preflight(spec_path)
    verification = build_task_verification(checks)
    return {
        "status": verification.status,
        "verification": verification.model_dump(),
        "checks_run": [c.name for c in PREFLIGHT_CHECKS],
        "skipped": skipped,
        "assumptions": list(ASSUMPTIONS),
        "risk": "unverified",
    }


__all__ = [
    "ASSUMPTIONS",
    "PREFLIGHT_CHECKS",
    "VIEW_ORIENTATIONS",
    "PreflightCheck",
    "assess",
    "evaluate_preflight",
    "evaluate_spec",
]
