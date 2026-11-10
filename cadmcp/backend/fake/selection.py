"""Fake backend · selector domain（S8e-4）。

S8e-4: 8 methods + `_material_entities` inventory helper.

Dependencies (self, MRO):
- `_enter` / `_require_doc` / `_doc` / `gui_selection`（FakeBackend）

Imports:
- `cadmcp.backend.protocol.models`（EdgeRef / FaceRef）
- `cadmcp.selectors`（query_faces）
- `cadmcp.errors`（fail）
- `._state`（_Doc）
"""
from __future__ import annotations

from cadmcp.backend.protocol.models import EdgeRef, FaceRef, VertexRef
from cadmcp.errors import fail
from cadmcp.selectors import query_faces


class FakeSelectionMixin:
    """selector domain (S8e-4: 8 methods + 1 helper)."""

    def _init_state(self) -> None:
        pass  # State owned by FakeBackend._init_state

    # ---------- Entity inventory ----------

    def _material_entities(self) -> list[dict]:
        """Entity inventory from material features (sign>0); cuts/detail features do not add bodies (canned)."""
        doc = self._require_doc()
        return [x for x in doc.features if x["sign"] > 0]

    # ---------- Face/edge lists ----------

    def list_faces(self) -> list[FaceRef]:
        self._enter("list_faces")
        out: list[FaceRef] = []
        for f in self._material_entities():
            x0, y0, z0, x1, y1, z1 = f["bbox3d"]
            xc, yc, zc = (x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2
            if f.get("profile") == "circle":
                # Matches real cylinder extrude: 0 cylinder, 1 top, 2 bottom
                for kind, c, n, ax in (
                    ("cylinder", (xc, yc, zc), None, (0.0, 0.0, 1.0)),
                    ("plane", (xc, yc, z1), (0.0, 0.0, 1.0), None),
                    ("plane", (xc, yc, z0), (0.0, 0.0, -1.0), None),
                ):
                    out.append(FaceRef(index=len(out), kind=kind, centroid_m=c, normal_m=n, axis_m=ax))
                continue
            if f.get("kind") == "revolve" and f.get("has_cone"):
                # Tapered revolve: cone + two planes (canned, still 3 faces)
                for kind, c, n in (
                    ("cone", (xc, yc, zc), None),
                    ("plane", (xc, yc, z1), (0.0, 0.0, 1.0)),
                    ("plane", (xc, yc, z0), (0.0, 0.0, -1.0)),
                ):
                    out.append(FaceRef(index=len(out), kind=kind, centroid_m=c, normal_m=n))
                continue
            if f.get("profile") == "tube":
                # Matches real threaded tube sweep cut: plane, cylinder, plane, cylinder
                for kind, c, n, ax in (
                    ("plane", (xc, yc, z1), (0.0, 0.0, 1.0), None),
                    ("cylinder", (xc, yc, zc), None, (0.0, 0.0, 1.0)),
                    ("plane", (xc, yc, z0), (0.0, 0.0, -1.0), None),
                    ("cylinder", (xc, yc, zc), None, (0.0, 0.0, 1.0)),
                ):
                    out.append(FaceRef(index=len(out), kind=kind, centroid_m=c, normal_m=n, axis_m=ax))
                continue
            slots = (
                ((xc, yc, z0), (0.0, 0.0, -1.0)),
                ((xc, yc, z1), (0.0, 0.0, 1.0)),
                ((x0, yc, zc), (-1.0, 0.0, 0.0)),
                ((x1, yc, zc), (1.0, 0.0, 0.0)),
                ((xc, y0, zc), (0.0, -1.0, 0.0)),
                ((xc, y1, zc), (0.0, 1.0, 0.0)),
            )
            for c, n in slots[: min(f["faces"], 6)]:
                out.append(FaceRef(index=len(out), kind="plane", centroid_m=c, normal_m=n))
        return out

    def list_edges(self) -> list[EdgeRef]:
        self._enter("list_edges")
        out: list[EdgeRef] = []
        for f in self._material_entities():
            x0, y0, z0, x1, y1, z1 = f["bbox3d"]
            xc, yc, zc = (x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2
            if f.get("profile") == "circle":
                for c in ((xc, yc, z1), (xc, yc, z0)):
                    out.append(EdgeRef(index=len(out), kind="circle", midpoint_m=c))
                continue
            if f.get("profile") == "tube":
                for c in ((xc, yc, z1), (xc, yc, z0), (xc, yc, z1), (xc, yc, z0)):
                    out.append(EdgeRef(index=len(out), kind="circle", midpoint_m=c))
                continue
            slots = (
                (x0, y0, zc), (x0, y1, zc), (x1, y0, zc), (x1, y1, zc),  # vertical edges
                (xc, y0, z0), (xc, y1, z0), (x0, yc, z0), (x1, yc, z0),  # bottom edges
                (xc, y0, z1), (xc, y1, z1), (x0, yc, z1), (x1, yc, z1),  # top edges
            )
            for c in slots[: min(f["edges"], 12)]:
                out.append(EdgeRef(index=len(out), kind="line", midpoint_m=c))
        return out

    def list_vertices(self) -> list[VertexRef]:
        """Box 8 corners; high z first (matches 2025 box probe index 0 = top corner)。"""
        self._enter("list_vertices")
        out: list[VertexRef] = []
        for f in self._material_entities():
            x0, y0, z0, x1, y1, z1 = f["bbox3d"]
            corners = [
                (x0, y0, z1), (x0, y1, z1), (x1, y0, z1), (x1, y1, z1),
                (x0, y0, z0), (x0, y1, z0), (x1, y0, z0), (x1, y1, z0),
            ]
            for p in corners:
                out.append(VertexRef(index=len(out), position_m=p))
        return out

    def get_vertices(self) -> list[VertexRef]:
        return self.list_vertices()

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
        