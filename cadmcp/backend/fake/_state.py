"""Fake backend · state dataclasses + pure geometry helpers (S8a).

- `_Sketch` / `_Doc`: in-memory doc/sketch state (`__slots__`)
- `DENSITY_KG_M3` / `_CHAIN_TOL` / `_PARALLEL_TOL`: constants
- vectors: `_vadd` / `_vmul` / `_vdot` / `_vcross` / `_vnorm2` / `_vunit`
- arcs: `_arc_from_three_points` / `_arc_from_center`
- assembly snapshots: `_as_assembly_snap_item` / `_snap_bboxes` / `_union_boxes`

Pure functions preferred, no `self` (section 4.6).
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path

from cadmcp.backend.protocol.models import (
    BomRow,
    EdgeRef,
    FaceRef,
    MateInfo,
)
from cadmcp.errors import fail

DENSITY_KG_M3 = 1000.0  # Fake assumption: fixed density when no material assigned
_CHAIN_TOL = 1e-9
_PARALLEL_TOL = 1e-12


# ---------- Vector helpers ----------


def _vadd(*vecs: tuple[float, float, float]) -> tuple[float, float, float]:
    return tuple(sum(c) for c in zip(*vecs, strict=True))  # type: ignore[return-value]


def _vmul(vec: tuple[float, float, float], scale: float) -> tuple[float, float, float]:
    return (vec[0] * scale, vec[1] * scale, vec[2] * scale)


def _vdot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _vcross(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _vnorm2(vec: tuple[float, float, float]) -> float:
    return vec[0] * vec[0] + vec[1] * vec[1] + vec[2] * vec[2]


def _vunit(vec: tuple[float, float, float]) -> tuple[float, float, float]:
    n = math.sqrt(_vnorm2(vec))
    if n < 1e-15:
        return (0.0, 0.0, 0.0)
    return (vec[0] / n, vec[1] / n, vec[2] / n)


# ---------- Arcs ----------


def _arc_from_three_points(
    x1: float, y1: float, x2: float, y2: float, x3: float, y3: float
) -> dict:
    """Three-point arc: start, on-arc, end."""
    d = 2.0 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
    if abs(d) < 1e-18:
        raise fail(
            "SKETCH_OP_FAILED",
            "Three points are collinear; cannot define arc",
            "Provide non-collinear start, point on arc, and end",
        )
    cx = (
        (x1 * x1 + y1 * y1) * (y2 - y3)
        + (x2 * x2 + y2 * y2) * (y3 - y1)
        + (x3 * x3 + y3 * y3) * (y1 - y2)
    ) / d
    cy = (
        (x1 * x1 + y1 * y1) * (x3 - x2)
        + (x2 * x2 + y2 * y2) * (x1 - x3)
        + (x3 * x3 + y3 * y3) * (x2 - x1)
    ) / d
    r = math.hypot(x1 - cx, y1 - cy)
    if r <= 0:
        raise fail("SKETCH_OP_FAILED", "Arc radius is zero", "Three points cannot coincide")
    a0 = math.atan2(y1 - cy, x1 - cx)
    a_mid = math.atan2(y2 - cy, x2 - cx)
    a1 = math.atan2(y3 - cy, x3 - cx)
    mid = (a_mid - a0) % math.tau
    end = (a1 - a0) % math.tau
    sweep = end if mid <= end + 1e-12 else end - math.tau
    if abs(sweep) < 1e-12:
        raise fail("SKETCH_OP_FAILED", "Arc sweep angle is zero", "Start and end cannot coincide")
    return {
        "kind": "arc",
        "cx": cx, "cy": cy, "r": r,
        "x0": x1, "y0": y1, "x1": x3, "y1": y3,
        "sweep": sweep,
    }


def _arc_from_center(
    cx: float, cy: float, x1: float, y1: float, x2: float, y2: float, ccw: bool
) -> dict:
    r = math.hypot(x1 - cx, y1 - cy)
    r2 = math.hypot(x2 - cx, y2 - cy)
    if r <= 0 or abs(r2 - r) > 1e-9 * max(1.0, r):
        raise fail(
            "SKETCH_OP_FAILED",
            "In center mode, start and end must lie on the same radius",
            "Ensure start/end are the same positive distance from center",
        )
    a0 = math.atan2(y1 - cy, x1 - cx)
    a1 = math.atan2(y2 - cy, x2 - cx)
    da = (a1 - a0) % math.tau
    if da < 1e-12:
        da = math.tau
    sweep = da if ccw else da - math.tau
    return {
        "kind": "arc",
        "cx": cx, "cy": cy, "r": r,
        "x0": x1, "y0": y1, "x1": x2, "y1": y2,
        "sweep": sweep,
    }


# ---------- Assembly snapshot helpers ----------


def _as_assembly_snap_item(item: object) -> dict:
    if isinstance(item, dict):
        return item
    name, pth, mat, cfg = item[:4]  # type: ignore[index]
    return {"name": name, "path": pth, "material": mat, "config": cfg}


def _snap_bboxes(items: Sequence[dict]) -> list[tuple[float, ...]]:
    boxes: list[tuple[float, ...]] = []
    for item in items:
        box = item.get("bbox_m")
        if box is not None and len(box) == 6:
            boxes.append(tuple(box))
        boxes.extend(_snap_bboxes([_as_assembly_snap_item(c) for c in item.get("children") or []]))
    return boxes


def _union_boxes(boxes: Sequence[tuple[float, ...]]) -> tuple[float, ...]:
    if not boxes:
        return (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        min(b[2] for b in boxes),
        max(b[3] for b in boxes),
        max(b[4] for b in boxes),
        max(b[5] for b in boxes),
    )


# ---------- State dataclasses ----------


class _Sketch:
    __slots__ = ("plane", "name", "entities")

    def __init__(self, plane: str, name: str | None = None) -> None:
        self.plane = plane
        self.name = name
        self.entities: list[dict] = []


class _Doc:
    __slots__ = (
        "title", "path", "modified", "open_sketch", "pending_sketch", "ended_sketches",
        "features", "sketch_seq", "doc_type", "components", "instance_seq", "mates",
        "component_faces", "component_edges", "component_bbox", "component_origin",
        "component_local_bbox", "component_R", "component_local_faces", "component_local_edges",
        "nested_children", "nested_paths", "nested_local_origin", "nested_local_R",
        "component_lightweight",
        "color",
        "material", "config_names", "active_config",
        "drawing_views", "drawing_model", "bom_inserted", "component_material", "bom_rows",
        "drawing_paper", "drawing_scale", "drawing_tolerances", "drawing_annotations",
        "drawing_sheets", "drawing_active_sheet", "title_block", "drawing_datums", "drawing_gdts",
        "drawing_layers", "drawing_current_layer",
        "exploded_views", "exploded",
        "dimensions", "equations", "planes", "axes",
    )

    def __init__(self, title: str, path: Path | None = None, doc_type: str = "part") -> None:
        self.title = title
        self.doc_type = doc_type
        self.components: dict[str, str] = {}  # instance name -> part path (assembly only)
        self.instance_seq: dict[str, int] = {}  # file name -> inserted instance count
        self.mates: list[MateInfo] = []
        self.component_faces: dict[str, list[FaceRef]] = {}  # instance name -> face list saved with part
        self.component_edges: dict[str, list[EdgeRef]] = {}  # instance name -> edge list saved with part
        self.component_bbox: dict[str, tuple[float, ...]] = {}  # instance name -> assembly-space bbox
        self.component_origin: dict[str, tuple[float, float, float]] = {}
        self.component_local_bbox: dict[str, tuple[float, ...]] = {}
        self.component_R: dict[str, tuple] = {}
        self.component_local_faces: dict[str, list[FaceRef]] = {}
        self.component_local_edges: dict[str, list[EdgeRef]] = {}
        self.nested_children: dict[str, list[str]] = {}
        self.nested_paths: dict[str, str] = {}
        self.nested_local_origin: dict[str, tuple[float, float, float]] = {}
        self.nested_local_R: dict[str, tuple] = {}
        self.component_lightweight: set[str] = set()
        self.color: tuple[float, float, float] | None = None
        self.material = ""
        self.config_names: list[str] = ["Default"]
        self.active_config = "Default"
        self.drawing_views: list[str] = []
        self.drawing_paper: str = "A4"
        self.drawing_scale: tuple[float, float] = (1.0, 1.0)
        self.drawing_tolerances: list[dict] = []
        self.drawing_annotations: int = 0
        self.drawing_sheets: list[dict] = [
            {"name": "Sheet1", "paper": "A4", "scale": [1.0, 1.0], "views": []}
        ]
        self.drawing_active_sheet: str = "Sheet1"
        self.title_block: dict[str, str] = {}
        self.drawing_datums: list[dict] = []
        self.drawing_gdts: list[dict] = []
        self.drawing_layers: list[dict] = [{"name": "0", "color": 0}]
        self.drawing_current_layer: str = "0"
        self.exploded_views: list[str] = []
        self.exploded = False
        self.drawing_model: str | None = None
        self.bom_inserted = False
        self.component_material: dict[str, str] = {}
        self.bom_rows: list[BomRow] = []
        self.dimensions: dict[str, dict] = {}
        self.equations: list[dict[str, str]] = []
        self.planes: list[dict] = []
        self.axes: list[dict] = []
        self.path = str(path) if path else None
        self.modified = False
        self.open_sketch: _Sketch | None = None
        self.pending_sketch: _Sketch | None = None  # profile from the latest end_sketch
        # sketches consumed by features removed here; sweep needs two latest sketches (profile + path)
        self.ended_sketches: list[_Sketch] = []
        self.features: list[dict] = []  # {name, kind, profile, area, perimeter, depth, bbox2d, faces, edges}
        self.sketch_seq = 0
        