"""Assembly domain · components (S6-3a).

S6-3a-1:_asm_select_name / _component_by_name / _assembly_component_objs /
       _assembly_component_names / _edit_target_name / _component_ref_of
S6-3a-2:+ list_components / get_component / edit_component / end_edit /
       get_edit_target / set_lightweight / set_color / get_color
S6-3a-3:+ insert_component / move_component / rotate_component +
       _pose_component / _unfix_component / _mate_involves_component /
       _component_mate_names
S6-3a-4: + pattern_component (inline; phase D switches to private helpers)

Scope boundaries (v1.2.2 section 4.1 / 4.3):
- This file only orchestrates component business logic.
- Geometry (_comp_point/_component_bbox_m/_component_is_lightweight/
  _component_is_fixed/_write_comp_transform/_snap_component_origin/
  _comp_dir/_unit_dir) -> GeometryMixin (com/geometry.py)
- Selection (_select_component) -> SelectionMixin (com/selection.py)
- Active document switching (_ensure_active) -> InfrastructureMixin (com/infrastructure.py)
- Mate feature iteration (_iter_mate_features) -> MateMixin (com/assembly/mate.py)

Dependencies (self, MRO):
- `_call` / `_map_error`(STAThreadMixin)
- `_require_assembly_doc` / `_require_part_doc` / `_ensure_active`(InfrastructureMixin)
- `_select_component` / `_clear_selection`(SelectionMixin)
- `_comp_point` / `_component_bbox_m` / `_component_is_lightweight` /
  `_component_is_fixed` / `_write_comp_transform` / `_snap_component_origin`
  (GeometryMixin)
- `_iter_mate_features`(MateMixin, S6-3b)
- `_get` / `_doc_type_for`(_helpers)

imports:
- `cadmcp.backend.protocol.models`(ComponentRef)
- `cadmcp.backend.protocol.constants`(POSE_PIVOTS / REVOLVE_AXES)
- `cadmcp.backend.protocol.geometry_math`(matmul3 / rotation_matrix_axis /
  rotate_point_about_axis)
- `cadmcp.backend.protocol.parsers`(component_name_keys)
- `cadmcp.backend.protocol.validators`(fail_if_component_mated)
- `cadmcp.errors`(fail)
- `.._helpers`(_get / _doc_type_for)
"""
from __future__ import annotations

import logging
import math
import traceback
from pathlib import Path
from typing import Any

from cadmcp.backend.protocol.constants import POSE_PIVOTS, REVOLVE_AXES
from cadmcp.backend.protocol.geometry_math import (
    matmul3,
    rotate_point_about_axis,
    rotation_matrix_axis,
)
from cadmcp.backend.protocol.models import ComponentRef, FeatureInfo
from cadmcp.backend.protocol.parsers import component_name_keys, linear_pattern_offset_m
from cadmcp.backend.protocol.validators import fail_if_component_mated
from cadmcp.errors import fail

from .._helpers import _doc_type_for, _get

log = logging.getLogger(__name__)


class ComponentMixin:
    """Component orchestration (S6-3a)."""

    def _init_state(self) -> None:
        pass  # stateless

    # ---------- S6-3a-1: basic helpers ----------

    @staticmethod
    def _asm_select_name(title: str) -> str:
        """Assembly title -> assembly segment in select-by-name strings (strip displayed extension if any)."""
        return title[:-7] if title.lower().endswith(".sldasm") else title

    def _component_by_name(self, doc: Any, name: str) -> Any:
        # False = all instances (including sub-asm p1-1@sub-1 / Name2 sub-1/p1-1).
        want = component_name_keys(name)
        exact = None
        hit = None
        for comp in _get(doc, "GetComponents", False) or ():
            try:
                n2 = str(_get(comp, "Name2") or "")
            except Exception:
                log.debug("Failed to read component name: %s", traceback.format_exc())
                continue
            if not n2:
                continue
            if n2 == name:
                exact = comp
                break
            if want & component_name_keys(n2):
                hit = comp
        return exact or hit

    def _assembly_component_objs(
        self, doc: Any, *, top_level_only: bool = True
    ) -> list[tuple[str, Any]]:
        """IAssemblyDoc.GetComponents(TopLevelOnly): True top-level only, False includes nested instances."""
        out: list[tuple[str, Any]] = []
        for comp in _get(doc, "GetComponents", top_level_only) or ():
            try:
                name = str(_get(comp, "Name2") or "")
            except Exception:
                log.debug("Failed to read component name: %s", traceback.format_exc())
                continue
            if name:
                out.append((name, comp))
        return out

    def _assembly_component_names(self, doc: Any) -> list[str]:
        return [n for n, _ in self._assembly_component_objs(doc)]

    def _edit_target_name(self, doc: Any) -> str | None:
        try:
            active = str(_get(doc, "GetTitle") or "")
            tgt = _get(doc, "GetEditTarget")
            title = str(_get(tgt, "GetTitle") or "") if tgt is not None else ""
        except Exception:
            return None
        if not title or title == active:
            return None
        try:
            comp = _get(doc, "GetEditTargetComponent")
            name = str(_get(comp, "Name2") or "") if comp is not None else ""
        except Exception:
            name = ""
        return name or title

    def _component_ref_of(
        self, comp: Any, name: str, path: str | None = None
    ) -> ComponentRef:
        origin = self._comp_point(comp, (0.0, 0.0, 0.0))
        bbox = self._component_bbox_m(comp)
        resolved = name
        try:
            resolved = str(_get(comp, "Name2") or name)
        except Exception:
            pass
        if path is None:
            try:
                model = _get(comp, "GetModelDoc2")
                path = str(_get(model, "GetPathName") or "") if model is not None else None
            except Exception:
                path = None
            if not path:
                try:
                    path = str(_get(comp, "GetPathName") or "") or None
                except Exception:
                    path = None
        return ComponentRef(
            name=resolved,
            path=path or None,
            origin_m=origin,
            bbox_m=bbox,
            lightweight=self._component_is_lightweight(comp),
        )

    # ---------- S6-3a-2: simple public methods ----------

    def list_components(self, children: bool = False) -> list[ComponentRef]:
        def _fn() -> list[ComponentRef]:
            asm = self.sw.ActiveDoc
            self._require_assembly_doc(asm, "Use new_assembly before listing components")
            return [
                self._component_ref_of(comp, name)
                for name, comp in self._assembly_component_objs(
                    asm, top_level_only=not children
                )
            ]

        return self._call(_fn)

    def get_component(self, name: str) -> ComponentRef:
        def _fn() -> ComponentRef:
            asm = self.sw.ActiveDoc
            self._require_assembly_doc(asm, "Use new_assembly before reading a component")
            comp = self._component_by_name(asm, name)
            if comp is None:
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Component not found: {name!r}",
                    "Instance name from insert_component return value, e.g. p1-1",
                    component=name,
                )
            return self._component_ref_of(comp, name)

        return self._call(_fn)

    def edit_component(self, name: str) -> str:
        def _fn() -> str:
            doc = self.sw.ActiveDoc
            self._require_assembly_doc(doc, "Use new_assembly before edit-in-place")
            raw = str(name).strip()
            if not raw:
                raise fail("INVALID_ARGUMENT", "Component name cannot be empty", "Pass an instance name from list_components")
            want = component_name_keys(raw)
            comp = None
            for n, c in self._assembly_component_objs(doc, top_level_only=True):
                if n == raw or (want & component_name_keys(n)):
                    comp = c
                    break
            if comp is None:
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Component not found: {raw!r}",
                    "Instance name from insert_component / list_components",
                    component=raw,
                )
            model = None
            try:
                model = _get(comp, "GetModelDoc2")
            except Exception:
                model = None
            try:
                mtype = int(_get(model, "GetType")) if model is not None else 0
            except Exception:
                mtype = 0
            if mtype != 2:  # SW_DOC_ASSEMBLY
                raise fail(
                    "INVALID_ARGUMENT",
                    "Edit-in-place only supports sub-assemblies",
                    "Use edit_component on .sldasm instances; in-place part edit not supported in this phase",
                    component=raw,
                )
            if not self._select_component(doc, comp):
                raise fail("SELECT_FAILED", f"Could not select component {raw!r}", "Use list_components to see instance names")
            try:
                doc.EditAssembly()
            except Exception as exc:
                log.debug("EditAssembly failed: %s", traceback.format_exc())
                raise self._map_error(exc) from exc
            current = self._edit_target_name(doc)
            if current is None:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Failed to enter sub-assembly edit-in-place",
                    "Confirm the instance is saved as .sldasm and no modal dialog is blocking",
                )
            return current

        return self._call(_fn)

    def end_edit(self) -> None:
        def _fn() -> None:
            doc = self.sw.ActiveDoc
            self._require_assembly_doc(doc, "Exit edit-in-place on an assembly")
            if self._edit_target_name(doc) is None:
                raise fail("INVALID_ARGUMENT", "Not currently in edit-in-place", "Call edit_component first")
            try:
                doc.ClearSelection2(True)
            except Exception:
                pass
            try:
                doc.EditAssembly()
            except Exception as exc:
                log.debug("Exit EditAssembly failed: %s", traceback.format_exc())
                raise self._map_error(exc) from exc

        return self._call(_fn)

    def get_edit_target(self) -> str | None:
        def _fn() -> str | None:
            doc = self.sw.ActiveDoc
            self._require_assembly_doc(doc, "Query edit-in-place target on an assembly")
            return self._edit_target_name(doc)

        return self._call(_fn)

    def set_lightweight(self, name: str, lightweight: bool) -> str:
        def _fn() -> str:
            doc = self.sw.ActiveDoc
            self._require_assembly_doc(doc, "Use new_assembly before changing lightweight state")
            raw = str(name).strip()
            if not raw:
                raise fail("INVALID_ARGUMENT", "Component name cannot be empty", "Pass an instance name from list_components")
            comp = self._component_by_name(doc, raw)
            if comp is None:
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Component not found: {raw!r}",
                    "Instance name from insert_component / list_components",
                    component=raw,
                )
            state = 1 if lightweight else 2  # LIGHTWEIGHT / RESOLVED
            try:
                rc = int(_get(comp, "SetSuppression2", state))
            except Exception as exc:
                raise self._map_error(exc) from exc
            if rc == 0 or self._component_is_lightweight(comp) != bool(lightweight):
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Failed to change component lightweight state",
                    "Confirm the instance is not suppressed and no modal dialog is blocking",
                    component=raw,
                )
            return str(_get(comp, "Name2") or raw)

        return self._call(_fn)

    def set_color(self, r: float, g: float, b: float) -> tuple[float, float, float]:
        def _fn() -> tuple[float, float, float]:
            doc = self.sw.ActiveDoc
            self._require_part_doc(doc, "Set appearance color on a part")
            rgb = (float(r), float(g), float(b))
            for c in rgb:
                if c < 0.0 or c > 1.0:
                    raise fail("INVALID_ARGUMENT", "RGB components must be in 0–1", "Pass 0 <= r,g,b <= 1")
            vals = [rgb[0], rgb[1], rgb[2], 1.0, 1.0, 1.0, 0.0, 0.4, 0.0]
            try:
                doc.MaterialPropertyValues = vals
            except Exception:
                try:
                    doc.SetMaterialPropertyValues(vals)
                except Exception as exc:
                    raise self._map_error(exc) from exc
            return rgb

        return self._call(_fn)

    def get_color(self) -> tuple[float, float, float] | None:
        def _fn() -> tuple[float, float, float] | None:
            doc = self.sw.ActiveDoc
            self._require_part_doc(doc, "Read appearance color on a part")
            vals = None
            try:
                vals = list(_get(doc, "MaterialPropertyValues") or ())
            except Exception:
                try:
                    vals = list(doc.GetMaterialPropertyValues() or ())
                except Exception:
                    vals = None
            if not vals or len(vals) < 3:
                return None
            return (float(vals[0]), float(vals[1]), float(vals[2]))

        return self._call(_fn)

    # ---------- S6-3a-3: pose (insert / move / rotate) ----------

    def _unfix_component(self, asm: Any, comp: Any) -> None:
        selected = self._select_component(asm, comp)
        if selected and self._component_is_fixed(comp):
            try:
                _get(asm, "UnFixComponent")
            except Exception:
                log.debug("UnFixComponent failed: %s", traceback.format_exc())

    def _mate_involves_component(self, mate: Any, name: str) -> bool:
        count = 0
        for attr in ("GetMateEntityCount", "GetEntityCount"):
            try:
                val = getattr(mate, attr)
                count = int(val() if callable(val) and not hasattr(val, "_oleobj_") else val)
                break
            except Exception:
                continue
        for i in range(count):
            ent = None
            try:
                ent = mate.MateEntity(i)
            except Exception:
                try:
                    ent = _get(mate, "MateEntity", i)
                except Exception:
                    continue
            if ent is None:
                continue
            for key in ("ReferenceComponent", "Component", "GetComponent"):
                try:
                    c = getattr(ent, key)
                    if callable(c) and not hasattr(c, "_oleobj_"):
                        c = c()
                    cn = str(_get(c, "Name2") or "")
                    if cn == name:
                        return True
                except Exception:
                    continue
        return False

    def _component_mate_names(self, asm: Any, comp: Any, name: str) -> list[str]:
        names: list[str] = []
        mates = None
        try:
            mates = comp.GetMates()
        except TypeError:
            try:
                mates = _get(comp, "GetMates")
            except Exception:
                log.debug("GetMates failed: %s", traceback.format_exc())
        except Exception:
            log.debug("GetMates failed: %s", traceback.format_exc())
        for mate in mates or ():
            try:
                label = str(_get(mate, "Name") or "")
            except Exception:
                label = ""
            if label:
                names.append(label)
        if names:
            return names
        # _iter_mate_features owned by MateMixin (S6-3b); invoked via MRO
        for feat in self._iter_mate_features(asm):
            label = str(_get(feat, "Name") or "")
            spec = feat
            try:
                spec = _get(feat, "GetSpecificFeature2") or feat
            except Exception:
                spec = feat
            if label and self._mate_involves_component(spec, name):
                names.append(label)
        return names

    def _pose_component(
        self, asm: Any, name: str, hint: str, force: bool = False
    ) -> Any:
        self._require_assembly_doc(asm, hint)
        comp = self._component_by_name(asm, name)
        if comp is None:
            raise fail(
                "INVALID_ARGUMENT",
                f"Component not found: {name!r}",
                "Instance name from insert_component return value, e.g. p1-1",
                component=name,
            )
        if not force:
            fail_if_component_mated(name, self._component_mate_names(asm, comp, name))
        return comp

    def insert_component(
        self, path: Path, x_m: float = 0.0, y_m: float = 0.0, z_m: float = 0.0
    ) -> ComponentRef:
        def _fn() -> ComponentRef:
            asm = self.sw.ActiveDoc
            self._require_assembly_doc(asm, "Use new_assembly before inserting a component")
            p = Path(path)
            if not p.is_absolute():
                p = (Path.cwd() / p).resolve()
            if not p.exists():
                raise fail("OPEN_FAILED", f"Component file does not exist: {p}", "Confirm the path is correct")
            asm_title = str(_get(asm, "GetTitle"))
            keep_window = False
            try:
                existing = self.sw.GetOpenDocumentByName(str(p))
                if existing is not None:
                    keep_window = bool(_get(existing, "Visible"))
            except Exception:
                log.debug("Failed to read part open state: %s", traceback.format_exc())
            # Real hardware: AddComponent5 silently returns None if the part is not pre-loaded.
            standalone = self.sw.OpenDoc(str(p), _doc_type_for(p)[1])
            if standalone is None:
                raise fail(
                    "OPEN_FAILED",
                    f"Could not open component file: {p}",
                    "Confirm the file is valid and SolidWorks can open it",
                )
            try:
                comp = _get(asm, "AddComponent5", str(p), 0, "", False, "", x_m, y_m, z_m)
            except Exception as exc:
                raise self._map_error(exc) from exc
            finally:
                if not keep_window:
                    try:
                        self.sw.CloseDoc(_get(standalone, "GetTitle"))
                    except Exception:
                        log.debug("Failed to close standalone part window: %s", traceback.format_exc())
            self._ensure_active(asm, asm_title)
            if comp is None:
                raise fail(
                    "OPEN_FAILED",
                    f"Failed to insert component: {p}",
                    "Confirm the part file exists and SolidWorks can open it",
                )
            origin = self._snap_component_origin(asm, comp, x_m, y_m, z_m)
            try:
                top = self._assembly_component_objs(asm, top_level_only=True)
                if len(top) == 1 and not self._component_is_fixed(comp):
                    if self._select_component(asm, comp):
                        _get(asm, "FixComponent")
            except Exception:
                log.debug("Failed to fix first component: %s", traceback.format_exc())
            bbox = self._component_bbox_m(comp)
            name = p.stem
            try:
                name = str(_get(comp, "Name2")) or name
            except Exception:
                pass
            return ComponentRef(name=name, path=str(p), origin_m=origin, bbox_m=bbox)

        return self._call(_fn)

    def move_component(
        self,
        name: str,
        x_m: float,
        y_m: float,
        z_m: float,
        relative: bool = False,
        force: bool = False,
    ) -> ComponentRef:
        def _fn() -> ComponentRef:
            asm = self.sw.ActiveDoc
            comp = self._pose_component(
                asm, name, "Use new_assembly before moving a component", force=force
            )
            self._unfix_component(asm, comp)
            tx, ty, tz = x_m, y_m, z_m
            if relative:
                ox, oy, oz = self._comp_point(comp, (0.0, 0.0, 0.0))
                tx, ty, tz = ox + x_m, oy + y_m, oz + z_m
            self._snap_component_origin(asm, comp, tx, ty, tz)
            return self._component_ref_of(comp, name)

        return self._call(_fn)

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
        def _fn() -> ComponentRef:
            asm = self.sw.ActiveDoc
            if pivot_m is None and about not in POSE_PIVOTS:
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Unknown rotation pivot: {about!r}",
                    f"about: {', '.join(POSE_PIVOTS)}",
                    requested=about,
                )
            if axis not in REVOLVE_AXES:
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Unknown rotation axis: {axis!r}",
                    f"axis names: {', '.join(REVOLVE_AXES)}",
                    requested=axis,
                )
            comp = self._pose_component(
                asm, name, "Use new_assembly before rotating a component", force=force
            )
            if abs(float(angle_rad)) > 1e-15 or absolute:
                self._unfix_component(asm, comp)
                try:
                    xf = _get(comp, "Transform2")
                    raw = list(_get(xf, "ArrayData"))
                except Exception as exc:
                    raise self._map_error(exc) from exc
                a = [float(v) for v in raw] + [0.0] * max(0, 16 - len(raw))
                old_r = (
                    (a[0], a[1], a[2]),
                    (a[3], a[4], a[5]),
                    (a[6], a[7], a[8]),
                )
                origin = (a[9], a[10], a[11])
                if pivot_m is not None:
                    pivot = (float(pivot_m[0]), float(pivot_m[1]), float(pivot_m[2]))
                else:
                    pivot = (0.0, 0.0, 0.0) if about == "world" else origin
                delta = rotation_matrix_axis(axis, angle_rad)
                new_r = delta if absolute else matmul3(delta, old_r)
                a[0], a[1], a[2] = new_r[0]
                a[3], a[4], a[5] = new_r[1]
                a[6], a[7], a[8] = new_r[2]
                if not absolute:
                    a[9], a[10], a[11] = rotate_point_about_axis(
                        origin, pivot, axis, angle_rad
                    )
                if not self._write_comp_transform(comp, a[:16]):
                    raise fail(
                        "FEATURE_CREATE_FAILED",
                        f"Could not rotate component {name!r}",
                        "Delete mates first, or pass force=true to write the transform",
                        component=name,
                    )
                try:
                    _get(asm, "EditRebuild3")
                except Exception:
                    log.debug("Post-rotate rebuild failed: %s", traceback.format_exc())
            return self._component_ref_of(comp, name)

        return self._call(_fn)

    # ---------- S6-3a-4: patterns (inline; phase D uses private helpers) ----------

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
        def _fn() -> tuple[FeatureInfo, list[ComponentRef]]:
            asm = self.sw.ActiveDoc
            self._require_assembly_doc(asm, "Use new_assembly before patterning components")
            if count < 2:
                raise fail("INVALID_ARGUMENT", "Pattern count must be >= 2 (including seed)", "Pass count >= 2")
            offset = linear_pattern_offset_m(dx_m, dy_m, dz_m)
            if offset is not None and axis is not None:
                raise fail(
                    "INVALID_ARGUMENT",
                    "Circular patterns use axis; linear patterns use dx/dy/dz; do not mix",
                    "Remove axis or remove dx/dy/dz",
                )
            if offset is None:
                if axis is None:
                    raise fail(
                        "INVALID_ARGUMENT",
                        "Need a circular axis or linear spacing",
                        "Pass axis=+z, or one of dx/dy/dz",
                    )
                return self._circular_pattern_component(asm, name, count, axis, about)
            return self._linear_pattern_component(asm, name, count, offset)

        return self._call(_fn, timeout=180.0)

    def _circular_pattern_component(
        self, asm: Any, name: str, count: int, axis: str, about: str
    ) -> tuple[FeatureInfo, list[ComponentRef]]:
        if axis not in REVOLVE_AXES:
            raise fail(
                "INVALID_ARGUMENT",
                f"Unknown rotation axis: {axis!r}",
                f"axis names: {', '.join(REVOLVE_AXES)}",
                requested=axis,
            )
        if about not in POSE_PIVOTS:
            raise fail(
                "INVALID_ARGUMENT",
                f"Unknown rotation pivot: {about!r}",
                f"about: {', '.join(POSE_PIVOTS)}",
                requested=about,
            )
        seed = self._component_by_name(asm, name)
        if seed is None:
            raise fail(
                "INVALID_ARGUMENT",
                f"Component not found: {name!r}",
                "Instance name from insert_component return value, e.g. p1-1",
                component=name,
            )
        # 2025 probe: component mark=1, ref axis mark=2, FeatureCircularPattern3 evenly spaced
        # Writes LocalCirPattern; deleting the feature removes copies, keeps seed.
        axis_feat = self._ensure_ref_axis(asm, axis)
        if not self._select_component(asm, seed, mark=1):
            raise fail("SELECT_FAILED", f"Could not select component {name!r}", "Use list_components to see instance names")
        if not self._select_ref_axis(asm, axis_feat, mark=2):
            raise fail(
                "SELECT_FAILED",
                f"Could not select pattern axis {axis}",
                "Confirm the assembly has default planes, or call create_axis first",
            )
        try:
            feat = asm.FeatureManager.FeatureCircularPattern3(
                int(count), math.tau / int(count), axis.startswith("-"), "", False, True
            )
        except Exception as exc:
            log.debug("Assembly FeatureCircularPattern3 failed: %s", traceback.format_exc())
            raise self._map_error(exc) from exc
        finally:
            self._clear_selection(asm)
        if feat is None:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "Assembly circular pattern failed (API returned None)",
                "Confirm seed instance exists and axis is an assembly reference axis",
            )
        try:
            _get(asm, "ForceRebuild3", True)
        except Exception:
            log.debug("Post-pattern rebuild failed: %s", traceback.format_exc())
        real = self._feature_real_name(feat, "LocalCirPattern")
        info = FeatureInfo(name=self._register("LocalCirPattern", real), kind="local_cir_pattern")
        refs = [
            self._component_ref_of(comp, cname)
            for cname, comp in self._assembly_component_objs(asm, top_level_only=True)
        ]
        return info, refs

    def _linear_pattern_component(
        self, asm: Any, name: str, count: int, offset: tuple[float, float, float]
    ) -> tuple[FeatureInfo, list[ComponentRef]]:
        seed = self._component_by_name(asm, name)
        if seed is None:
            raise fail(
                "INVALID_ARGUMENT",
                f"Component not found: {name!r}",
                "Instance name from insert_component return value, e.g. p1-1",
                component=name,
            )
        dx, dy, dz = offset
        spacing = max(abs(dx), abs(dy), abs(dz))
        ux, uy, uz = (dx / spacing, dy / spacing, dz / spacing)
        smgr = _get(asm, "SketchManager")
        line = None
        try:
            smgr.Insert3DSketch(True)
            line = smgr.CreateLine(0.0, 0.0, 0.0, 0.05 * ux, 0.05 * uy, 0.05 * uz)
            smgr.Insert3DSketch(True)
        except Exception as exc:
            log.debug("Assembly 3D sketch direction line failed: %s", traceback.format_exc())
            raise self._map_error(exc) from exc
        if line is None:
            raise fail("SKETCH_OP_FAILED", "Could not create linear pattern direction line", "Confirm the assembly allows 3D sketch insert")
        if not self._select_component(asm, seed, mark=1):
            raise fail("SELECT_FAILED", f"Could not select component {name!r}", "Use list_components to see instance names")
        sm = _get(asm, "SelectionManager")
        data = _get(sm, "CreateSelectData")
        data.Mark = 2
        ok_dir = False
        try:
            ok_dir = bool(line.Select4(True, data))
        except Exception:
            log.debug("Direction line Select4 failed: %s", traceback.format_exc())
        if not ok_dir:
            raise fail("SELECT_FAILED", "Could not select linear pattern direction", "Direction comes from an internal 3D sketch line")
        try:
            feat = asm.FeatureManager.FeatureLinearPattern5(
                int(count), float(spacing), 0, 0.0, False, False, "", "",
                False, False, False, False, True, False,
                False, False, False, False, 0.0, 0.0, False, True,
            )
        except Exception as exc:
            log.debug("Assembly FeatureLinearPattern5 failed: %s", traceback.format_exc())
            raise self._map_error(exc) from exc
        finally:
            self._clear_selection(asm)
        if feat is None:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "Assembly linear pattern failed (API returned None)",
                "Confirm seed exists and spacing is along a single axis",
            )
        try:
            _get(asm, "ForceRebuild3", True)
        except Exception:
            log.debug("Post-pattern rebuild failed: %s", traceback.format_exc())
        real = self._feature_real_name(feat, "LocalLPattern")
        info = FeatureInfo(name=self._register("LocalLPattern", real), kind="local_l_pattern")
        refs = [
            self._component_ref_of(comp, cname)
            for cname, comp in self._assembly_component_objs(asm, top_level_only=True)
        ]
        return info, refs
        