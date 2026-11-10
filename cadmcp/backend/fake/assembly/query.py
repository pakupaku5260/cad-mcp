"""Fake backend · assembly domain · assembly query（S8h）。

S8h: list_component_faces / list_component_edges / check_interference (3 methods).

Dependencies (self, MRO):
- `_enter` / `_require_doc` / `_doc`（FakeBackend）
- `_require_assembly`（FakeAssemblyComponentMixin，S8f）

Imports:
- `cadmcp.backend.protocol.models`（EdgeRef / FaceRef / InterferencePair）
- `cadmcp.selectors`（filter_by_kind / FACE_FILTER_KINDS / EDGE_FILTER_KINDS /
  interference_component_pairs / aabb_pair_status）
- `cadmcp.errors`（fail）
"""
from __future__ import annotations

from cadmcp.backend.protocol.geometry_engine import aabb_pair_status
from cadmcp.backend.protocol.models import (
    EdgeRef,
    FaceRef,
    InterferencePair,
)
from cadmcp.backend.protocol.parsers import interference_component_pairs
from cadmcp.errors import fail
from cadmcp.selectors import (
    EDGE_FILTER_KINDS,
    FACE_FILTER_KINDS,
    filter_by_kind,
)


class FakeAssemblyQueryMixin:
    """assembly query (S8h: 3 methods)."""

    def _init_state(self) -> None:
        pass  # State owned by FakeBackend._init_state

    def list_component_faces(
        self, component: str, kind: str | None = None
    ) -> list[FaceRef]:
        self._enter("list_component_faces", component=component, kind=kind)
        doc = self._require_assembly("Create an assembly with new_assembly, then list component faces")
        if component not in doc.components:
            raise fail(
                "INVALID_ARGUMENT",
                f"Component not found: {component!r}",
                "Instance name comes from insert_component, e.g. p1-1",
                component=component,
            )
        return filter_by_kind(
            doc.component_faces.get(component, []), kind, allowed=FACE_FILTER_KINDS, what="face"
        )

    def list_component_edges(
        self, component: str, kind: str | None = None
    ) -> list[EdgeRef]:
        self._enter("list_component_edges", component=component, kind=kind)
        doc = self._require_assembly("Create an assembly with new_assembly, then list component edges")
        if component not in doc.components:
            raise fail(
                "INVALID_ARGUMENT",
                f"Component not found: {component!r}",
                "Instance name comes from insert_component, e.g. p1-1",
                component=component,
            )
        return filter_by_kind(
            doc.component_edges.get(component, []), kind, allowed=EDGE_FILTER_KINDS, what="edge"
        )

    def check_interference(
        self,
        component1: str | None = None,
        component2: str | None = None,
        coincident_as_interference: bool = False,
    ) -> tuple[list[InterferencePair], str]:
        self._enter(
            "check_interference",
            component1=component1,
            component2=component2,
            coincident_as_interference=coincident_as_interference,
        )
        doc = self._require_assembly("Create an assembly with new_assembly, then check interference")
        pairs_out: list[InterferencePair] = []
        for a, b in interference_component_pairs(list(doc.components), component1, component2):
            box_a = doc.component_bbox.get(a)
            box_b = doc.component_bbox.get(b)
            if box_a is None or box_b is None:
                pairs_out.append(InterferencePair(a=a, b=b, status="unknown"))
                continue
            status = aabb_pair_status(
                tuple(box_a), tuple(box_b), coincident_as_interference=coincident_as_interference
            )
            if status == "clear":
                continue
            pairs_out.append(InterferencePair(a=a, b=b, status=status))
        return pairs_out, "aabb"
