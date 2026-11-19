"""Verification toolset: read-only verify_model (F2) + verify_step_readback (P5).

Reuses fingerprint / force_rebuild / check_interference / list_mates /
inspect_drawing / get_bom. Does not mutate the model.
"""
from __future__ import annotations

import logging
import math
import shutil
import time
from pathlib import Path
from typing import Any

from cadmcp.backend.drawing_checklist import summarize_inspect_for_verify
from cadmcp.backend.protocol.constants import TITLE_BLOCK_DEFAULT_KEYS
from cadmcp.errors import CadMcpError, fail
from cadmcp.kernel import OpContext
from cadmcp.registry import ToolSpec, make_schema
from cadmcp.result import VerificationCheck
from cadmcp.safety import ensure_input_path, ensure_output_path
from cadmcp.units import SUPPORTED_UNITS, UnitContext
from cadmcp.verification import VERIFY_GROUPS, build_task_verification

log = logging.getLogger(__name__)

_GROUP_ENUM = list(VERIFY_GROUPS)
_RETRYABLE_CODES = frozenset({"COM_CALL_FAILED", "EXEC_TIMEOUT"})
_STEP_EXTS = frozenset({".step", ".stp"})
_MAX_RETRIES_CAP = 2

# Groups that apply per active document type (others → skipped_groups).
_APPLICABLE: dict[str, frozenset[str]] = {
    "part": frozenset({"geometry", "features", "mass_bbox"}),
    "assembly": frozenset({"geometry", "features", "mass_bbox", "assembly"}),
    "drawing": frozenset({"drawing"}),
}

_UNIT_ENUM = sorted(SUPPORTED_UNITS)


def _unit_ctx(ctx: OpContext, unit: str) -> UnitContext:
    return ctx.units if unit == ctx.units.external_unit else UnitContext(unit)


def _fp_public(fp: Any, u: UnitContext) -> dict[str, Any]:
    return {
        "volume": u.volume_from_m3(fp.volume_m3),
        "surface_area": u.area_from_m2(fp.surface_area_m2),
        "mass_kg": fp.mass_kg,
        "face_count": fp.face_count,
        "edge_count": fp.edge_count,
        "bbox": list(u.tuple_from_m(fp.bbox_m)),
        "length_unit": u.external_unit,
        "volume_unit": f"{u.external_unit}3",
        "area_unit": f"{u.external_unit}2",
    }


def _check(name: str, ok: bool, detail: str, code: str | None = None) -> VerificationCheck:
    return VerificationCheck(name=name, ok=ok, detail=detail, code=code)


def _parse_groups(raw: list[str] | None) -> list[str] | None:
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise fail(
            "INVALID_ARGUMENT",
            "groups must be an array of group names",
            f"Choose from: {', '.join(VERIFY_GROUPS)}",
        )
    out: list[str] = []
    for g in raw:
        if g not in VERIFY_GROUPS:
            raise fail(
                "INVALID_ARGUMENT",
                f"Unknown verify group {g!r}",
                f"Choose from: {', '.join(VERIFY_GROUPS)}",
                group=g,
            )
        if g not in out:
            out.append(g)
    return out


def _parse_thresholds(raw: dict[str, Any] | None) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise fail(
            "INVALID_ARGUMENT",
            "thresholds must be an object",
            "Pass numeric limits and optional holes=[{x,y,z,tol_mm}, ...]",
        )
    allowed = {
        "volume_min_mm3",
        "volume_max_mm3",
        "mass_min_kg",
        "mass_max_kg",
        "bbox_dx_max_mm",
        "bbox_dy_max_mm",
        "bbox_dz_max_mm",
        "holes",
        # Drawing release checklist
        "required_title_keys",
        "require_bom",
        "min_datums",
        "required_gdt_symbols",
        "fail_on_untoleranced",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise fail(
            "INVALID_ARGUMENT",
            f"Unknown thresholds keys: {', '.join(unknown)}",
            f"Allowed: {', '.join(sorted(allowed))}",
            unknown=unknown,
        )
    holes = raw.get("holes")
    if holes is not None:
        if not isinstance(holes, list):
            raise fail(
                "INVALID_ARGUMENT",
                "thresholds.holes must be an array",
                "Each hole needs {x,y,z,tol_mm} in the unit of the unit param (default mm)",
            )
        for i, h in enumerate(holes):
            if not isinstance(h, dict) or not all(k in h for k in ("x", "y", "z", "tol_mm")):
                raise fail(
                    "INVALID_ARGUMENT",
                    f"thresholds.holes[{i}] must include x,y,z,tol_mm",
                    "Example: {\"x\":10,\"y\":10,\"z\":5,\"tol_mm\":0.1}",
                )
            if float(h["tol_mm"]) < 0:
                raise fail(
                    "INVALID_ARGUMENT",
                    "thresholds.holes tol_mm cannot be negative",
                    "Pass tol_mm >= 0",
                )
    keys = raw.get("required_title_keys")
    if keys is not None and not isinstance(keys, list):
        raise fail(
            "INVALID_ARGUMENT",
            "thresholds.required_title_keys must be an array of strings",
            f"Example: {list(TITLE_BLOCK_DEFAULT_KEYS[:3])}",
        )
    syms = raw.get("required_gdt_symbols")
    if syms is not None and not isinstance(syms, list):
        raise fail(
            "INVALID_ARGUMENT",
            "thresholds.required_gdt_symbols must be an array of strings",
            'Example: ["position"]',
        )
    if "min_datums" in raw and raw["min_datums"] is not None:
        try:
            if int(raw["min_datums"]) < 0:
                raise ValueError
        except (TypeError, ValueError):
            raise fail(
                "INVALID_ARGUMENT",
                "thresholds.min_datums must be a non-negative integer",
                "Pass min_datums >= 0",
            ) from None
    if "require_bom" in raw and raw["require_bom"] is not None and not isinstance(
        raw["require_bom"], bool
    ):
        raise fail(
            "INVALID_ARGUMENT",
            "thresholds.require_bom must be a boolean",
            "Omit for auto (assembly drawings only)",
        )
    if "fail_on_untoleranced" in raw and raw["fail_on_untoleranced"] is not None and not isinstance(
        raw["fail_on_untoleranced"], bool
    ):
        raise fail(
            "INVALID_ARGUMENT",
            "thresholds.fail_on_untoleranced must be a boolean",
            "Default false until dimension-tolerance COM is probe-verified",
        )
    return dict(raw)


def _run_geometry(ctx: OpContext, fp: Any, doc_type: str) -> list[VerificationCheck]:
    has_solid = fp.face_count > 0 and fp.volume_m3 > 0.0
    if has_solid:
        return [
            _check(
                "geometry.solid",
                True,
                f"face_count={fp.face_count} volume_m3={fp.volume_m3:.6g}",
            )
        ]
    # Assemblies may have components while the aggregate fingerprint stays empty (esp. Fake).
    if doc_type == "assembly":
        comps = ctx.backend.list_components()
        if comps:
            return [
                _check(
                    "geometry.solid",
                    True,
                    f"assembly components={len(comps)}; aggregate face_count={fp.face_count}",
                )
            ]
        return [
            _check(
                "geometry.empty_body",
                False,
                "assembly has no components and no solid fingerprint",
                "VERIFY_EMPTY_BODY",
            )
        ]
    return [
        _check(
            "geometry.empty_body",
            False,
            f"face_count={fp.face_count} volume_m3={fp.volume_m3}",
            "VERIFY_EMPTY_BODY",
        )
    ]


def _run_features(ctx: OpContext) -> list[VerificationCheck]:
    outcome = ctx.backend.force_rebuild()
    errs = list(outcome.feature_errors or [])
    if not outcome.ok or errs:
        detail = "; ".join(errs) if errs else "rebuild failed"
        return [_check("features.tree", False, detail, "VERIFY_FEATURE_ERROR")]
    return [_check("features.tree", True, "rebuild ok; no feature errors")]


def _run_mass_bbox(
    ctx: OpContext, fp: Any, thresholds: dict[str, Any], uc: UnitContext
) -> list[VerificationCheck]:
    checks: list[VerificationCheck] = []
    # Always evaluate thresholds in mm3 / kg / mm for stable keys.
    mm = UnitContext("mm")
    vol_mm3 = mm.volume_from_m3(fp.volume_m3)
    mass = fp.mass_kg
    x0, y0, z0, x1, y1, z1 = fp.bbox_m
    dx_mm, dy_mm, dz_mm = mm.from_m(x1 - x0), mm.from_m(y1 - y0), mm.from_m(z1 - z0)

    def _bound(key: str, value: float, *, lower: bool) -> None:
        if key not in thresholds:
            return
        limit = float(thresholds[key])
        ok = value >= limit if lower else value <= limit
        code = (
            "VERIFY_MASS_OUT_OF_RANGE"
            if key.startswith(("volume_", "mass_"))
            else "VERIFY_BBOX_OUT_OF_RANGE"
        )
        checks.append(
            _check(
                f"mass_bbox.{key}",
                ok,
                f"value={value:.6g} limit={limit:.6g}",
                None if ok else code,
            )
        )

    _bound("volume_min_mm3", vol_mm3, lower=True)
    _bound("volume_max_mm3", vol_mm3, lower=False)
    _bound("mass_min_kg", mass, lower=True)
    _bound("mass_max_kg", mass, lower=False)
    _bound("bbox_dx_max_mm", dx_mm, lower=False)
    _bound("bbox_dy_max_mm", dy_mm, lower=False)
    _bound("bbox_dz_max_mm", dz_mm, lower=False)

    holes = thresholds.get("holes")
    if holes:
        cylinders = [
            f
            for f in ctx.backend.get_faces(kind="cylinder")
            if f.kind == "cylinder"
        ]
        for i, hole in enumerate(holes):
            expect = (
                uc.to_m(float(hole["x"])),
                uc.to_m(float(hole["y"])),
                uc.to_m(float(hole["z"])),
            )
            tol_m = UnitContext("mm").to_m(float(hole["tol_mm"]))
            if not cylinders:
                checks.append(
                    _check(
                        f"mass_bbox.hole[{i}]",
                        False,
                        "no cylindrical faces to match thresholds.holes",
                        "VERIFY_HOLE_POSITION",
                    )
                )
                continue
            best = min(
                (math.dist(expect, f.centroid_m), f) for f in cylinders
            )
            dist, face = best
            ok = dist <= tol_m
            checks.append(
                _check(
                    f"mass_bbox.hole[{i}]",
                    ok,
                    (
                        f"nearest_face={face.index} dist_mm={mm.from_m(dist):.6g} "
                        f"tol_mm={float(hole['tol_mm'])} "
                        "(threshold hole-axis check; not drawing tolerance)"
                    ),
                    None if ok else "VERIFY_HOLE_POSITION",
                )
            )

    if not checks:
        checks.append(
            _check(
                "mass_bbox.snapshot",
                True,
                f"volume_mm3={vol_mm3:.6g} mass_kg={mass:.6g} bbox_mm=[{dx_mm:.6g},{dy_mm:.6g},{dz_mm:.6g}]",
            )
        )
    return checks


def _run_assembly(ctx: OpContext) -> list[VerificationCheck]:
    checks: list[VerificationCheck] = []
    pairs, method = ctx.backend.check_interference()
    bad = [p for p in pairs if p.status != "clear"]
    if bad:
        detail = f"method={method}; " + ", ".join(f"{p.a}↔{p.b}:{p.status}" for p in bad[:8])
        checks.append(_check("assembly.interference", False, detail, "VERIFY_INTERFERENCE"))
    else:
        checks.append(
            _check("assembly.interference", True, f"method={method}; no interfering pairs")
        )

    mates = ctx.backend.list_mates()
    mate_errs = [m for m in mates if m.sw_error not in (None, 0)]
    if mate_errs:
        detail = ", ".join(f"{m.name}:sw_error={m.sw_error}" for m in mate_errs[:8])
        checks.append(_check("assembly.mates", False, detail, "VERIFY_MATE_ERROR"))
    else:
        checks.append(_check("assembly.mates", True, f"mates={len(mates)}; no sw_error"))
    return checks


def _run_drawing(ctx: OpContext, thr: dict[str, Any]) -> list[VerificationCheck]:
    info = ctx.backend.inspect_drawing()
    problems, need_bom = summarize_inspect_for_verify(info, thr)
    bom_detail = "bom skipped (part drawing or require_bom=false)"
    if need_bom:
        try:
            source, rows = ctx.backend.get_bom()
            bom_detail = f"bom source={source} rows={len(rows)}"
            if not rows:
                problems.append("empty BOM")
        except CadMcpError as exc:
            problems.append(f"BOM missing ({exc.code})")
            bom_detail = f"bom missing ({exc.code})"
        except Exception as exc:
            problems.append(f"BOM missing ({type(exc).__name__})")
            bom_detail = f"bom missing ({type(exc).__name__})"

    detail = (
        f"{'; '.join(problems)}; " if problems else ""
        f"views={info.get('view_count')} annotations={info.get('annotation_count')}; "
        f"model={info.get('model_doc_type')}; {bom_detail}; "
        f"title_missing={len(info.get('missing_title_fields') or [])}; "
        f"untoleranced={len(info.get('untoleranced_dimensions') or [])}"
    )
    if problems:
        return [
            _check(
                "drawing.completeness",
                False,
                detail,
                "VERIFY_DRAWING_INCOMPLETE",
            )
        ]
    return [_check("drawing.completeness", True, detail)]


def _clamp_max_retries(raw: Any) -> tuple[int, str | None]:
    """Return (clamped retries, optional warning). Illegal → 0 + warning."""
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return 0, f"max_retries={raw!r} invalid; using 0"
    if n < 0 or n > _MAX_RETRIES_CAP:
        return 0, f"max_retries={n} out of 0..{_MAX_RETRIES_CAP}; using 0"
    return n, None


def _run_one_group(
    ctx: OpContext,
    group: str,
    *,
    fp: Any,
    doc_type: str,
    thr: dict[str, Any],
    uc: UnitContext,
) -> list[VerificationCheck]:
    if group == "geometry":
        assert fp is not None
        return _run_geometry(ctx, fp, doc_type)
    if group == "features":
        return _run_features(ctx)
    if group == "mass_bbox":
        assert fp is not None
        return _run_mass_bbox(ctx, fp, thr, uc)
    if group == "assembly":
        return _run_assembly(ctx)
    if group == "drawing":
        return _run_drawing(ctx, thr)
    raise fail("INVALID_ARGUMENT", f"Unknown verify group {group!r}", f"Choose from: {', '.join(VERIFY_GROUPS)}")


def verify_model(
    ctx: OpContext,
    groups: list[str] | None = None,
    thresholds: dict[str, Any] | None = None,
    unit: str = "mm",
    partial_on_timeout: bool = False,
    max_retries: int = 0,
) -> dict:
    """Run applicable model checks; returns Verification + skipped_groups (+ P5 partial/retry)."""
    info = ctx.backend.active_document()
    if info is None:
        raise fail(
            "NO_ACTIVE_DOCUMENT",
            "No active document to verify",
            "Create or open a part, assembly, or drawing first",
        )
    doc_type = info.doc_type
    requested = _parse_groups(groups)
    thr = _parse_thresholds(thresholds)
    uc = _unit_ctx(ctx, unit)
    retries_cap, retry_warn = _clamp_max_retries(max_retries)
    result_warnings: list[str] = []
    if retry_warn:
        log.warning("%s", retry_warn)
        result_warnings.append(retry_warn)

    applicable = _APPLICABLE.get(doc_type, frozenset())
    if requested is None:
        to_run = [g for g in VERIFY_GROUPS if g in applicable]
        skipped = [
            {"group": g, "reason": f"not applicable to doc_type={doc_type}"}
            for g in VERIFY_GROUPS
            if g not in applicable
        ]
    else:
        to_run = [g for g in requested if g in applicable]
        skipped = [
            {"group": g, "reason": f"not applicable to doc_type={doc_type}"}
            for g in requested
            if g not in applicable
        ]

    checks: list[VerificationCheck] = []
    fp = None
    fp_public = None
    fp_failed = False
    need_fp = any(g in to_run for g in ("geometry", "mass_bbox"))
    if need_fp and doc_type in {"part", "assembly"}:
        # Fingerprint fetch: retryable under same rules when partial_on_timeout
        fp_attempts = 0
        while True:
            try:
                fp = ctx.backend.fingerprint()
                fp_public = _fp_public(fp, uc)
                break
            except CadMcpError as exc:
                if exc.code not in _RETRYABLE_CODES:
                    raise
                if fp_attempts >= retries_cap:
                    if partial_on_timeout:
                        checks.append(
                            _check(
                                "fingerprint",
                                False,
                                f"{exc.code}: {exc.message}",
                                exc.code,
                            )
                        )
                        fp_failed = True
                        break
                    raise
                fp_attempts += 1

    completed: list[str] = []
    incomplete: list[dict[str, Any]] = []
    retries_log: list[dict[str, Any]] = []
    groups_actually: list[str] = []

    for group in to_run:
        if group in {"geometry", "mass_bbox"} and fp_failed:
            incomplete.append(
                {
                    "group": group,
                    "reason": "fingerprint unavailable after retryable COM failure",
                    "code": "COM_CALL_FAILED",
                }
            )
            groups_actually.append(group)
            continue

        attempt_rows: list[dict[str, Any]] = []
        used_retries = 0
        while True:
            t0 = time.perf_counter()
            try:
                group_checks = _run_one_group(
                    ctx, group, fp=fp, doc_type=doc_type, thr=thr, uc=uc
                )
                elapsed = time.perf_counter() - t0
                if attempt_rows:
                    attempt_rows.append(
                        {
                            "attempt": used_retries + 1,
                            "ok": True,
                            "elapsed_s": round(elapsed, 4),
                            "reason": "recovered",
                        }
                    )
                checks.extend(group_checks)
                completed.append(group)
                groups_actually.append(group)
                if attempt_rows:
                    retries_log.append(
                        {
                            "group": group,
                            "count": used_retries,
                            "attempts": attempt_rows,
                        }
                    )
                break
            except CadMcpError as exc:
                elapsed = time.perf_counter() - t0
                attempt_rows.append(
                    {
                        "attempt": used_retries + 1,
                        "ok": False,
                        "elapsed_s": round(elapsed, 4),
                        "reason": exc.code,
                        "message": exc.message,
                    }
                )
                if exc.code not in _RETRYABLE_CODES:
                    # Validation / verify failures bubble; do not retry
                    if attempt_rows:
                        retries_log.append(
                            {
                                "group": group,
                                "count": used_retries,
                                "attempts": attempt_rows,
                            }
                        )
                    raise
                if used_retries < retries_cap:
                    used_retries += 1
                    continue
                # Exhausted retries on timeout/COM
                retries_log.append(
                    {
                        "group": group,
                        "count": used_retries,
                        "attempts": attempt_rows,
                    }
                )
                if not partial_on_timeout:
                    raise
                checks.append(
                    _check(
                        f"{group}.timeout",
                        False,
                        f"{exc.code}: {exc.message}",
                        exc.code,
                    )
                )
                incomplete.append(
                    {
                        "group": group,
                        "reason": exc.message,
                        "code": exc.code,
                    }
                )
                groups_actually.append(group)
                break

    verification = build_task_verification(checks)
    partial = bool(incomplete)
    out: dict[str, Any] = {
        "verification": verification.model_dump(),
        "doc_type": doc_type,
        "skipped_groups": skipped,
        "groups_run": list(groups_actually) if groups_actually else list(to_run),
        "unit": uc.external_unit,
        "partial": partial,
        "completed_groups": completed,
        "incomplete_groups": incomplete,
        "retries": retries_log,
    }
    if result_warnings:
        out["warnings"] = result_warnings
    if fp_public is not None:
        out["fingerprint"] = fp_public
    return out


def verify_step_readback(
    ctx: OpContext,
    path: str,
    expected_components: int | None = None,
    expected_bbox: list[float] | None = None,
    tolerance_mm: float = 1.0,
    unit: str = "mm",
) -> dict:
    """Open a STEP copy read-only style; compare part_count / top-level bbox. Never SaveAs source."""
    if tolerance_mm < 0:
        raise fail("INVALID_ARGUMENT", "tolerance_mm must be >= 0", "Pass a non-negative tolerance")
    uc = _unit_ctx(ctx, unit)
    src = ensure_input_path(path, roots=ctx.workspace, extensions=_STEP_EXTS)
    # Prefer out/p5_step_readback/open/ when workspace is the repo root so the
    # open copy never overwrites a user-supplied source already under out/.
    base = (
        "out/p5_step_readback/open"
        if (Path(ctx.workspace) / "out").is_dir() or (Path(ctx.workspace) / "cadmcp").is_dir()
        else "p5_step_readback/open"
    )
    readback = ensure_output_path(
        f"{base}/{src.name}",
        roots=ctx.workspace,
        extensions=_STEP_EXTS,
        overwrite=True,
    )
    if Path(readback).resolve() != Path(src).resolve():
        shutil.copy2(src, readback)
    else:
        # Source already is the open path; still safe — do not rewrite in place.
        pass

    notes: list[str] = []
    # Close any active doc before opening the STEP copy (do not touch source).
    for _ in range(8):
        if ctx.backend.active_document() is None:
            break
        try:
            ctx.backend.close_document(discard=True)
        except Exception:
            break

    opened = ctx.backend.open_document(readback)
    try:
        doc_type = opened.doc_type
        part_count = 1
        if doc_type == "assembly":
            comps = ctx.backend.list_components_lite(children=False)
            part_count = len(comps)
        else:
            notes.append(
                "STEP imported as a single part document (part_count=1); "
                "SolidWorks may flatten multi-body assemblies depending on import options"
            )
        fp = ctx.backend.fingerprint()
        bbox = list(uc.tuple_from_m(fp.bbox_m)) if fp.bbox_m is not None else None
        bbox_size = None
        if bbox is not None and len(bbox) >= 6:
            bbox_size = [bbox[3] - bbox[0], bbox[4] - bbox[1], bbox[5] - bbox[2]]
    finally:
        try:
            ctx.backend.close_document(discard=True)
        except Exception:
            pass

    exp_bbox = None
    if expected_bbox is not None:
        if not isinstance(expected_bbox, (list, tuple)) or len(expected_bbox) != 6:
            raise fail(
                "INVALID_ARGUMENT",
                "expected_bbox must be [xmin,ymin,zmin,xmax,ymax,zmax]",
                "Pass six numbers in the call unit",
            )
        exp_bbox = [float(v) for v in expected_bbox]

    matches: dict[str, bool] = {}
    diff: dict[str, Any] = {}
    if expected_components is not None:
        matches["components"] = int(part_count) == int(expected_components)
        diff["components"] = {
            "actual": part_count,
            "expected": int(expected_components),
        }
        if not matches["components"]:
            notes.append(
                f"part_count={part_count} != expected_components={expected_components} "
                "(do not treat as pass; see notes for import limits)"
            )
    if exp_bbox is not None and bbox is not None:
        deltas = [abs(bbox[i] - exp_bbox[i]) for i in range(6)]
        matches["bbox"] = max(deltas) <= float(tolerance_mm)
        diff["bbox"] = {
            "actual": bbox,
            "expected": exp_bbox,
            "abs_delta": deltas,
            "tolerance_mm": float(tolerance_mm),
            "max_delta": max(deltas),
        }
    elif exp_bbox is not None:
        matches["bbox"] = False
        diff["bbox"] = {"actual": None, "expected": exp_bbox, "reason": "bbox unavailable"}

    ok_match = all(matches.values()) if matches else True
    return {
        "ok": True,
        "matches": matches if matches else {"checked": False},
        "all_match": ok_match,
        "part_count": part_count,
        "bbox": bbox,
        "bbox_size": bbox_size,
        "expected_components": expected_components,
        "expected_bbox": exp_bbox,
        "tolerance_mm": float(tolerance_mm),
        "diff": diff,
        "source_path": str(src),
        "readback_path": str(readback),
        "doc_type": opened.doc_type,
        "unit": uc.external_unit,
        "notes": notes,
    }


VERIFICATION_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="verify_model",
        toolset="verification",
        description=(
            "Read-only checks: geometry, features, mass/bbox, assembly, drawing release. "
            "Drawing: title keys, assembly BOM auto, optional datums/GDT/untoleranced. "
            "Omit groups → applicable only; skipped_groups listed. "
            "thresholds.holes = cylinder axes (mm). "
            "partial_on_timeout=true continues after group COM timeout (partial≠pass); "
            "max_retries 0..2 for COM_CALL_FAILED/EXEC_TIMEOUT only."
        ),
        input_schema=make_schema(
            {
                "groups": {
                    "type": "array",
                    "items": {"type": "string", "enum": _GROUP_ENUM},
                    "description": (
                        "Subset of geometry|features|mass_bbox|assembly|drawing. "
                        "Default: all groups applicable to the active document."
                    ),
                },
                "thresholds": {
                    "type": "object",
                    "additionalProperties": False,
                    "description": (
                        "Part: volume/mass/bbox/holes. Drawing: required_title_keys, "
                        "require_bom, min_datums, required_gdt_symbols, fail_on_untoleranced."
                    ),
                    "properties": {
                        "volume_min_mm3": {"type": "number"},
                        "volume_max_mm3": {"type": "number"},
                        "mass_min_kg": {"type": "number"},
                        "mass_max_kg": {"type": "number"},
                        "bbox_dx_max_mm": {"type": "number"},
                        "bbox_dy_max_mm": {"type": "number"},
                        "bbox_dz_max_mm": {"type": "number"},
                        "holes": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "x": {"type": "number"},
                                    "y": {"type": "number"},
                                    "z": {"type": "number"},
                                    "tol_mm": {"type": "number"},
                                },
                                "required": ["x", "y", "z", "tol_mm"],
                            },
                        },
                        "required_title_keys": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Default: TITLE_BLOCK defaults. Pass [] to skip.",
                        },
                        "require_bom": {
                            "type": "boolean",
                            "description": "Default auto: true only for assembly drawings.",
                        },
                        "min_datums": {"type": "integer", "minimum": 0},
                        "required_gdt_symbols": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "fail_on_untoleranced": {
                            "type": "boolean",
                            "description": "Default false until tolerance COM is probe-verified.",
                        },
                    },
                },
                "unit": {
                    "type": "string",
                    "enum": _UNIT_ENUM,
                    "description": "Interprets thresholds.holes x/y/z (default mm).",
                },
                "partial_on_timeout": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "If true, a group COM timeout/call failure is recorded and remaining "
                        "groups still run (partial≠verified). Default false keeps old abort."
                    ),
                },
                "max_retries": {
                    "type": "integer",
                    "default": 0,
                    "description": "Retries per group for COM_CALL_FAILED/EXEC_TIMEOUT only (0..2).",
                },
            }
        ),
        handler=verify_model,
        mutating=False,
        timeout_class="slow",
    ),
    ToolSpec(
        name="verify_step_readback",
        toolset="verification",
        description=(
            "Copy a STEP into out/p5_step_readback/, open the copy, report part_count and "
            "top-level bbox vs optional expected_components/expected_bbox. Never modifies "
            "the source; does not SaveAs. If SW imports as one part, part_count=1 with notes."
        ),
        input_schema=make_schema(
            {
                "path": {
                    "type": "string",
                    "description": "Source .step/.stp path under the workspace.",
                },
                "expected_components": {
                    "type": "integer",
                    "description": "Optional expected instance/body count after import.",
                },
                "expected_bbox": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 6,
                    "maxItems": 6,
                    "description": "Optional [xmin,ymin,zmin,xmax,ymax,zmax] in call unit.",
                },
                "tolerance_mm": {
                    "type": "number",
                    "default": 1.0,
                    "description": "Max abs bbox corner delta (mm) when expected_bbox set.",
                },
                "unit": {
                    "type": "string",
                    "enum": _UNIT_ENUM,
                    "description": "Unit for bbox comparison (default mm).",
                },
            },
            ["path"],
        ),
        handler=verify_step_readback,
        mutating=False,
        timeout_class="slow",
    ),
]

__all__ = ["VERIFICATION_SPECS", "VERIFY_GROUPS", "verify_model"]
