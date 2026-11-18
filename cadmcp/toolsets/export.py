"""Export domain: STEP/STL (part or assembly) and PDF/DXF (drawing).

Format follows the file extension; one tool covers all exports.
EXP3+: step_ap=203|214|242 (default 214); write_meta sidecar; export_batch.
"""
from __future__ import annotations

from pathlib import Path

from cadmcp.backend.export_formats import STEP_AP_DEFAULT, format_for_path, validate_export_options
from cadmcp.backend.export_meta import meta_path_for, write_step_meta
from cadmcp.backend.step_schema import detect_step_ap
from cadmcp.errors import CadMcpError, fail
from cadmcp.kernel import OpContext
from cadmcp.registry import ToolSpec, make_schema
from cadmcp.safety import ensure_input_path, ensure_output_path

_DOC_EXTS = {".sldprt", ".sldasm", ".SLDPRT", ".SLDASM"}


def export_document(
    ctx: OpContext,
    path: str,
    overwrite: bool = False,
    step_ap: int | None = None,
    stl_quality: str | None = None,
    write_meta: bool = True,
) -> dict:
    fmt = format_for_path(path)
    effective_ap = int(step_ap) if step_ap is not None else (
        STEP_AP_DEFAULT if fmt == "step" else None
    )
    validate_export_options(fmt, step_ap=effective_ap, stl_quality=stl_quality)
    suffix = Path(path).suffix.lower()
    resolved = ensure_output_path(
        path, roots=ctx.workspace, extensions={suffix}, overwrite=overwrite
    )
    quality = None if stl_quality is None else str(stl_quality).strip().lower()

    props: dict[str, str] = {}
    source_path = ""
    source_title = ""
    configuration = ""
    doc_type = ""
    if fmt == "step" and write_meta:
        try:
            props = dict(ctx.backend.get_properties())
        except CadMcpError:
            props = {}
        info = ctx.backend.active_document()
        if info is not None:
            source_path = str(info.path or "")
            source_title = str(info.title or "")
            configuration = str(info.configuration or "")
            doc_type = str(info.doc_type or "")

    backend_out = ctx.backend.export_document(
        resolved, fmt, step_ap=effective_ap, stl_quality=quality
    ) or {}

    out: dict = {"saved": True, "path": str(resolved)}
    if quality is not None:
        out["stl_quality"] = quality
    if fmt == "step" and effective_ap is not None:
        verified = backend_out.get("step_ap")
        if verified is None:
            verified = detect_step_ap(resolved)
        if verified != int(effective_ap):
            raise fail(
                "SAVE_FAILED",
                f"STEP protocol mismatch: requested AP{effective_ap}, detected {verified!r}",
                "Delete the file and retry; for AP242 require MBD PublishSTEP242File",
                step_ap_requested=effective_ap,
                step_ap_detected=verified,
            )
        export_path = str(backend_out.get("export_path") or (
            "PublishSTEP242File" if int(effective_ap) == 242 else "SaveAs3"
        ))
        out["step_ap"] = int(verified)
        out["export_path"] = export_path
        if write_meta:
            try:
                meta = write_step_meta(
                    resolved,
                    step_ap=int(verified),
                    step_ap_requested=int(effective_ap),
                    export_path=export_path,
                    properties=props,
                    source_path=source_path,
                    source_title=source_title,
                    configuration=configuration,
                    doc_type=doc_type,
                )
            except OSError as exc:
                raise fail(
                    "SAVE_FAILED",
                    f"STEP exported but sidecar write failed: {exc}",
                    f"STEP exists at {resolved}; fix permissions and rewrite meta, or set write_meta=false",
                ) from exc
            out["meta"] = str(meta)
    return out


def export_batch(
    ctx: OpContext,
    items: list,
    overwrite: bool = False,
) -> dict:
    """Serial open→export→close for a STEP/STL/PDF/DXF manifest; stop on first failure."""
    if ctx.dispatch is None:
        raise fail(
            "INTERNAL_ERROR",
            "export_batch dispatch not wired",
            "Server defect; start with a Kernel.dispatch wiring path",
            tool="export_batch",
        )
    if not isinstance(items, list) or not items:
        raise fail(
            "INVALID_ARGUMENT",
            "items must be a non-empty array",
            '[{"path":"a.sldprt","out":"a.step","step_ap":214}]',
        )
    results: list[dict] = []
    for i, raw in enumerate(items):
        if not isinstance(raw, dict):
            raise fail("INVALID_ARGUMENT", f"items[{i}] must be an object", "Include path and out")
        src = str(raw.get("path") or "").strip()
        out_path = str(raw.get("out") or "").strip()
        if not src or not out_path:
            raise fail(
                "INVALID_ARGUMENT",
                f"items[{i}] requires path and out",
                'e.g. {"path":"a.sldprt","out":"a.step"}',
            )
        step_ap = raw.get("step_ap")
        configuration = raw.get("configuration")
        entry: dict = {"path": src, "out": out_path, "ok": False}
        opened = False
        try:
            try:
                ensure_input_path(src, roots=ctx.workspace, extensions=_DOC_EXTS)
            except CadMcpError as exc:
                entry.update({
                    "error_code": exc.code,
                    "message": exc.message,
                    "hint": exc.hint or "",
                })
                results.append(entry)
                return {"ok": False, "count": len(results), "results": results}
            open_r = ctx.dispatch("open_document", {"path": src})
            if not open_r.ok:
                err = open_r.error
                entry.update({
                    "error_code": err.code if err else "OPEN_FAILED",
                    "message": err.message if err else "open_document failed",
                    "hint": err.hint if err else "",
                })
                results.append(entry)
                return {"ok": False, "count": len(results), "results": results}
            opened = True
            if configuration is not None and str(configuration).strip():
                cfg_r = ctx.dispatch(
                    "set_configuration",
                    {"name": str(configuration).strip(), "create": False},
                )
                if not cfg_r.ok:
                    err = cfg_r.error
                    entry.update({
                        "error_code": err.code if err else "FEATURE_NOT_FOUND",
                        "message": err.message if err else "set_configuration failed",
                        "hint": err.hint if err else "",
                    })
                    results.append(entry)
                    return {"ok": False, "count": len(results), "results": results}
            export_args: dict = {"path": out_path, "overwrite": bool(overwrite), "write_meta": True}
            if step_ap is not None:
                export_args["step_ap"] = int(step_ap)
            elif format_for_path(out_path) == "step":
                export_args["step_ap"] = STEP_AP_DEFAULT
            exp_r = ctx.dispatch("export", export_args)
            if not exp_r.ok:
                err = exp_r.error
                entry.update({
                    "error_code": err.code if err else "SAVE_FAILED",
                    "message": err.message if err else "export failed",
                    "hint": err.hint if err else "",
                })
                results.append(entry)
                return {"ok": False, "count": len(results), "results": results}
            res = exp_r.result or {}
            entry["ok"] = True
            entry["out"] = str(res.get("path") or out_path)
            if "step_ap" in res:
                entry["step_ap"] = res["step_ap"]
            if "export_path" in res:
                entry["export_path"] = res["export_path"]
            if "meta" in res:
                entry["meta"] = res["meta"]
            else:
                # Non-STEP exports have no meta
                p = Path(str(res.get("path") or out_path))
                if p.suffix.lower() in {".step", ".stp"}:
                    entry["meta"] = str(meta_path_for(p))
            results.append(entry)
        finally:
            if opened:
                ctx.dispatch("close_document", {"discard": True})
    return {"ok": True, "count": len(results), "results": results}


EXPORT_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="export",
        toolset="export",
        description=(
            "Export active doc by extension (.step/.stl part|asm; .pdf/.dxf drawing). "
            "step_ap=203|214|242 (default 214); write_meta writes *.step.meta.json."
        ),
        input_schema=make_schema(
            {
                "path": {"type": "string", "description": "Workspace-relative output path."},
                "overwrite": {"type": "boolean", "default": False},
                "step_ap": {
                    "type": "integer",
                    "enum": [203, 214, 242],
                    "description": "STEP AP; default 214. AP242 needs MBD.",
                },
                "stl_quality": {
                    "type": "string",
                    "enum": ["coarse", "fine"],
                    "description": "STL quality; .stl only.",
                },
                "write_meta": {
                    "type": "boolean",
                    "default": True,
                    "description": "STEP sidecar *.step.meta.json (ignored otherwise).",
                },
            },
            ["path"],
        ),
        handler=export_document,
        mutating=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="export_batch",
        toolset="export",
        description=(
            "Serial open→export→close manifest; stop on first failure. "
            "STEP defaults step_ap=214 and write_meta=true."
        ),
        input_schema=make_schema(
            {
                "items": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["path", "out"],
                        "properties": {
                            "path": {"type": "string", "description": "Workspace .sldprt/.sldasm."},
                            "out": {"type": "string", "description": "Export path."},
                            "step_ap": {"type": "integer", "enum": [203, 214, 242]},
                            "configuration": {"type": "string"},
                        },
                    },
                },
                "overwrite": {"type": "boolean", "default": False},
            },
            ["items"],
        ),
        handler=export_batch,
        mutating=True,
        timeout_class="slow",
    ),
]
