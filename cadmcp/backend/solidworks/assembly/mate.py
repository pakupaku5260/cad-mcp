"""Assembly domain · mates (S6-3b).

S6-3b: selection helpers + AddMate3 wrapper + 6 mate types + list/delete + mate feature iteration.

Dependencies (self, MRO):
- `_call` / `_map_error` (STAThreadMixin)
- `sw` (COMConnectionMixin)
- `_component_by_name` / `_asm_select_name` (ComponentMixin)
- `_component_face_objects` / `_component_edge_objects` / `_face_geometry` / `_edge_geometry` (GeometryMixin)
- `_clear_selection` (SelectionMixin)
- `_get` (_helpers)

imports:
- `cadmcp.backend.protocol.models` (EdgeRef / FaceRef / MateInfo / MateRef)
- `cadmcp.backend.protocol.parsers` (mate_need_hint / parse_mate_pair / resolve_mate_align)
- `cadmcp.backend.protocol.constants` (PLANE_ALIASES)
- `cadmcp.selectors` (resolve_mate_index)
- `cadmcp.errors` (CadMcpError / fail)
- `.._constants` (SW_DOC_ASSEMBLY / _MATE_* / _DELETE_*)
- `.._helpers` (_get)
"""
from __future__ import annotations

import logging
import traceback
from typing import Any

from cadmcp.backend.protocol.constants import PLANE_ALIASES
from cadmcp.backend.protocol.models import EdgeRef, FaceRef, MateInfo, MateRef
from cadmcp.backend.protocol.parsers import (
    mate_need_hint,
    parse_mate_pair,
    parse_mate_ref,
    resolve_mate_align,
)
from cadmcp.errors import CadMcpError, fail
from cadmcp.selectors import resolve_mate_index

from .._constants import (
    _DELETE_ABSORBED,
    _DELETE_CHILDREN,
    _MATE_ALIGN_ALIGNED,
    _MATE_ANGLE,
    _MATE_CAM,
    _MATE_COINCIDENT,
    _MATE_CONCENTRIC,
    _MATE_DISTANCE,
    _MATE_ERR_HINTS,
    _MATE_ERR_NONE,
    _MATE_GEAR,
    _MATE_SCREW,
    _MATE_SEL_MARK_CAM,
    _MATE_SEL_MARK_DEFAULT,
    _MATE_SEL_MARK_WIDTH,
    _MATE_TANGENT,
    _MATE_WIDTH,
    _MATE_WIDTH_CENTERED,
    SW_DOC_ASSEMBLY,
)
from .._helpers import _get

log = logging.getLogger(__name__)


class MateMixin:
    """Mates (S6-3b: 17 methods)."""

    def _init_state(self) -> None:
        pass  # stateless

    # ---------- selection helpers ----------

    def _select_mate_plane(self, doc: Any, plane: str, component: str, asm: str, mark: int) -> bool:
        """Append selection as '<localized plane name>@<component select string>'. Nested assemblies use GetSelectByIDString."""
        import pythoncom
        from win32com.client import VARIANT

        callout = VARIANT(pythoncom.VT_DISPATCH, None)
        tails = [f"{component}@{asm}", component]
        comp = self._component_by_name(doc, component)
        if comp is not None:
            try:
                sid = str(_get(comp, "GetSelectByIDString") or "")
            except Exception:
                sid = ""
            if sid:
                tails.insert(0, sid)
            n2 = str(_get(comp, "Name2") or "")
            if n2:
                tails.append(f"{n2}@{asm}")
                tails.append(n2)
        seen: set[str] = set()
        for local in PLANE_ALIASES[plane]:
            for tail in tails:
                full = f"{local}@{tail}"
                if full in seen:
                    continue
                seen.add(full)
                try:
                    if bool(doc.Extension.SelectByID2(full, "PLANE", 0, 0, 0, True, mark, callout, 0)):
                        return True
                except Exception:
                    log.debug("SelectByID2(%r) failed: %s", full, traceback.format_exc())
        return False

    def _select_mate_face(self, doc: Any, ref: MateRef, mark: int) -> bool:
        """Assembly context: component GetBody face, append via Select4 (verified on real hardware)."""
        comp = self._component_by_name(doc, ref.component)
        if comp is None:
            return False
        faces = self._component_face_objects(comp)
        pool: list[FaceRef] = []
        for face in faces:
            kind, centroid, normal, axis = self._face_geometry(face, comp)
            pool.append(
                FaceRef(index=len(pool), kind=kind, centroid_m=centroid, normal_m=normal, axis_m=axis)
            )
        index = resolve_mate_index(
            int(ref.face_index or 0),
            ref.coord_m,
            pool,
            component=ref.component,
            kind="face",
            filter_kind=ref.filter_kind,
        )
        data = _get(_get(doc, "SelectionManager"), "CreateSelectData")
        data.Mark = mark
        try:
            return bool(faces[index].Select4(True, data))
        except Exception:
            log.debug("Select4 face failed: %s", traceback.format_exc())
            return False

    def _select_mate_edge(self, doc: Any, ref: MateRef, mark: int) -> bool:
        """Assembly context: component GetBody edge, append via Select4."""
        comp = self._component_by_name(doc, ref.component)
        if comp is None:
            return False
        edges = self._component_edge_objects(comp)
        pool: list[EdgeRef] = []
        for edge in edges:
            kind, midpoint = self._edge_geometry(edge, comp)
            pool.append(EdgeRef(index=len(pool), kind=kind, midpoint_m=midpoint))
        index = resolve_mate_index(
            int(ref.edge_index or 0),
            ref.coord_m,
            pool,
            component=ref.component,
            kind="edge",
            filter_kind=ref.filter_kind,
        )
        data = _get(_get(doc, "SelectionManager"), "CreateSelectData")
        data.Mark = mark
        try:
            return bool(edges[index].Select4(True, data))
        except Exception:
            log.debug("Select4 edge failed: %s", traceback.format_exc())
            return False

    def _select_mate_ref(self, doc: Any, ref: MateRef, asm: str, mark: int) -> bool:
        if ref.kind == "plane":
            return self._select_mate_plane(doc, ref.plane or "", ref.component, asm, mark)
        if ref.kind == "edge":
            return self._select_mate_edge(doc, ref, mark)
        return self._select_mate_face(doc, ref, mark)

    # ---------- AddMate3 wrapper ----------

    def _add_mate(
        self,
        doc: Any,
        mate_type: int,
        *,
        distance_m: float = 0.0,
        angle_rad: float = 0.0,
        align: int = _MATE_ALIGN_ALIGNED,
        gear_ratio_num: int = 0,
        gear_ratio_den: int = 1,
        width_option: int | None = None,
    ) -> tuple[Any, int]:
        """AddMate3 for standard mates; width uses AddMate5 (needs WidthMateOption + mark 16)."""
        import pythoncom
        from win32com.client import VARIANT

        err = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        if width_option is not None:
            ret = doc.AddMate5(
                mate_type,
                align,
                False,
                distance_m,
                0.0,
                0.0,
                float(gear_ratio_num),
                float(gear_ratio_den),
                angle_rad,
                0.0,
                0.0,
                False,
                False,
                int(width_option),
                err,
            )
            return ret, int(err.value)
        ret = doc.AddMate3(
            mate_type,
            align,
            False,
            distance_m,
            0.0,
            0.0,
            int(gear_ratio_num),
            int(gear_ratio_den),
            angle_rad,
            0.0,
            0.0,
            False,
            err,
        )
        return ret, int(err.value)

    def _fail_if_suppressed(self, doc: Any, *components: str) -> None:
        for name in components:
            if not name:
                continue
            comp = self._component_by_name(doc, name)
            if comp is not None and self._component_is_suppressed(comp):
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Component is suppressed: {name!r}",
                    "Call set_suppressed(..., suppressed=false) before mating or moving",
                    component=name,
                )

    def _mate_common(
        self,
        entity1: str,
        entity2: str,
        mate_type: int,
        label: str,
        mate_name: str,
        *,
        distance_m: float = 0.0,
        angle_rad: float = 0.0,
        align: str | None = None,
        gear_ratio_num: int = 0,
        gear_ratio_den: int = 1,
        entity3: str | None = None,
    ) -> tuple[Any, int]:
        """Shared mate path. Check order matches fake._mate: doc → assembly → entity format → align → select → create."""
        doc = self.sw.ActiveDoc
        if doc is None:
            raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create an assembly first")
        try:
            doc_type = int(_get(doc, "GetType"))
        except Exception:
            doc_type = 0
        if doc_type != SW_DOC_ASSEMBLY:
            raise fail(
                "INVALID_ARGUMENT",
                "Active document is not an assembly",
                "Use new_assembly to create an assembly before mating",
            )
        ref1, ref2 = parse_mate_pair(
            entity1, entity2, allow_same_component=entity3 is not None
        )
        ref3 = parse_mate_ref(entity3) if entity3 is not None else None
        if ref3 is not None and ref3.component in (ref1.component, ref2.component) and ref1.component == ref2.component:
            # Width: two faces on one part + tab on another.
            if ref3.component == ref1.component:
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Width tab entity3 must be on a different component than {ref1.component!r}",
                    "entity1/entity2 are the width faces; entity3 is the tab on the other part",
                )
        self._fail_if_suppressed(
            doc,
            ref1.component,
            ref2.component,
            ref3.component if ref3 is not None else "",
        )
        align_i = resolve_mate_align(align, mate_name)
        asm = self._asm_select_name(str(_get(doc, "GetTitle")))
        # Width mate requires selection mark 16 (IAssemblyDoc.AddMate5 remarks).
        sel_mark = _MATE_SEL_MARK_WIDTH if mate_type == _MATE_WIDTH else _MATE_SEL_MARK_DEFAULT
        self._clear_selection(doc)
        try:
            ok1 = self._select_mate_ref(doc, ref1, asm, sel_mark)
            ok2 = ok1 and self._select_mate_ref(doc, ref2, asm, sel_mark)
            ok3 = True
            if ref3 is not None:
                ok3 = ok2 and self._select_mate_ref(doc, ref3, asm, sel_mark)
        except CadMcpError:
            self._clear_selection(doc)
            raise
        if not (ok1 and ok2 and ok3):
            self._clear_selection(doc)
            if not ok1:
                missing = ref1.component
            elif not ok2:
                missing = ref2.component
            else:
                missing = ref3.component if ref3 is not None else "?"
            raise fail(
                "INVALID_ARGUMENT",
                f"Could not select mate entities ({entity1!r} / {entity2!r}): component not found: {missing}",
                "Instance names come from insert_component; face/edge indices from get_component_faces / get_component_edges",
            )
        try:
            mate, err = self._add_mate(
                doc,
                mate_type,
                distance_m=distance_m,
                angle_rad=angle_rad,
                align=align_i,
                gear_ratio_num=gear_ratio_num,
                gear_ratio_den=gear_ratio_den,
                width_option=_MATE_WIDTH_CENTERED if mate_type == _MATE_WIDTH else None,
            )
        except Exception as exc:
            raise self._map_error(exc) from exc
        finally:
            self._clear_selection(doc)
        if mate is None:
            hint = (
                mate_need_hint(mate_name)
                if err == 2
                else _MATE_ERR_HINTS.get(err, "Check selected entity types and mate parameters")
            )
            raise fail("FEATURE_CREATE_FAILED", f"Failed to create {label} mate (status code {err})", hint)
        # AddMate3 may return a mate object with non-1 status (e.g. over-defined): mate is still created.
        # Rebuild before reading Transform2 so get_component reflects the mated pose.
        try:
            _get(doc, "EditRebuild3")
        except Exception:
            log.debug("Post-mate rebuild failed: %s", traceback.format_exc())
        return mate, err

    def _named_mate(self, mate: Any, err: int, mate_type: str, default: str) -> MateInfo:
        name = default
        try:
            name = str(_get(mate, "Name")) or name
        except Exception:
            pass
        return MateInfo(
            name=name,
            mate_type=mate_type,
            sw_error=None if err == _MATE_ERR_NONE else int(err),
        )

    # ---------- 6 mate types ----------

    def mate_concentric(self, entity1: str, entity2: str, align: str | None = None) -> MateInfo:
        def _fn() -> MateInfo:
            mate, err = self._mate_common(
                entity1, entity2, _MATE_CONCENTRIC, "concentric", "concentric", align=align
            )
            return self._named_mate(mate, err, "concentric", "Concentric")

        return self._call(_fn)

    def mate_coincident(self, entity1: str, entity2: str, align: str | None = None) -> MateInfo:
        def _fn() -> MateInfo:
            mate, err = self._mate_common(
                entity1, entity2, _MATE_COINCIDENT, "coincident", "coincident", align=align
            )
            return self._named_mate(mate, err, "coincident", "Coincident")

        return self._call(_fn)

    def mate_distance(
        self, entity1: str, entity2: str, distance_m: float, align: str | None = None
    ) -> MateInfo:
        def _fn() -> MateInfo:
            if distance_m < 0:
                raise fail("INVALID_ARGUMENT", "Distance cannot be negative", "Pass distance >= 0")
            mate, err = self._mate_common(
                entity1, entity2, _MATE_DISTANCE, "distance", "distance",
                distance_m=distance_m, align=align,
            )
            return self._named_mate(mate, err, "distance", "Distance")

        return self._call(_fn)

    def mate_angle(
        self, entity1: str, entity2: str, angle_rad: float, align: str | None = None
    ) -> MateInfo:
        def _fn() -> MateInfo:
            mate, err = self._mate_common(
                entity1, entity2, _MATE_ANGLE, "angle", "angle",
                angle_rad=angle_rad, align=align,
            )
            return self._named_mate(mate, err, "angle", "Angle")

        return self._call(_fn)

    def mate_tangent(self, entity1: str, entity2: str, align: str | None = None) -> MateInfo:
        def _fn() -> MateInfo:
            mate, err = self._mate_common(
                entity1, entity2, _MATE_TANGENT, "tangent", "tangent", align=align
            )
            return self._named_mate(mate, err, "tangent", "Tangent")

        return self._call(_fn)

    def mate_screw(
        self, entity1: str, entity2: str, pitch_m: float, align: str | None = None
    ) -> MateInfo:
        def _fn() -> MateInfo:
            if pitch_m <= 0:
                raise fail("INVALID_ARGUMENT", "Pitch must be positive", "Pass pitch > 0")
            mate, err = self._mate_common(
                entity1, entity2, _MATE_SCREW, "screw", "screw",
                distance_m=pitch_m, align=align,
            )
            return self._named_mate(mate, err, "screw", "ScrewMate")

        return self._call(_fn)

    def mate_gear(
        self,
        entity1: str,
        entity2: str,
        ratio_num: int,
        ratio_den: int,
        align: str | None = None,
    ) -> MateInfo:
        def _fn() -> MateInfo:
            if int(ratio_num) <= 0 or int(ratio_den) <= 0:
                raise fail(
                    "INVALID_ARGUMENT",
                    "Gear ratio numerator and denominator must be positive integers",
                    "Pass ratio_num > 0 and ratio_den > 0",
                )
            mate, err = self._mate_common(
                entity1,
                entity2,
                _MATE_GEAR,
                "gear",
                "gear",
                align=align,
                gear_ratio_num=int(ratio_num),
                gear_ratio_den=int(ratio_den),
            )
            return self._named_mate(mate, err, "gear", "GearMate")

        return self._call(_fn)

    def mate_cam(
        self, entity1: str, entity2: str, align: str | None = None
    ) -> MateInfo:
        def _fn() -> MateInfo:
            import pythoncom

            # CAM-02 BLOCKED (S0): CreateMateData + EntitiesToMate[1/8] assigns, but CreateMate
            # returns None on SW2025. AddMate5(swMateCAMFOLLOWER) crashes the process (CAM-01) —
            # never call AddMate5 for cam on the formal path.
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create an assembly first")
            try:
                doc_type = int(_get(doc, "GetType"))
            except Exception:
                doc_type = 0
            if doc_type != SW_DOC_ASSEMBLY:
                raise fail(
                    "INVALID_ARGUMENT",
                    "Active document is not an assembly",
                    "Use new_assembly to create an assembly before mating",
                )
            ref1, ref2 = parse_mate_pair(entity1, entity2)
            self._fail_if_suppressed(doc, ref1.component, ref2.component)
            align_i = resolve_mate_align(align, "cam")
            if ref1.kind != "face" or ref2.kind != "face":
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Failed to create cam mate (status code 2)",
                    mate_need_hint("cam", [ref1.kind, ref2.kind]),
                )
            try:
                f_cam = self._mate_face_object(doc, ref1)
                f_fol = self._mate_face_object(doc, ref2)
            except CadMcpError:
                raise
            except Exception as exc:
                raise self._map_error(exc) from exc
            try:
                data = doc.CreateMateData(_MATE_CAM)
                # ICamFollowerMateFeatureData.EntitiesToMate[EntityType] = IDispatch (typelib).
                # EntityType uses the AddMate5 selection marks: cam=1, follower=8.
                ole = data._oleobj_
                ole.InvokeTypes(
                    1,
                    0,
                    pythoncom.DISPATCH_PROPERTYPUT,
                    (24, 0),
                    ((3, 1), (9, 1)),
                    _MATE_SEL_MARK_DEFAULT,
                    f_cam,
                )
                ole.InvokeTypes(
                    1,
                    0,
                    pythoncom.DISPATCH_PROPERTYPUT,
                    (24, 0),
                    ((3, 1), (9, 1)),
                    _MATE_SEL_MARK_CAM,
                    f_fol,
                )
                data.MateAlignment = align_i
                feat = doc.CreateMate(data)
            except Exception as exc:
                raise self._map_error(exc) from exc
            if feat is None or feat is False:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Failed to create cam mate (status code 0)",
                    mate_need_hint("cam"),
                )
            try:
                _get(doc, "EditRebuild3")
            except Exception:
                log.debug("Post-mate rebuild failed: %s", traceback.format_exc())
            return self._named_mate(feat, _MATE_ERR_NONE, "cam", "CamMate")

        return self._call(_fn)

    def _mate_face_object(self, doc: Any, ref: MateRef) -> Any:
        """Resolve a face/plane MateRef to an IFace2 in assembly context (body faces only)."""
        if ref.kind not in ("face",):
            raise fail(
                "INVALID_ARGUMENT",
                "Mate entity must be a body face (#plane:N / #cylinder:N / #face:N), not a datum plane or edge",
                "Use get_component_faces and pass '#plane:<index>' / '#cylinder:<index>'",
            )
        comp = self._component_by_name(doc, ref.component)
        if comp is None:
            raise fail(
                "INVALID_ARGUMENT",
                f"Component not found: {ref.component!r}",
                "Instance names come from insert_component",
                component=ref.component,
            )
        faces = self._component_face_objects(comp)
        pool: list[FaceRef] = []
        for face in faces:
            kind, centroid, normal, axis = self._face_geometry(face, comp)
            pool.append(
                FaceRef(index=len(pool), kind=kind, centroid_m=centroid, normal_m=normal, axis_m=axis)
            )
        index = resolve_mate_index(
            int(ref.face_index or 0),
            ref.coord_m,
            pool,
            component=ref.component,
            kind="face",
            filter_kind=ref.filter_kind,
        )
        return faces[index]

    def mate_width(
        self,
        entity1: str,
        entity2: str,
        entity3: str,
        align: str | None = None,
    ) -> MateInfo:
        def _fn() -> MateInfo:
            import pythoncom
            from win32com.client import VARIANT

            # Width on SW2025: CreateMateData + WidthSelection(2) + TabSelection(2).
            # AddMate5 with mark 16 returns err=0 / None on this build; CreateMate works.
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create an assembly first")
            try:
                doc_type = int(_get(doc, "GetType"))
            except Exception:
                doc_type = 0
            if doc_type != SW_DOC_ASSEMBLY:
                raise fail(
                    "INVALID_ARGUMENT",
                    "Active document is not an assembly",
                    "Use new_assembly to create an assembly before mating",
                )
            resolve_mate_align(align, "width")
            ref1, ref2 = parse_mate_pair(entity1, entity2, allow_same_component=True)
            ref3 = parse_mate_ref(entity3)
            if ref1.component == ref2.component == ref3.component:
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Width tab entity3 must be on a different component than {ref1.component!r}",
                    "entity1/entity2 are the width faces; entity3 is the tab on the other part",
                )
            self._fail_if_suppressed(doc, ref1.component, ref2.component, ref3.component)
            try:
                w1 = self._mate_face_object(doc, ref1)
                w2 = self._mate_face_object(doc, ref2)
                tab = self._mate_face_object(doc, ref3)
            except CadMcpError:
                raise
            except Exception as exc:
                raise self._map_error(exc) from exc
            try:
                data = doc.CreateMateData(_MATE_WIDTH)
                data.ConstraintType = _MATE_WIDTH_CENTERED
                width_var = VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, (w1, w2))
                # API wants two tab faces; one tab face is duplicated (verified on SW2025).
                tab_var = VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, (tab, tab))
                try:
                    data.WidthSelection = width_var
                except Exception:
                    data.SetWidthSelection(width_var)
                try:
                    data.TabSelection = tab_var
                except Exception:
                    data.SetTabSelection(tab_var)
                feat = doc.CreateMate(data)
            except Exception as exc:
                raise self._map_error(exc) from exc
            if feat is None:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Failed to create width mate (status code 0)",
                    mate_need_hint("width"),
                )
            try:
                _get(doc, "EditRebuild3")
            except Exception:
                log.debug("Post-mate rebuild failed: %s", traceback.format_exc())
            return self._named_mate(feat, _MATE_ERR_NONE, "width", "WidthMate")

        return self._call(_fn)

    # ---------- feature iteration ----------

    def _iter_mate_features(self, doc: Any):
        """Mate features: sub-features of MateGroup / MateGrp in the feature tree (real-hardware path)."""
        feat = _get(doc, "FirstFeature")
        while feat is not None:
            tname = str(_get(feat, "GetTypeName2") or "")
            if tname in ("MateGroup", "MateGrp"):
                sub = _get(feat, "GetFirstSubFeature")
                while sub is not None:
                    yield sub
                    sub = _get(sub, "GetNextSubFeature")
            feat = _get(feat, "GetNextFeature")

    @staticmethod
    def _mate_type_from_sw(tname: str) -> str:
        lower = tname.lower()
        # Localized feature type names (CN) seen on SW2025 UI.
        if "宽度" in tname or "width" in lower:
            return "width"
        if "齿轮" in tname or "gear" in lower:
            return "gear"
        if "凸轮" in tname or "cam" in lower:
            return "cam"
        for key in (
            "concentric",
            "coincident",
            "distance",
            "angle",
            "tangent",
            "screw",
        ):
            if key in lower:
                return key
        return tname or "unknown"

    # ---------- list / delete ----------

    def list_mates(self) -> list[MateInfo]:
        def _fn() -> list[MateInfo]:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create an assembly first")
            try:
                doc_type = int(_get(doc, "GetType"))
            except Exception:
                doc_type = 0
            if doc_type != SW_DOC_ASSEMBLY:
                raise fail(
                    "INVALID_ARGUMENT",
                    "Active document is not an assembly",
                    "Use new_assembly to create an assembly before listing mates",
                )
            out: list[MateInfo] = []
            for feat in self._iter_mate_features(doc):
                name = str(_get(feat, "Name") or "")
                tname = str(_get(feat, "GetTypeName2") or "")
                out.append(MateInfo(name=name, mate_type=self._mate_type_from_sw(tname)))
            return out

        return self._call(_fn)

    def delete_mate(self, name: str) -> None:
        def _fn() -> None:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            try:
                doc_type = int(_get(doc, "GetType"))
            except Exception:
                doc_type = 0
            if doc_type != SW_DOC_ASSEMBLY:
                raise fail(
                    "INVALID_ARGUMENT",
                    "Active document is not an assembly",
                    "Use new_assembly to create an assembly before deleting mates",
                )
            found = None
            for feat in self._iter_mate_features(doc):
                if str(_get(feat, "Name") or "") == name:
                    found = feat
                    break
            if found is None:
                raise fail(
                    "FEATURE_NOT_FOUND",
                    f"Mate not found: {name!r}",
                    "Use list_mates to see mate names",
                    name=name,
                )
            doc.ClearSelection2(True)
            if not found.Select2(False, 0):
                raise fail("SELECT_FAILED", f"Could not select mate {name}", "Confirm the mate exists and no dialog is open")
            try:
                ok = bool(doc.Extension.DeleteSelection2(_DELETE_ABSORBED | _DELETE_CHILDREN))
            except Exception as exc:
                raise self._map_error(exc) from exc
            finally:
                doc.ClearSelection2(True)
            if not ok:
                raise self._com_failed(
                    f"Failed to delete mate: {name}", "Check for open dialogs or whether the mate is locked"
                )

        return self._call(_fn)
