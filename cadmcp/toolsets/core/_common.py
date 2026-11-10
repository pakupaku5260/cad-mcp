"""Shared constants and helpers for the core toolset."""
from __future__ import annotations

from cadmcp.backend.protocol.models import DocInfo, FaceRef
from cadmcp.kernel import OpContext
from cadmcp.units import SUPPORTED_UNITS, UnitContext

PNG_EXTS = frozenset({"png", "jpg", "jpeg"})
_DOC_EXTS = frozenset({"sldprt", "sldasm", "slddrw"})

_UNIT_ENUM = sorted(SUPPORTED_UNITS)
_UNIT_PROP = {"type": "string", "enum": _UNIT_ENUM, "default": "mm"}


def _unit_ctx(ctx: OpContext, unit: str) -> UnitContext:
    """Unit context for this call (invalid units raise UNIT_UNSUPPORTED)."""
    return ctx.units if unit == ctx.units.external_unit else UnitContext(unit)


def _public_face(face: FaceRef, u: UnitContext) -> dict:
    item = {
        "index": face.index,
        "kind": face.kind,
        "centroid": list(u.tuple_from_m(face.centroid_m)),
    }
    if face.normal_m is not None:
        item["normal"] = [float(v) for v in face.normal_m]
    return item


def _doc_payload(info: DocInfo) -> dict:
    return {
        "title": info.title,
        "path": info.path,
        "doc_type": info.doc_type,
        "modified": info.modified,
        "units": info.units,
    }

