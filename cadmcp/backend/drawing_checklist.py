"""Pure helpers for drawing release checklist (inspect + verify)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from cadmcp.backend.protocol.constants import TITLE_BLOCK_DEFAULT_KEYS


def model_doc_type_from_path(path: str | None) -> str:
    """Return part|assembly|unknown from a model file path."""
    if not path:
        return "unknown"
    suf = Path(str(path)).suffix.lower()
    if suf == ".sldasm":
        return "assembly"
    if suf == ".sldprt":
        return "part"
    return "unknown"


def compute_tolerance_gaps(
    *,
    dimension_names: list[str],
    toleranced_names: set[str],
    failed_requests: list[str] | None = None,
) -> tuple[list[dict], list[str], list[str]]:
    """Return (tolerance_records_stub, missing_tolerances, untoleranced_dimensions).

    ``missing_tolerances`` = apply requests that did not land.
    ``untoleranced_dimensions`` = dims present on the drawing without a successful tol.
    """
    dims = [str(d).strip() for d in dimension_names if str(d).strip()]
    ok = {str(n).strip() for n in toleranced_names if str(n).strip()}
    untoleranced = [d for d in dims if d not in ok]
    missing = [str(n).strip() for n in (failed_requests or []) if str(n).strip()]
    # De-dupe preserve order
    seen: set[str] = set()
    missing_u: list[str] = []
    for n in missing:
        if n not in seen:
            seen.add(n)
            missing_u.append(n)
    return [], missing_u, untoleranced


def missing_title_fields(
    title_block: dict[str, str],
    required_keys: list[str] | None = None,
) -> list[str]:
    keys = list(required_keys) if required_keys is not None else list(TITLE_BLOCK_DEFAULT_KEYS)
    return [k for k in keys if not str(title_block.get(k) or "").strip()]


def drawing_needs_bom(
    *,
    model_doc_type: str,
    require_bom: bool | None,
) -> bool:
    """Auto: assembly drawings require BOM; part drawings do not."""
    if require_bom is not None:
        return bool(require_bom)
    return model_doc_type == "assembly"


def summarize_inspect_for_verify(
    info: dict[str, Any], thr: dict[str, Any]
) -> tuple[list[str], bool]:
    """Return (problem strings, need_bom) for verify_model drawing group."""
    problems: list[str] = []
    if int(info.get("view_count") or 0) <= 0:
        problems.append("no views")
    if int(info.get("annotation_count") or 0) < 0:
        problems.append("annotation_count invalid")

    required_keys = thr.get("required_title_keys")
    if required_keys is None:
        # Default release gate: full TITLE_BLOCK_DEFAULT_KEYS via inspect field
        missing = list(info.get("missing_title_fields") or [])
    else:
        if not isinstance(required_keys, list):
            problems.append("required_title_keys must be an array")
            missing = []
        else:
            title = dict(info.get("title_block") or {})
            missing = missing_title_fields(title, [str(k) for k in required_keys])
    if missing:
        problems.append("missing title: " + ",".join(missing))

    model_type = str(info.get("model_doc_type") or "unknown")
    if "require_bom" in thr:
        need_bom = drawing_needs_bom(
            model_doc_type=model_type, require_bom=bool(thr.get("require_bom"))
        )
    else:
        need_bom = drawing_needs_bom(model_doc_type=model_type, require_bom=None)

    min_datums = thr.get("min_datums")
    if min_datums is not None:
        try:
            need = int(min_datums)
        except (TypeError, ValueError):
            problems.append("min_datums must be an integer")
            need = 0
        if int(info.get("datum_count") or 0) < need:
            problems.append(f"datums={info.get('datum_count')} < min_datums={need}")

    req_syms = thr.get("required_gdt_symbols")
    if req_syms is not None:
        if not isinstance(req_syms, list):
            problems.append("required_gdt_symbols must be an array")
        else:
            have = {
                str(g.get("symbol") or "").strip().lower()
                for g in (info.get("gdts") or [])
                if isinstance(g, dict)
            }
            for sym in req_syms:
                s = str(sym).strip().lower()
                if s and s not in have:
                    problems.append(f"missing gdt symbol: {sym}")

    if thr.get("fail_on_untoleranced"):
        unt = list(info.get("untoleranced_dimensions") or [])
        if unt:
            problems.append("untoleranced: " + ",".join(unt[:12]) + ("…" if len(unt) > 12 else ""))
        miss = list(info.get("missing_tolerances") or [])
        if miss:
            problems.append("missing_tolerances: " + ",".join(miss[:12]))

    return problems, need_bom
