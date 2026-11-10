"""Fake backend · assembly domain · mates (S8g).

S8g: 22 methods + 3 constant groups (mate logic) + 6 vector helpers **imported from `_engine` pure functions**.

Dependencies (self, MRO):
- `_enter` / `_require_doc` / `_doc`（FakeBackend）
- `_require_assembly` / `_component_ref` / `_translate_component` /
  `_sync_component_world`（FakeAssemblyComponentMixin，S8f）

Imports:
- `cadmcp.backend.protocol.geometry_math`（apply_matrix3 / matmul3）
- `cadmcp.backend.protocol.models`（MateInfo）
- `cadmcp.backend.protocol.parsers`（canonical_plane / mate_need_hint /
  parse_mate_pair / resolve_mate_align）
- `cadmcp.selectors`（resolve_mate_index）
- `cadmcp.errors`（fail）
- `.._engine` (6 pure vector helpers — not redefined here)
- `.._state` (_Doc, type hints only)

Section 4.6: `_vec_len` / `_vec_unit` / `_vec_dot` / `_vec_cross` / `_rodrigues` /
`_rotation_aligning` live in `_engine.py`; this file must **not** redefine method versions,
always `from .._engine import` and call directly.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from cadmcp.backend.protocol.geometry_math import apply_matrix3, matmul3
from cadmcp.backend.protocol.models import MateInfo
from cadmcp.backend.protocol.parsers import (
    canonical_plane,
    component_name_keys,
    mate_need_hint,
    parse_mate_pair,
    resolve_mate_align,
)
from cadmcp.errors import fail
from cadmcp.selectors import resolve_mate_index

from .._engine import (
    _rotation_aligning,
    _vec_dot,
    _vec_unit,
)

if TYPE_CHECKING:
    from .._state import _Doc

from cadmcp.backend.protocol.constants import MAT_IDENTITY
from cadmcp.backend.protocol.models import EdgeRef, FaceRef


class FakeAssemblyMateMixin:
    """Mate domain (S8g: 22 methods + 3 constant groups)."""

    _PLANE_NORMAL_LOCAL = {
        "Front Plane": (0.0, 0.0, 1.0),
        "Top Plane": (0.0, 1.0, 0.0),
        "Right Plane": (1.0, 0.0, 0.0),
    }

    _PLANE_MATES = frozenset({"coincident", "distance", "angle"})

    _MATE_LABELS = {
        "concentric": ("Concentric", "Concentric"),
        "coincident": ("Coincident", "Coincident"),
        "distance": ("Distance", "Distance"),
        "angle": ("Angle", "Angle"),
        "tangent": ("Tangent", "Tangent"),
        "screw": ("Screw", "Screw"),
    }

    def _init_state(self) -> None:
        pass  # State owned by FakeBackend._init_state

    # ---------- Face/edge materialize ----------

    @staticmethod
    def _offset_library(
        faces: list, edges: list, x_m: float, y_m: float, z_m: float
    ) -> tuple[list, list]:
        if x_m == 0.0 and y_m == 0.0 and z_m == 0.0:
            return list(faces), list(edges)

        shifted_faces = [
            FaceRef(
                index=f.index,
                kind=f.kind,
                centroid_m=(f.centroid_m[0] + x_m, f.centroid_m[1] + y_m, f.centroid_m[2] + z_m),
                normal_m=f.normal_m,
            )
            for f in faces
        ]
        shifted_edges = [
            EdgeRef(
                index=e.index,
                kind=e.kind,
                midpoint_m=(e.midpoint_m[0] + x_m, e.midpoint_m[1] + y_m, e.midpoint_m[2] + z_m),
            )
            for e in edges
        ]
        return shifted_faces, shifted_edges

    def _face_kind(self, doc: _Doc, ref) -> str:
        faces = doc.component_faces.get(ref.component, [])
        idx = resolve_mate_index(
            int(ref.face_index),
            ref.coord_m,
            faces,
            component=ref.component,
            kind="face",
            filter_kind=ref.filter_kind,
        )
        return faces[idx].kind

    def _edge_kind(self, doc: _Doc, ref) -> str:
        edges = doc.component_edges.get(ref.component, [])
        idx = resolve_mate_index(
            int(ref.edge_index),
            ref.coord_m,
            edges,
            component=ref.component,
            kind="edge",
            filter_kind=ref.filter_kind,
        )
        return edges[idx].kind

    # ---------- Mate common path ----------

    def _mate(
        self, mate_type: str, entity1: str, entity2: str, align: str | None = None
    ) -> MateInfo:
        """Mate common path: check order matches com_backend._mate_common (isomorphic errors)."""
        doc = self._require_assembly("Create an assembly with new_assembly, then add mates")
        ref1, ref2 = parse_mate_pair(entity1, entity2)
        resolve_mate_align(align, mate_type)
        known = set(doc.components) | set(doc.nested_paths)
        missing = [
            c for c in (ref1.component, ref2.component)
            if c not in known and not any(
                component_name_keys(c) & component_name_keys(k) for k in known
            )
        ]
        if missing:
            raise fail(
                "INVALID_ARGUMENT",
                f"Could not select mate entities ({entity1!r} / {entity2!r}): Component not found: {', '.join(missing)}",
                "Component instance from insert_component; face/edge indexes from get_component_faces / get_component_edges",
            )
        prefix, label = self._MATE_LABELS[mate_type]
        kinds = []
        for ref in (ref1, ref2):
            if ref.kind == "plane":
                kinds.append("plane")
            elif ref.kind == "edge":
                kinds.append(self._edge_kind(doc, ref))
            else:
                kinds.append(self._face_kind(doc, ref))
        if mate_type in ("concentric", "screw"):
            allowed = kinds in (["cylinder", "cylinder"], ["circle", "circle"])
        elif mate_type == "coincident":
            allowed = kinds in (["plane", "plane"], ["circle", "circle"])
        else:
            allowed = kinds == ["plane", "plane"] and mate_type in self._PLANE_MATES
        if not allowed:
            raise fail(
                "FEATURE_CREATE_FAILED",
                f"Failed to create {label} mate (status code 2)",
                mate_need_hint(mate_type, kinds),
            )
        n = sum(1 for m in doc.mates if m.mate_type == mate_type) + 1
        info = MateInfo(
            name=f"{prefix}{n}",
            mate_type=mate_type,
            components=(ref1.component, ref2.component),
        )
        doc.mates.append(info)
        self._solve_mate(doc, mate_type, ref1, ref2, align)
        doc.modified = True
        return info

    # ---------- Grounded/movable check ----------

    def _grounded_component(self, doc: _Doc) -> str | None:
        names = list(doc.components)
        return names[0] if names else None

    def _movable_of_pair(self, doc: _Doc, c1: str, c2: str) -> str:
        grounded = self._grounded_component(doc)
        if c1 == grounded and c2 != grounded:
            return c2
        if c2 == grounded and c1 != grounded:
            return c1
        names = list(doc.components)
        return c2 if names.index(c2) >= names.index(c1) else c1

    # ---------- Rigid transform ----------

    def _apply_rigid(
        self,
        doc: _Doc,
        name: str,
        rot: tuple,
        pivot: tuple[float, float, float],
    ) -> None:

        if rot == MAT_IDENTITY:
            return
        R = doc.component_R.get(name, MAT_IDENTITY)
        origin = doc.component_origin.get(name, (0.0, 0.0, 0.0))
        rel = (origin[0] - pivot[0], origin[1] - pivot[1], origin[2] - pivot[2])
        doc.component_R[name] = matmul3(rot, R)
        spun = apply_matrix3(rot, rel)
        doc.component_origin[name] = (
            pivot[0] + spun[0], pivot[1] + spun[1], pivot[2] + spun[2]
        )
        self._sync_component_world(doc, name)

    # ---------- Solid plane/axis ----------

    def _entity_plane(
        self, doc: _Doc, ref
    ) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
        if ref.kind == "plane":
            canon = canonical_plane(ref.plane or "") or (ref.plane or "")
            local = self._PLANE_NORMAL_LOCAL.get(canon)
            if local is None:
                return None

            R = doc.component_R.get(ref.component, MAT_IDENTITY)
            origin = doc.component_origin.get(ref.component, (0.0, 0.0, 0.0))
            return origin, apply_matrix3(R, local)
        if ref.kind == "edge":
            edges = doc.component_edges.get(ref.component, [])
            idx = resolve_mate_index(
                int(ref.edge_index),
                ref.coord_m,
                edges,
                component=ref.component,
                kind="edge",
                filter_kind=ref.filter_kind,
            )
            edge = edges[idx]
            if edge.kind != "circle":
                return None
            R = doc.component_R.get(ref.component, MAT_IDENTITY)
            return edge.midpoint_m, apply_matrix3(R, (0.0, 0.0, 1.0))
        faces = doc.component_faces.get(ref.component, [])
        idx = resolve_mate_index(
            int(ref.face_index),
            ref.coord_m,
            faces,
            component=ref.component,
            kind="face",
            filter_kind=ref.filter_kind,
        )
        face = faces[idx]
        if face.normal_m is None:
            return None
        return face.centroid_m, face.normal_m

    def _entity_axis(
        self, doc: _Doc, ref
    ) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:

        R = doc.component_R.get(ref.component, MAT_IDENTITY)
        axis = apply_matrix3(R, (0.0, 0.0, 1.0))
        if ref.kind == "edge":
            edges = doc.component_edges.get(ref.component, [])
            idx = resolve_mate_index(
                int(ref.edge_index),
                ref.coord_m,
                edges,
                component=ref.component,
                kind="edge",
                filter_kind=ref.filter_kind,
            )
            return edges[idx].midpoint_m, axis
        faces = doc.component_faces.get(ref.component, [])
        idx = resolve_mate_index(
            int(ref.face_index),
            ref.coord_m,
            faces,
            component=ref.component,
            kind="face",
            filter_kind=ref.filter_kind,
        )
        return faces[idx].centroid_m, axis

    # ---------- Orientation align ----------

    def _align_direction(
        self,
        n_mov: tuple[float, float, float],
        n_fix: tuple[float, float, float],
        align: str | None,
    ) -> tuple[float, float, float]:
        if align == "anti_aligned":
            return (-n_fix[0], -n_fix[1], -n_fix[2])
        if align == "aligned":
            return n_fix
        if _vec_dot(n_mov, n_fix) < 0:
            return (-n_fix[0], -n_fix[1], -n_fix[2])
        return n_fix

    # ---------- Mate solve ----------

    def _solve_mate(
        self, doc: _Doc, mate_type: str, ref1, ref2, align: str | None
    ) -> None:
        if ref1.component not in doc.components or ref2.component not in doc.components:
            return
        if mate_type == "coincident":
            g1, g2 = self._entity_plane(doc, ref1), self._entity_plane(doc, ref2)
            if g1 is None or g2 is None:
                return
            movable = self._movable_of_pair(doc, ref1.component, ref2.component)
            if movable == ref1.component:
                p_fix, n_fix, p_mov, n_mov = g2[0], g2[1], g1[0], g1[1]
            else:
                p_fix, n_fix, p_mov, n_mov = g1[0], g1[1], g2[0], g2[1]
            n_fix_u, n_mov_u = _vec_unit(n_fix), _vec_unit(n_mov)
            if n_fix_u is None or n_mov_u is None:
                return
            target = self._align_direction(n_mov_u, n_fix_u, align)
            self._apply_rigid(doc, movable, _rotation_aligning(n_mov_u, target), p_mov)
            p_mov2, _ = self._entity_plane(
                doc, ref1 if movable == ref1.component else ref2
            ) or (p_mov, n_mov)
            gap = _vec_dot(
                (p_mov2[0] - p_fix[0], p_mov2[1] - p_fix[1], p_mov2[2] - p_fix[2]),
                n_fix_u,
            )
            self._translate_component(
                doc, movable, -gap * n_fix_u[0], -gap * n_fix_u[1], -gap * n_fix_u[2]
            )
            return
        if mate_type != "concentric":
            return
        g1, g2 = self._entity_axis(doc, ref1), self._entity_axis(doc, ref2)
        if g1 is None or g2 is None:
            return
        movable = self._movable_of_pair(doc, ref1.component, ref2.component)
        if movable == ref1.component:
            p_fix, a_fix, p_mov, a_mov = g2[0], g2[1], g1[0], g1[1]
        else:
            p_fix, a_fix, p_mov, a_mov = g1[0], g1[1], g2[0], g2[1]
        a_fix_u, a_mov_u = _vec_unit(a_fix), _vec_unit(a_mov)
        if a_fix_u is None or a_mov_u is None:
            return
        target = self._align_direction(a_mov_u, a_fix_u, align)
        self._apply_rigid(doc, movable, _rotation_aligning(a_mov_u, target), p_mov)
        p_mov2, _ = self._entity_axis(
            doc, ref1 if movable == ref1.component else ref2
        ) or (p_mov, a_mov)
        rel = (p_mov2[0] - p_fix[0], p_mov2[1] - p_fix[1], p_mov2[2] - p_fix[2])
        axial = _vec_dot(rel, a_fix_u)
        radial = (
            rel[0] - axial * a_fix_u[0],
            rel[1] - axial * a_fix_u[1],
            rel[2] - axial * a_fix_u[2],
        )
        self._translate_component(doc, movable, -radial[0], -radial[1], -radial[2])

    # ---------- Mate API (6 kinds + list/delete) ----------

    def mate_concentric(
        self, entity1: str, entity2: str, align: str | None = None
    ) -> MateInfo:
        self._enter("mate_concentric", entity1=entity1, entity2=entity2, align=align)
        return self._mate("concentric", entity1, entity2, align)

    def mate_coincident(
        self, entity1: str, entity2: str, align: str | None = None
    ) -> MateInfo:
        self._enter("mate_coincident", entity1=entity1, entity2=entity2, align=align)
        return self._mate("coincident", entity1, entity2, align)

    def mate_distance(
        self, entity1: str, entity2: str, distance_m: float, align: str | None = None
    ) -> MateInfo:
        self._enter(
            "mate_distance", entity1=entity1, entity2=entity2, distance=distance_m, align=align
        )
        if distance_m < 0:
            raise fail("INVALID_ARGUMENT", "Distance cannot be negative", "Pass distance >= 0")
        return self._mate("distance", entity1, entity2, align)

    def mate_angle(
        self, entity1: str, entity2: str, angle_rad: float, align: str | None = None
    ) -> MateInfo:
        self._enter("mate_angle", entity1=entity1, entity2=entity2, angle=angle_rad, align=align)
        return self._mate("angle", entity1, entity2, align)

    def mate_tangent(
        self, entity1: str, entity2: str, align: str | None = None
    ) -> MateInfo:
        self._enter("mate_tangent", entity1=entity1, entity2=entity2, align=align)
        return self._mate("tangent", entity1, entity2, align)

    def mate_screw(
        self, entity1: str, entity2: str, pitch_m: float, align: str | None = None
    ) -> MateInfo:
        self._enter("mate_screw", entity1=entity1, entity2=entity2, pitch=pitch_m, align=align)
        if pitch_m <= 0:
            raise fail("INVALID_ARGUMENT", "Pitch must be positive", "Pass pitch > 0")
        return self._mate("screw", entity1, entity2, align)

    def list_mates(self) -> list[MateInfo]:
        self._enter("list_mates")
        doc = self._require_assembly("Create an assembly with new_assembly, then list mates")
        return list(doc.mates)

    def delete_mate(self, name: str) -> None:
        self._enter("delete_mate", name=name)
        doc = self._require_assembly("Create an assembly with new_assembly, then delete mates")
        if not any(m.name == name for m in doc.mates):
            raise fail(
                "FEATURE_NOT_FOUND", f"Mate not found: {name!r}", "Use list_mates for mate names", name=name
            )
        doc.mates = [m for m in doc.mates if m.name != name]
        doc.modified = True
