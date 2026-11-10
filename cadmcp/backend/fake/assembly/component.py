"""Fake backend · assembly domain · components（S8f）。

S8f: 24 methods (entry / insert / snapshot / query / world sync / move-rotate /
      in-context edit / lightweight / patterns / mate lock query / child cleanup).

Dependencies (self, MRO):
- `_enter` / `_require_doc` / `_doc` / `_edit_component`（FakeBackend）
- `_part_library` / `_assembly_library`（FakeBackend.__init__）
- `_drop_component` (this file; called from FakeFeatureManageMixin.delete_feature)

Imports:
- `cadmcp.backend.protocol.models`（ComponentRef）
- `cadmcp.backend.protocol.constants`（MAT_IDENTITY / POSE_PIVOTS）
- `cadmcp.backend.protocol.geometry_math`（apply_matrix3 / matmul3 /
  rotate_point_about_axis / rotation_matrix_axis）
- `cadmcp.backend.protocol.validators`（fail_if_component_mated）
- `cadmcp.backend.protocol.parsers`（component_name_keys / linear_pattern_offset_m）
- `cadmcp.errors`（fail）
- `.._state`（_Doc / _as_assembly_snap_item / _snap_bboxes / _union_boxes）
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING

from cadmcp.backend.protocol.constants import MAT_IDENTITY, POSE_PIVOTS
from cadmcp.backend.protocol.geometry_math import (
    apply_matrix3,
    matmul3,
    rotate_point_about_axis,
    rotation_matrix_axis,
)
from cadmcp.backend.protocol.models import ComponentRef, FeatureInfo
from cadmcp.backend.protocol.models import EdgeRef as _EdgeRef
from cadmcp.backend.protocol.models import FaceRef as _FaceRef
from cadmcp.backend.protocol.parsers import (
    linear_pattern_offset_m,
)
from cadmcp.backend.protocol.validators import fail_if_component_mated
from cadmcp.errors import fail

from .._state import (
    _as_assembly_snap_item,
    _snap_bboxes,
    _union_boxes,
)

if TYPE_CHECKING:
    from .._state import _Doc


class FakeAssemblyComponentMixin:
    """Assembly components (S8f: 24 methods)."""

    def _init_state(self) -> None:
        pass  # State owned by FakeBackend._init_state

    # ---------- Entry ----------

    def _require_assembly(self, hint: str) -> _Doc:
        doc = self._require_doc()
        if doc.doc_type != "assembly":
            raise fail("INVALID_ARGUMENT", "Active document is not an assembly", hint)
        return doc

    # ---------- Insert ----------

    def insert_component(
        self, path: Path, x_m: float = 0.0, y_m: float = 0.0, z_m: float = 0.0
    ) -> ComponentRef:
        self._enter("insert_component", path=path, x=x_m, y=y_m, z=z_m)
        doc = self._require_assembly("Create an assembly with new_assembly, then insert components")
        if not path.exists():
            raise fail("OPEN_FAILED", f"Part file does not exist: {path}", "Confirm the path is correct")
        n = doc.instance_seq.get(path.stem, 0) + 1
        doc.instance_seq[path.stem] = n
        name = f"{path.stem}-{n}"  # SW rule: <filename>-<serial>
        doc.components[name] = str(path)
        resolved = str(Path(path).resolve())
        origin = (x_m, y_m, z_m)
        if path.suffix.lower() == ".sldasm":
            snap = [_as_assembly_snap_item(it) for it in self._assembly_library.get(resolved, [])]
            local = _union_boxes([b for b in _snap_bboxes(snap) if b is not None])
            doc.component_local_faces[name] = []
            doc.component_local_edges[name] = []
            doc.component_local_bbox[name] = local
            doc.component_R[name] = MAT_IDENTITY
            doc.component_origin[name] = origin
            doc.component_material[name] = ""
            for item in snap:
                self._instantiate_nested(doc, item, parent=name)
            self._sync_component_world(doc, name)
        else:
            stored = self._part_library.get(resolved)
            if stored is None:
                faces, edges, bbox_part, material = [], [], (0.0, 0.0, 0.0, 0.0, 0.0, 0.0), ""
            else:
                faces, edges, bbox_part = stored[0], stored[1], stored[2]
                material = stored[3] if len(stored) > 3 else ""
            doc.component_local_faces[name] = list(faces)
            doc.component_local_edges[name] = list(edges)
            doc.component_local_bbox[name] = tuple(bbox_part)
            doc.component_R[name] = MAT_IDENTITY
            doc.component_origin[name] = origin
            doc.component_material[name] = material
            self._sync_component_world(doc, name)
        doc.modified = True
        bbox = doc.component_bbox[name]
        return ComponentRef(name=name, path=str(path), origin_m=origin, bbox_m=bbox)

    # ---------- Snapshot ----------

    def _snapshot_component(self, doc: _Doc, name: str) -> dict:
        return {
            "name": name,
            "path": doc.components.get(name) or doc.nested_paths.get(name, ""),
            "material": doc.component_material.get(name, ""),
            "config": doc.active_config,
            "origin_m": doc.component_origin.get(name, (0.0, 0.0, 0.0)),
            "local_bbox": tuple(doc.component_local_bbox.get(name, (0.0,) * 6)),
            "bbox_m": tuple(doc.component_bbox.get(name, (0.0,) * 6)),
            "local_faces": list(doc.component_local_faces.get(name, [])),
            "local_edges": list(doc.component_local_edges.get(name, [])),
            "children": [
                self._snapshot_nested_child(doc, child)
                for child in doc.nested_children.get(name, [])
            ],
        }

    def _snapshot_nested_child(self, doc: _Doc, name: str) -> dict:
        return {
            "name": name,
            "path": doc.nested_paths.get(name, ""),
            "material": doc.component_material.get(name, ""),
            "config": doc.active_config,
            "origin_m": doc.component_origin.get(name, (0.0, 0.0, 0.0)),
            "local_bbox": tuple(doc.component_local_bbox.get(name, (0.0,) * 6)),
            "bbox_m": tuple(doc.component_bbox.get(name, (0.0,) * 6)),
            "local_faces": list(doc.component_local_faces.get(name, [])),
            "local_edges": list(doc.component_local_edges.get(name, [])),
            "children": [],
        }

    def _instantiate_nested(self, doc: _Doc, item: dict, *, parent: str) -> None:
        raw = str(item.get("name") or Path(str(item.get("path") or "comp")).stem)
        cname = f"{raw}@{parent}"
        loc_o = tuple(item.get("origin_m") or (0.0, 0.0, 0.0))
        loc_b = tuple(item.get("local_bbox") or (0.0,) * 6)
        if len(loc_o) != 3:
            loc_o = (0.0, 0.0, 0.0)
        if len(loc_b) != 6:
            loc_b = (0.0,) * 6
        doc.nested_paths[cname] = str(item.get("path") or "")
        doc.nested_local_origin[cname] = loc_o
        doc.nested_local_R[cname] = MAT_IDENTITY
        doc.nested_children.setdefault(parent, []).append(cname)
        doc.component_local_faces[cname] = list(item.get("local_faces") or [])
        doc.component_local_edges[cname] = list(item.get("local_edges") or [])
        doc.component_local_bbox[cname] = loc_b
        doc.component_material[cname] = str(item.get("material") or "")
        for grand in item.get("children") or []:
            self._instantiate_nested(doc, _as_assembly_snap_item(grand), parent=parent)

    # ---------- Query ----------

    def _component_or_fail(
        self, doc: _Doc, name: str, *, allow_nested: bool = False
    ) -> None:
        if name in doc.components or (allow_nested and name in doc.nested_paths):
            return
        raise fail(
            "INVALID_ARGUMENT",
            f"Component not found: {name!r}",
            "Instance names from insert_component / list_components, e.g. p1-1 or p1-1@sub-1",
            component=name,
        )

    def _component_ref(self, doc: _Doc, name: str) -> ComponentRef:
        origin = doc.component_origin.get(name, (0.0, 0.0, 0.0))
        bbox = doc.component_bbox.get(name)
        box = tuple(bbox) if bbox is not None and len(bbox) == 6 else None
        path = doc.components.get(name) or doc.nested_paths.get(name)
        return ComponentRef(
            name=name,
            path=path,
            origin_m=origin,
            bbox_m=box,
            lightweight=name in doc.component_lightweight,
        )

    def list_components(self, children: bool = False) -> list[ComponentRef]:
        self._enter("list_components", children=children)
        doc = self._require_assembly("Create an assembly with new_assembly, then list components")
        out = [self._component_ref(doc, n) for n in doc.components]
        if children:
            for parent in doc.components:
                out.extend(self._component_ref(doc, c) for c in doc.nested_children.get(parent, []))
        return out

    def get_component(self, name: str) -> ComponentRef:
        self._enter("get_component", name=name)
        doc = self._require_assembly("Create an assembly with new_assembly, then get a component")
        self._component_or_fail(doc, name, allow_nested=True)
        return self._component_ref(doc, name)

    # ---------- World-space sync ----------

    def _mates_locking(self, doc: _Doc, name: str) -> list[str]:
        out: list[str] = []
        for mate in doc.mates:
            pair = mate.components
            if pair is not None and name in pair:
                out.append(mate.name)
        return out

    def _sync_component_world(self, doc: _Doc, name: str) -> None:
        R = doc.component_R.get(name, MAT_IDENTITY)
        origin = doc.component_origin.get(name, (0.0, 0.0, 0.0))
        b = doc.component_local_bbox.get(name, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0))
        corners = [
            tuple(c + o for c, o in zip(apply_matrix3(R, (x, y, z)), origin, strict=True))
            for x in (b[0], b[3])
            for y in (b[1], b[4])
            for z in (b[2], b[5])
        ]
        xs, ys, zs = zip(*corners, strict=True)
        doc.component_bbox[name] = (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))
        doc.component_faces[name] = [
            _FaceRef(
                index=f.index,
                kind=f.kind,
                centroid_m=tuple(
                    c + o for c, o in zip(apply_matrix3(R, f.centroid_m), origin, strict=True)
                ),
                normal_m=apply_matrix3(R, f.normal_m) if f.normal_m is not None else None,
            )
            for f in doc.component_local_faces.get(name, [])
        ]
        doc.component_edges[name] = [
            _EdgeRef(
                index=e.index,
                kind=e.kind,
                midpoint_m=tuple(
                    c + o for c, o in zip(apply_matrix3(R, e.midpoint_m), origin, strict=True)
                ),
            )
            for e in doc.component_local_edges.get(name, [])
        ]
        for child in doc.nested_children.get(name, []):
            loc = doc.nested_local_origin.get(child, (0.0, 0.0, 0.0))
            loc_r = doc.nested_local_R.get(child, MAT_IDENTITY)
            doc.component_origin[child] = tuple(
                c + o for c, o in zip(apply_matrix3(R, loc), origin, strict=True)
            )
            doc.component_R[child] = matmul3(R, loc_r)
            self._sync_one_component_world(doc, child)

    def _sync_one_component_world(self, doc: _Doc, name: str) -> None:
        R = doc.component_R.get(name, MAT_IDENTITY)
        origin = doc.component_origin.get(name, (0.0, 0.0, 0.0))
        b = doc.component_local_bbox.get(name, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0))
        corners = [
            tuple(c + o for c, o in zip(apply_matrix3(R, (x, y, z)), origin, strict=True))
            for x in (b[0], b[3])
            for y in (b[1], b[4])
            for z in (b[2], b[5])
        ]
        xs, ys, zs = zip(*corners, strict=True)
        doc.component_bbox[name] = (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))
        doc.component_faces[name] = [
            _FaceRef(
                index=f.index,
                kind=f.kind,
                centroid_m=tuple(
                    c + o for c, o in zip(apply_matrix3(R, f.centroid_m), origin, strict=True)
                ),
                normal_m=apply_matrix3(R, f.normal_m) if f.normal_m is not None else None,
            )
            for f in doc.component_local_faces.get(name, [])
        ]
        doc.component_edges[name] = [
            _EdgeRef(
                index=e.index,
                kind=e.kind,
                midpoint_m=tuple(
                    c + o for c, o in zip(apply_matrix3(R, e.midpoint_m), origin, strict=True)
                ),
            )
            for e in doc.component_local_edges.get(name, [])
        ]

    def _translate_component(
        self, doc: _Doc, name: str, dx: float, dy: float, dz: float
    ) -> None:
        if math.hypot(dx, dy, dz) < 1e-12:
            return
        ox, oy, oz = doc.component_origin.get(name, (0.0, 0.0, 0.0))
        doc.component_origin[name] = (ox + dx, oy + dy, oz + dz)
        self._sync_component_world(doc, name)

    # ---------- Move / rotate ----------

    def move_component(
        self,
        name: str,
        x_m: float,
        y_m: float,
        z_m: float,
        relative: bool = False,
        force: bool = False,
    ) -> ComponentRef:
        self._enter(
            "move_component", name=name, x=x_m, y=y_m, z=z_m, relative=relative, force=force
        )
        doc = self._require_assembly("Create an assembly with new_assembly, then move components")
        self._component_or_fail(doc, name)
        if not force:
            fail_if_component_mated(name, self._mates_locking(doc, name))
        ox, oy, oz = doc.component_origin.get(name, (0.0, 0.0, 0.0))
        if relative:
            self._translate_component(doc, name, x_m, y_m, z_m)
        else:
            self._translate_component(doc, name, x_m - ox, y_m - oy, z_m - oz)
        doc.modified = True
        return self._component_ref(doc, name)

    def rotate_component(
        self,
        name: str,
        axis: str,
        angle_rad: float,
        about: str = "origin",
        absolute: bool = False,
        force: bool = False,
        pivot_m: tuple[float, float, float] | None = None,
    ) -> ComponentRef:
        self._enter(
            "rotate_component",
            name=name, axis=axis, angle=angle_rad, about=about,
            absolute=absolute, force=force, pivot=pivot_m,
        )
        doc = self._require_assembly("Create an assembly with new_assembly, then rotate components")
        self._component_or_fail(doc, name)
        if pivot_m is None and about not in POSE_PIVOTS:
            raise fail(
                "INVALID_ARGUMENT",
                f"Unknown rotation pivot: {about!r}",
                f"about：{', '.join(POSE_PIVOTS)}",
                requested=about,
            )
        if not force:
            fail_if_component_mated(name, self._mates_locking(doc, name))
        delta = rotation_matrix_axis(axis, angle_rad)
        old_r = doc.component_R.get(name, MAT_IDENTITY)
        origin = doc.component_origin.get(name, (0.0, 0.0, 0.0))
        if pivot_m is not None:
            pivot = (float(pivot_m[0]), float(pivot_m[1]), float(pivot_m[2]))
        else:
            pivot = (0.0, 0.0, 0.0) if about == "world" else origin
        if absolute:
            doc.component_R[name] = delta
        elif abs(float(angle_rad)) > 1e-15:
            doc.component_R[name] = matmul3(delta, old_r)
            doc.component_origin[name] = rotate_point_about_axis(
                origin, pivot, axis, angle_rad
            )
        self._sync_component_world(doc, name)
        doc.modified = True
        return self._component_ref(doc, name)

    # ---------- In-context edit ----------

    def edit_component(self, name: str) -> str:
        self._enter("edit_component", name=name)
        doc = self._require_assembly("Create an assembly with new_assembly, then edit in context")
        raw = str(name).strip()
        if not raw:
            raise fail("INVALID_ARGUMENT", "Component name cannot be empty", "Pass an instance name from list_components")
        self._component_or_fail(doc, raw)
        path = str(doc.components.get(raw) or "")
        if not path.lower().endswith(".sldasm"):
            raise fail(
                "INVALID_ARGUMENT",
                "In-context edit only supports subassemblies",
                "Use edit_component on .sldasm instances; part in-context edit is not implemented",
                component=raw,
            )
        self._edit_component = raw
        doc.modified = True
        return raw

    def end_edit(self) -> None:
        self._enter("end_edit")
        self._require_assembly("Exit in-context edit on an assembly")
        if not self._edit_component:
            raise fail("INVALID_ARGUMENT", "Not currently in in-context edit", "Call edit_component first")
        self._edit_component = None

    def get_edit_target(self) -> str | None:
        self._enter("get_edit_target")
        self._require_assembly("Query in-context edit target on an assembly")
        return self._edit_component

    # ---------- Lightweight ----------

    def set_lightweight(self, name: str, lightweight: bool) -> str:
        self._enter("set_lightweight", name=name, lightweight=lightweight)
        doc = self._require_assembly("Create an assembly with new_assembly, then set lightweight")
        raw = str(name).strip()
        if not raw:
            raise fail("INVALID_ARGUMENT", "Component name cannot be empty", "Pass an instance name from list_components")
        self._component_or_fail(doc, raw, allow_nested=True)
        if lightweight:
            doc.component_lightweight.add(raw)
        else:
            doc.component_lightweight.discard(raw)
        doc.modified = True
        return raw

    # ---------- Patterns ----------

    def pattern_component(
        self,
        name: str,
        count: int,
        axis: str | None = None,
        about: str = "world",
        dx_m: float | None = None,
        dy_m: float | None = None,
        dz_m: float | None = None,
    ) -> tuple[FeatureInfo, list[ComponentRef]]:
        self._enter(
            "pattern_component", name=name, count=count, axis=axis, about=about,
            dx=dx_m, dy=dy_m, dz=dz_m,
        )
        doc = self._require_assembly("Create an assembly with new_assembly, then pattern components")
        self._component_or_fail(doc, name)
        if count < 2:
            raise fail("INVALID_ARGUMENT", "Pattern count must be >= 2 (including seed)", "Pass count >= 2")
        offset = linear_pattern_offset_m(dx_m, dy_m, dz_m)
        if offset is not None and axis is not None:
            raise fail(
                "INVALID_ARGUMENT",
                "Circular patterns use axis; linear patterns use dx/dy/dz — do not mix",
                "Drop axis or drop dx/dy/dz",
            )
        seed = self._component_ref(doc, name)
        path = Path(seed.path or "")
        origin = seed.origin_m or (0.0, 0.0, 0.0)
        if offset is None:
            if axis is None:
                raise fail(
                    "INVALID_ARGUMENT",
                    "Need circular axis or linear spacing",
                    "Pass axis=+z, or one of dx/dy/dz",
                )
            rotation_matrix_axis(axis, 0.0)
            if about not in POSE_PIVOTS:
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Unknown rotation pivot: {about!r}",
                    f"about：{', '.join(POSE_PIVOTS)}",
                    requested=about,
                )
            out = [seed]
            step = math.tau / count
            copies: list[str] = []
            for i in range(1, count):
                inst = self.insert_component(path, origin[0], origin[1], origin[2])
                spun = self.rotate_component(inst.name, axis, step * i, about=about, force=True)
                copies.append(spun.name)
                out.append(spun)
            n = sum(1 for x in doc.features if x.get("kind") == "local_cir_pattern") + 1
            fname = f"LocalCirPattern{n}"
            kind = "local_cir_pattern"
        else:
            dx, dy, dz = offset
            out = [seed]
            copies = []
            for i in range(1, count):
                inst = self.insert_component(
                    path, origin[0] + dx * i, origin[1] + dy * i, origin[2] + dz * i
                )
                copies.append(inst.name)
                out.append(inst)
            n = sum(1 for x in doc.features if x.get("kind") == "local_l_pattern") + 1
            fname = f"LocalLPattern{n}"
            kind = "local_l_pattern"
        doc.features.append({
            "kind": kind, "sign": 0, "name": fname,
            "seed": name, "copies": copies,
        })
        doc.modified = True
        return FeatureInfo(name=fname, kind=kind), out

    # ---------- Child cleanup ----------

    def _drop_component(self, doc: _Doc, name: str) -> None:
        for child in list(doc.nested_children.pop(name, [])):
            self._drop_component(doc, child)
        doc.components.pop(name, None)
        doc.nested_paths.pop(name, None)
        doc.component_lightweight.discard(name)
        for store in (
            doc.component_faces, doc.component_edges, doc.component_bbox,
            doc.component_origin, doc.component_local_bbox, doc.component_R,
            doc.component_local_faces, doc.component_local_edges, doc.component_material,
            doc.nested_local_origin, doc.nested_local_R,
        ):
            store.pop(name, None)
        doc.mates = [m for m in doc.mates if name not in (m.components or ())]
