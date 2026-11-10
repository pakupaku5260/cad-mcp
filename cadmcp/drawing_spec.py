"""DrawingSpec (DRW3 L2/L3): declarative drawing JSON.

L1 uses existing fine-grained tools; this module parses/validates spec only.
L3: sheets / title_block / gdts (see docs/drw3-l3-plan.md).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cadmcp.backend.protocol.constants import GDT_SYMBOLS
from cadmcp.errors import fail

_PAPER = {"A4", "A3", "A2", "A1", "A0"}
_VIEWS = {"front", "back", "left", "right", "top", "bottom", "isometric"}


def _parse_scale(scale: Any, where: str) -> list[float]:
    if (
        not isinstance(scale, list)
        or len(scale) != 2
        or not all(isinstance(x, (int, float)) and float(x) > 0 for x in scale)
    ):
        raise fail("INVALID_ARGUMENT", f"{where} must be positive [num, den]", "e.g. [1, 2]")
    return [float(scale[0]), float(scale[1])]


def _parse_paper(paper: Any, where: str) -> str:
    paper_u = str(paper if paper is not None else "A4").strip().upper()
    if paper_u not in _PAPER:
        raise fail("INVALID_ARGUMENT", f"{where} unknown paper {paper_u!r}", f"Choose: {', '.join(sorted(_PAPER))}")
    return paper_u


def _parse_views(views: Any, where: str) -> list[dict[str, Any]]:
    if not isinstance(views, list) or not views:
        raise fail("INVALID_ARGUMENT", f"{where} must be a non-empty array", 'e.g. [{"orient":"front"}]')
    out: list[dict[str, Any]] = []
    for i, view in enumerate(views):
        if not isinstance(view, dict):
            raise fail("INVALID_ARGUMENT", f"{where}[{i}] must be an object", "Include orient")
        orient = str(view.get("orient", "")).strip().lower()
        if orient not in _VIEWS:
            raise fail(
                "INVALID_ARGUMENT",
                f"Unknown view {orient!r}",
                f"Choose: {', '.join(sorted(_VIEWS))}",
            )
        item = dict(view)
        item["orient"] = orient
        out.append(item)
    return out


def load_drawing_spec(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise fail("PATH_NOT_FOUND", f"DrawingSpec not found: {path}", "Ensure path is in workspace")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise fail("INVALID_ARGUMENT", f"Invalid DrawingSpec JSON: {exc}", "Check JSON syntax") from exc
    if not isinstance(data, dict):
        raise fail("INVALID_ARGUMENT", "DrawingSpec root must be an object", "See docs/drw3-l3-plan.md")
    model = data.get("model")
    if not isinstance(model, str) or not model.strip():
        raise fail("INVALID_ARGUMENT", "Missing model path", "spec.model must point to a saved .sldprt/.sldasm")

    sheets_raw = data.get("sheets")
    if sheets_raw is not None:
        if not isinstance(sheets_raw, list) or not sheets_raw:
            raise fail("INVALID_ARGUMENT", "sheets must be a non-empty array", "Each item has name/views")
        sheets: list[dict[str, Any]] = []
        for i, sh in enumerate(sheets_raw):
            if not isinstance(sh, dict):
                raise fail("INVALID_ARGUMENT", f"sheets[{i}] must be an object", "Include name and views")
            name = str(sh.get("name") or f"Sheet{i + 1}").strip()
            if not name:
                raise fail("INVALID_ARGUMENT", f"sheets[{i}].name must not be empty", "e.g. Sheet1")
            sheets.append(
                {
                    "name": name,
                    "paper": _parse_paper(sh.get("paper", "A4"), f"sheets[{i}].paper"),
                    "scale": _parse_scale(sh.get("scale", [1, 1]), f"sheets[{i}].scale"),
                    "views": _parse_views(sh.get("views"), f"sheets[{i}].views"),
                }
            )
        data["sheets"] = sheets
        # L2 compat: top-level fields from first sheet
        data["paper"] = sheets[0]["paper"]
        data["scale"] = sheets[0]["scale"]
        data["views"] = sheets[0]["views"]
    else:
        data["views"] = _parse_views(data.get("views"), "views")
        data["paper"] = _parse_paper(data.get("paper", "A4"), "paper")
        data["scale"] = _parse_scale(data.get("scale", [1, 1]), "scale")

    if "section" in data and data["section"] is not None and not isinstance(data["section"], dict):
        raise fail("INVALID_ARGUMENT", "section must be an object or omitted", 'e.g. {"label":"A"}')
    if "detail" in data and data["detail"] is not None and not isinstance(data["detail"], dict):
        raise fail("INVALID_ARGUMENT", "detail must be an object or omitted", 'e.g. {"label":"B","x":0,"y":0,"radius":10}')
    tols = data.get("tolerances") or []
    if not isinstance(tols, list):
        raise fail("INVALID_ARGUMENT", "tolerances must be an array", "Each item has dimension + type/values")

    title = data.get("title_block")
    if title is not None:
        if not isinstance(title, dict):
            raise fail("INVALID_ARGUMENT", "title_block must be an object", '{"PartNo":"P-001",...}')
        cleaned = {str(k).strip(): str(v) for k, v in title.items() if str(k).strip()}
        data["title_block"] = cleaned

    gdts = data.get("gdts")
    if gdts is not None:
        if not isinstance(gdts, list):
            raise fail("INVALID_ARGUMENT", "gdts must be an array", "Each item kind=datum|gdt")
        parsed: list[dict[str, Any]] = []
        for i, item in enumerate(gdts):
            if not isinstance(item, dict):
                raise fail("INVALID_ARGUMENT", f"gdts[{i}] must be an object", "Include kind")
            kind = str(item.get("kind", "")).strip().lower()
            if kind == "datum":
                label = str(item.get("label") or "").strip()
                if not label:
                    raise fail("INVALID_ARGUMENT", f"gdts[{i}].label must not be empty", "e.g. A")
                edge = item.get("edge")
                if edge is not None and (not isinstance(edge, int) or int(edge) < 0):
                    raise fail("INVALID_ARGUMENT", f"gdts[{i}].edge must be int >= 0", "Omit to auto-pick edge")
                parsed.append(
                    {
                        "kind": "datum",
                        "label": label,
                        "x": float(item.get("x", 100)),
                        "y": float(item.get("y", 80)),
                        "edge": None if edge is None else int(edge),
                    }
                )
            elif kind == "gdt":
                symbol = str(item.get("symbol") or "").strip().lower()
                if symbol not in GDT_SYMBOLS:
                    raise fail(
                        "INVALID_ARGUMENT",
                        f"gdts[{i}] unknown symbol {symbol!r}",
                        f"Choose: {', '.join(GDT_SYMBOLS)}",
                    )
                tol = str(item.get("tolerance") or "").strip()
                if not tol:
                    raise fail("INVALID_ARGUMENT", f"gdts[{i}].tolerance must not be empty", "e.g. 0.1")
                refs = item.get("datums") or []
                if not isinstance(refs, list):
                    raise fail("INVALID_ARGUMENT", f"gdts[{i}].datums must be an array", 'e.g. ["A"]')
                edge = item.get("edge")
                if edge is not None and (not isinstance(edge, int) or int(edge) < 0):
                    raise fail("INVALID_ARGUMENT", f"gdts[{i}].edge must be int >= 0", "Omit to auto-pick edge")
                parsed.append(
                    {
                        "kind": "gdt",
                        "symbol": symbol,
                        "tolerance": tol,
                        "datums": [str(d).strip() for d in refs if str(d).strip()],
                        "x": float(item.get("x", 120)),
                        "y": float(item.get("y", 60)),
                        "edge": None if edge is None else int(edge),
                    }
                )
            else:
                raise fail("INVALID_ARGUMENT", f"gdts[{i}].kind must be datum or gdt", f"got {kind!r}")
        data["gdts"] = parsed

    out_pdf = data.get("output_pdf")
    if out_pdf is not None and not isinstance(out_pdf, str):
        raise fail("INVALID_ARGUMENT", "output_pdf must be a string path", "Relative to workspace")
    data.setdefault("import_dimensions", True)
    return data


__all__ = ["load_drawing_spec"]
