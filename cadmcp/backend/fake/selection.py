"""Fake backend · selector domain (S8e-4 + F1.3 persist-ref signatures).

Dependencies (self, MRO):
- `_enter` / `_require_doc` / `_doc` / `gui_selection` (FakeBackend)

ref_id is a deterministic geometric signature prefixed with ``fake:`` (32 hex chars).
It is recomputed from current state on every list call and is never cached, so model
edits that change geometry invalidate previously issued refs (reverse lookup returns
None). Quantization uses ``round(x, n)`` as required by the F1.3 card.
"""
from __future__ import annotations

import hashlib
import math
from typing import Any

from cadmcp.backend.protocol.models import EdgeRef, FaceRef, VertexRef
from cadmcp.errors import fail
from cadmcp.selectors import query_faces


def _q(value: float, digits: int) -> float:
    return round(float(value), digits)


def _model_rev(doc: Any) -> str:
    """Deterministic digest of feature-tree state (recomputed, not cached).

    Included so topology-changing ops (e.g. fillet/detail features, deletes) invalidate
    issued refs even when the originating material feature's bbox/centroid fields are
    unchanged in this simplified fake model.
    """
    feats = getattr(doc, "features", []) or []
    parts = []
    for f in feats:
        parts.append(
            f"{f.get('name')}|{f.get('kind')}|{f.get('sign')}|"
            f"{f.get('bbox3d')}|{f.get('faces')}|{f.get('edges')}"
        )
    payload = "||".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _bbox_dims(feature: dict[str, Any]) -> tuple[float, float, float]:
    x0, y0, z0, x1, y1, z1 = feature["bbox3d"]
    return (abs(x1 - x0), abs(y1 - y0), abs(z1 - z0))


def _face_area(feature: dict[str, Any], kind: str) -> float:
    dx, dy, dz = _bbox_dims(feature)
    if kind == "cylinder":
        radius = max(dx, dy) / 2.0
        return math.pi * 2.0 * radius * dz
    if kind == "cone":
        radius = max(dx, dy) / 2.0
        slant = math.hypot(radius, dz)
        return math.pi * radius * slant
    if kind == "plane":
        dims = sorted([dx, dy, dz], reverse=True)
        return dims[0] * dims[1]
    return dx * dy


def _edge_length(feature: dict[str, Any], kind: str) -> float:
    dx, dy, dz = _bbox_dims(feature)
    if kind == "circle":
        radius = max(dx, dy) / 2.0
        return math.pi * 2.0 * radius
    return max(dx, dy, dz)


def _face_sig(
    kind: str,
    centroid_m: tuple[float, float, float],
    normal_m: tuple[float, float, float] | None,
    area: float,
    rev: str,
) -> str:
    cx, cy, cz = (_q(centroid_m[0], 5), _q(centroid_m[1], 5), _q(centroid_m[2], 5))
    if normal_m is None:
        nx = ny = nz = 0.0
    else:
        nx, ny, nz = (_q(normal_m[0], 3), _q(normal_m[1], 3), _q(normal_m[2], 3))
    payload = f"face|{kind}|{cx},{cy},{cz}|{nx},{ny},{nz}|{_q(area, 9)}|{rev}"
    return "fake:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _edge_sig(kind: str, midpoint_m: tuple[float, float, float], length: float, rev: str) -> str:
    mx, my, mz = (_q(midpoint_m[0], 5), _q(midpoint_m[1], 5), _q(midpoint_m[2], 5))
    payload = f"edge|{kind}|{mx},{my},{mz}|{_q(length, 6)}|{rev}"
    return "fake:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _vertex_sig(position_m: tuple[float, float, float], rev: str) -> str:
    px, py, pz = (_q(position_m[0], 5), _q(position_m[1], 5), _q(position_m[2], 5))
    payload = f"vertex|{px},{py},{pz}|{rev}"
    return "fake:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


class FakeSelectionMixin:
    """Selector domain (S8e-4 methods + F1.3 persist refs)."""

    def _init_state(self) -> None:
        pass  # State owned by FakeBackend._init_state

    # ---------- Entity inventory ----------

    def _material_entities(self) -> list[dict]:
        """Entity inventory from material features (sign>0); cuts/detail features do not add bodies (canned)."""
        doc = self._require_doc()
        return [x for x in doc.features if x["sign"] > 0]

    def _face_entries(self) -> list[tuple[FaceRef, dict[str, Any]]]:
        out: list[tuple[FaceRef, dict[str, Any]]] = []
        rev = _model_rev(self._require_doc())
        for f in self._material_entities():
            x0, y0, z0, x1, y1, z1 = f["bbox3d"]
            xc, yc, zc = (x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2
            if f.get("profile") == "circle":
                specs = [
                    ("cylinder", (xc, yc, zc), None, (0.0, 0.0, 1.0)),
                    ("plane", (xc, yc, z1), (0.0, 0.0, 1.0), None),
                    ("plane", (xc, yc, z0), (0.0, 0.0, -1.0), None),
                ]
            elif f.get("kind") == "revolve" and f.get("has_cone"):
                specs = [
                    ("cone", (xc, yc, zc), None, None),
                    ("plane", (xc, yc, z1), (0.0, 0.0, 1.0), None),
                    ("plane", (xc, yc, z0), (0.0, 0.0, -1.0), None),
                ]
            elif f.get("profile") == "tube":
                specs = [
                    ("plane", (xc, yc, z1), (0.0, 0.0, 1.0), None),
                    ("cylinder", (xc, yc, zc), None, (0.0, 0.0, 1.0)),
                    ("plane", (xc, yc, z0), (0.0, 0.0, -1.0), None),
                    ("cylinder", (xc, yc, zc), None, (0.0, 0.0, 1.0)),
                ]
            else:
                slots = (
                    ("plane", (xc, yc, z0), (0.0, 0.0, -1.0), None),
                    ("plane", (xc, yc, z1), (0.0, 0.0, 1.0), None),
                    ("plane", (x0, yc, zc), (-1.0, 0.0, 0.0), None),
                    ("plane", (x1, yc, zc), (1.0, 0.0, 0.0), None),
                    ("plane", (xc, y0, zc), (0.0, -1.0, 0.0), None),
                    ("plane", (xc, y1, zc), (0.0, 1.0, 0.0), None),
                )
                specs = list(slots[: min(int(f.get("faces", 6)), 6)])
            for kind, c, n, ax in specs:
                ref = FaceRef(
                    index=len(out),
                    kind=kind,
                    centroid_m=c,
                    normal_m=n,
                    axis_m=ax,
                    ref_id=_face_sig(kind, c, n, _face_area(f, kind), rev),
                )
                out.append((ref, f))
        return out

    def _edge_entries(self) -> list[tuple[EdgeRef, dict[str, Any]]]:
        out: list[tuple[EdgeRef, dict[str, Any]]] = []
        rev = _model_rev(self._require_doc())
        for f in self._material_entities():
            x0, y0, z0, x1, y1, z1 = f["bbox3d"]
            xc, yc, zc = (x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2
            if f.get("profile") == "circle":
                specs = [("circle", (xc, yc, z1)), ("circle", (xc, yc, z0))]
            elif f.get("profile") == "tube":
                specs = [
                    ("circle", (xc, yc, z1)),
                    ("circle", (xc, yc, z0)),
                    ("circle", (xc, yc, z1)),
                    ("circle", (xc, yc, z0)),
                ]
            else:
                slots = (
                    ("line", (x0, y0, zc)),
                    ("line", (x0, y1, zc)),
                    ("line", (x1, y0, zc)),
                    ("line", (x1, y1, zc)),
                    ("line", (xc, y0, z0)),
                    ("line", (xc, y1, z0)),
                    ("line", (x0, yc, z0)),
                    ("line", (x1, yc, z0)),
                    ("line", (xc, y0, z1)),
                    ("line", (xc, y1, z1)),
                    ("line", (x0, yc, z1)),
                    ("line", (x1, yc, z1)),
                )
                specs = list(slots[: min(int(f.get("edges", 12)), 12)])
            for kind, c in specs:
                ref = EdgeRef(
                    index=len(out),
                    kind=kind,
                    midpoint_m=c,
                    ref_id=_edge_sig(kind, c, _edge_length(f, kind), rev),
                )
                out.append((ref, f))
        return out

    def _vertex_entries(self) -> list[tuple[VertexRef, dict[str, Any]]]:
        out: list[tuple[VertexRef, dict[str, Any]]] = []
        rev = _model_rev(self._require_doc())
        for f in self._material_entities():
            x0, y0, z0, x1, y1, z1 = f["bbox3d"]
            corners = [
                (x0, y0, z1), (x0, y1, z1), (x1, y0, z1), (x1, y1, z1),
                (x0, y0, z0), (x0, y1, z0), (x1, y0, z0), (x1, y1, z0),
            ]
            for p in corners:
                out.append((VertexRef(index=len(out), position_m=p, ref_id=_vertex_sig(p, rev)), f))
        return out

    # ---------- Face/edge lists ----------

    def list_faces(self) -> list[FaceRef]:
        self._enter("list_faces")
        return [ref for ref, _ in self._face_entries()]

    def list_edges(self) -> list[EdgeRef]:
        self._enter("list_edges")
        return [ref for ref, _ in self._edge_entries()]

    def list_vertices(self) -> list[VertexRef]:
        """Box 8 corners; high z first (matches 2025 box probe index 0 = top corner)."""
        self._enter("list_vertices")
        return [ref for ref, _ in self._vertex_entries()]

    def get_vertices(self) -> list[VertexRef]:
        return self.list_vertices()

    # ---------- ref_id resolution (F1.3) ----------

    def _face_by_persist_ref(self, ref_id: str) -> FaceRef | None:
        if not ref_id or not isinstance(ref_id, str):
            return None
        for ref, _ in self._face_entries():
            if ref.ref_id == ref_id:
                return ref
        return None

    def _edge_by_persist_ref(self, ref_id: str) -> EdgeRef | None:
        if not ref_id or not isinstance(ref_id, str):
            return None
        for ref, _ in self._edge_entries():
            if ref.ref_id == ref_id:
                return ref
        return None

    def _vertex_by_persist_ref(self, ref_id: str) -> VertexRef | None:
        if not ref_id or not isinstance(ref_id, str):
            return None
        for ref, _ in self._vertex_entries():
            if ref.ref_id == ref_id:
                return ref
        return None

    # ---------- GUI picking ----------

    def selected_entities(self) -> list[FaceRef | EdgeRef]:
        self._enter("selected_entities")
        self._require_doc()
        return list(self.gui_selection)

    # ---------- select_face / select_edge (GUI inject + validate) ----------

    def select_face(self, index: int) -> None:
        self._enter("select_face", index=index)
        self._require_doc()
        faces = self.list_faces()
        if not faces:
            raise fail("REF_NOT_FOUND", "No selectable faces in the document", "Create a solid with extrude first")
        if index < 0 or index >= len(faces):
            raise fail("INVALID_ARGUMENT", f"Face index out of range: {index}", f"Valid range 0..{len(faces) - 1}")

    def select_edge(self, index: int) -> None:
        self._enter("select_edge", index=index)
        self._require_doc()
        edges = self.list_edges()
        if not edges:
            raise fail("REF_NOT_FOUND", "No selectable edges in the document", "Create a solid with extrude first")
        if index < 0 or index >= len(edges):
            raise fail("INVALID_ARGUMENT", f"Edge index out of range: {index}", f"Valid range 0..{len(edges) - 1}")

    # ---------- Query wrappers ----------

    def get_faces(self, kind: str | None = None, query: str | None = None) -> list[FaceRef]:
        self._enter("get_faces", kind=kind, query=query)
        return query_faces(self.list_faces(), kind, query)

    def get_edges(self) -> list[EdgeRef]:
        self._enter("get_edges")
        return self.list_edges()
