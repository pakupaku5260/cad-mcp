"""Features · modify (fillet / chamfer / shell / rib / draft / combine / split / hole / thread).

S5-3a：fillet_blind / chamfer_blind / shell_blind

Dependencies (self, MRO):
- `_call` / `_map_error`（STAThreadMixin）
- `_select_edge_indexes` / `_select_edges` / `_select_face_indexes`（SelectionMixin）
- `_feature_real_name` / `_register` / `_features_of`（NamingMixin）
- `_has_solid`（GeometryMixin）
- `_get`（_helpers）

imports:
- `cadmcp.backend.protocol.models`（FeatureInfo）
- `cadmcp.errors`（fail）
- `.._helpers`（_get）
"""
from __future__ import annotations

import logging
import math
import traceback
from collections.abc import Sequence

from cadmcp.backend.protocol.constants import (
    COMBINE_OPS,
    HOLE_WIZARD_ENDS,
    SW_COMBINE_OP,
    SW_END_BLIND,
    SW_END_THROUGH_ALL,
)
from cadmcp.backend.protocol.geometry_engine import (
    thread_length_m,
    thread_profile_xy,
)
from cadmcp.backend.protocol.models import FeatureInfo
from cadmcp.errors import CadMcpError, fail

from .._constants import (
    _DELETE_ABSORBED,
    _DELETE_CHILDREN,
    _SUPPRESS_FEATURE,
    _THIS_CONFIGURATION,
    _UNSUPPRESS_FEATURE,
)
from .._helpers import _get

log = logging.getLogger(__name__)


class ModifyMixin:
    """Modify features (S5-3a: 3 methods)."""

    def _init_state(self) -> None:
        pass  # stateless

    def fillet_blind(
        self,
        radius_m: float,
        target: str | None = None,
        edge_indexes: Sequence[int] | None = None,
    ) -> FeatureInfo:
        def _fn() -> FeatureInfo:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            if radius_m <= 0:
                raise fail("INVALID_ARGUMENT", f"Fillet radius must be positive (internal meters): {radius_m}", "Pass radius > 0")
            selected = (
                self._select_edge_indexes(doc, edge_indexes)
                if edge_indexes is not None
                else self._select_edges(doc, target)
            )
            if selected == 0:
                raise fail(
                    "FEATURE_CREATE_FAILED", "No edges to fillet (no solid features yet)",
                    "Create a solid with extrude or revolve first; or pass edges from get_edges",
                )
            feat = None
            fm = doc.FeatureManager
            for rho in (0.0, radius_m):  # Rho should be 0 for circular fillet; keep alternate for calibration
                try:
                    feat = fm.FeatureFillet3(195, radius_m, rho, 0, 0, 0, 0, 0, 0, 0, 0, 0)
                except Exception:
                    log.debug("FeatureFillet3(rho=%s) failed: %s", rho, traceback.format_exc())
                    feat = None
                if feat is not None:
                    break
            doc.ClearSelection2(True)
            if feat is None:
                raise fail("FEATURE_CREATE_FAILED", "Fillet creation failed", "Confirm fillet radius is within machinable range")
            real = self._feature_real_name(feat, "Fillet")
            return FeatureInfo(name=self._register("Fillet", real), kind="fillet")

        return self._call(_fn)

    def chamfer_blind(
        self,
        distance_m: float,
        target: str | None = None,
        edge_indexes: Sequence[int] | None = None,
        angle_rad: float = math.pi / 4,
    ) -> FeatureInfo:
        def _fn() -> FeatureInfo:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            if distance_m <= 0:
                raise fail("INVALID_ARGUMENT", f"Chamfer distance must be positive (internal meters): {distance_m}", "Pass distance > 0")
            if angle_rad <= 0 or angle_rad >= math.pi / 2:
                raise fail("INVALID_ARGUMENT", "Chamfer angle must be between (0, 90) degrees", "Pass angle_deg, e.g. 30 or 45")
            selected = (
                self._select_edge_indexes(doc, edge_indexes)
                if edge_indexes is not None
                else self._select_edges(doc, target)
            )
            if selected == 0:
                raise fail(
                    "FEATURE_CREATE_FAILED", "No edges to chamfer (no solid features yet)",
                    "Create a solid with extrude or revolve first; or pass edges from get_edges",
                )
            try:
                # Options=4, Type=1 angle-distance; 4th param is radians
                feat = doc.FeatureManager.InsertFeatureChamfer(
                    4, 1, distance_m, angle_rad, 0.0, 0.0, 0.0, 0.0
                )
            except Exception as exc:
                log.debug("InsertFeatureChamfer failed: %s", traceback.format_exc())
                raise self._map_error(exc) from exc
            finally:
                doc.ClearSelection2(True)
            if feat is None:
                raise fail("FEATURE_CREATE_FAILED", "Chamfer creation failed", "Confirm chamfer distance is within machinable range")
            real = self._feature_real_name(feat, "Chamfer")
            return FeatureInfo(name=self._register("Chamfer", real), kind="chamfer")

        return self._call(_fn)

    def shell_blind(
        self, thickness_m: float, face_indexes: Sequence[int] | None = None,
    ) -> FeatureInfo:
        def _fn() -> FeatureInfo:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            if thickness_m <= 0:
                raise fail(
                    "INVALID_ARGUMENT", f"Shell thickness must be positive (internal meters): {thickness_m}",
                    "Pass thickness > 0",
                )
            if not self._has_solid(doc):
                raise fail(
                    "FEATURE_CREATE_FAILED", "No solid available to shell",
                    "Create a solid with extrude or revolve first",
                )
            before = {str(_get(f, "Name")) for f in self._features_of(doc)}
            if face_indexes is not None:
                if self._select_face_indexes(doc, face_indexes) == 0:
                    raise fail(
                        "FEATURE_CREATE_FAILED", "No faces available for openings",
                        "Pass face indexes from get_faces, or omit faces for closed shell",
                    )
            else:
                doc.ClearSelection2(True)  # No faces selected = closed shell
            try:
                doc.InsertFeatureShell(thickness_m, False)  # Inward
            except Exception as exc:
                log.debug("InsertFeatureShell failed: %s", traceback.format_exc())
                raise self._map_error(exc) from exc
            new = [f for f in self._features_of(doc) if str(_get(f, "Name")) not in before]
            if not new:
                raise fail(
                    "FEATURE_CREATE_FAILED", "Shell creation failed",
                    "Confirm thickness is less than half the smallest part dimension",
                )
            real = self._feature_real_name(new[-1], "Shell")
            return FeatureInfo(name=self._register("Shell", real), kind="shell")

        return self._call(_fn)

    def rib(self, thickness_m: float, sketch: str | None = None) -> FeatureInfo:
        def _fn() -> FeatureInfo:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            if thickness_m <= 0:
                raise fail("INVALID_ARGUMENT", "Rib thickness must be positive", "Pass thickness > 0")
            if not self._bodies_of(doc):
                raise fail("FEATURE_CREATE_FAILED", "Rib requires an existing solid", "extrude a base body first, then sketch the rib line")
            pending = self._pending_sketch_name
            if pending is None or (sketch is not None and sketch != pending):
                raise fail(
                    "SKETCH_NOT_FOUND",
                    f"No completed sketch available for feature (requested {sketch!r}, current: {pending}）",
                    "start_sketch → sketch_line → end_sketch → rib",
                )
            feat_sk = self._find_feature(doc, pending)
            if feat_sk is None:
                raise fail("SKETCH_NOT_FOUND", f"Sketch not found {pending}", "Use the name returned by end_sketch")
            doc.ClearSelection2(True)
            if not feat_sk.Select2(False, 0):
                raise fail("SELECT_FAILED", f"Cannot select sketch {pending}", "Confirm the sketch still exists")
            try:
                doc.EditSketch()
            except Exception:
                log.debug("Rib EditSketch failed: %s", traceback.format_exc())
            segs = self._sketch_segments(doc)
            line = None
            for seg in segs:
                if self._segment_is_construction(seg):
                    continue
                ends = self._segment_xy(seg)
                if ends is None:
                    continue
                (ax, ay), (bx, by) = ends
                if math.hypot(bx - ax, by - ay) > 1e-9:
                    line = (ax, ay, bx, by)
                    break
            if line is None:
                raise fail("FEATURE_CREATE_FAILED", "Rib sketch needs one line", "sketch_line before end_sketch")
            ax, ay, bx, by = line
            dx, dy = bx - ax, by - ay
            length = math.hypot(dx, dy)
            nx, ny = -dy / length * thickness_m / 2.0, dx / length * thickness_m / 2.0
            sm = _get(doc, "SketchManager")
            self._clear_selection(doc)
            for seg in segs:
                try:
                    seg.Select2(True, 0)
                except Exception:
                    try:
                        seg.Select(True)
                    except Exception:
                        pass
            try:
                doc.EditDelete()
            except Exception:
                log.debug("Delete original line failed: %s", traceback.format_exc())
            corners = (
                (ax + nx, ay + ny),
                (bx + nx, by + ny),
                (bx - nx, by - ny),
                (ax - nx, ay - ny),
            )
            try:
                for i in range(4):
                    x0, y0 = corners[i]
                    x1, y1 = corners[(i + 1) % 4]
                    sm.CreateLine(x0, y0, 0.0, x1, y1, 0.0)
            except Exception as exc:
                raise self._map_error(exc) from exc
            box = None
            for body in self._bodies_of(doc):
                box = self._body_bbox_m(body)
                if box is not None:
                    break
            if box is None:
                raise fail("FEATURE_CREATE_FAILED", "Rib requires an existing solid", "extrude a base body first")
            depth = box[5] - box[2]
            if depth <= 1e-9:
                depth = max(box[4] - box[1], box[3] - box[0], 1e-6)
            feat = self._feature_extrusion2(doc, True, False, 0, 0, depth, depth)
            if feat is None:
                raise fail("FEATURE_CREATE_FAILED", "Rib creation failed", "Line must lie in solid void with thickness > 0")
            self._consume_sketch_name(pending)
            real = self._feature_real_name(feat, "Rib")
            return FeatureInfo(name=self._register("Rib", real), kind="rib")

        return self._call(_fn)

    def draft(
        self, angle_rad: float, faces: Sequence[int], neutral: int, flip: bool = False,
    ) -> FeatureInfo:
        def _fn() -> FeatureInfo:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            if angle_rad <= 0 or angle_rad >= math.pi / 2:
                raise fail("INVALID_ARGUMENT", "Draft angle must be between (0, 90) degrees", "Pass angle_deg, e.g.  5")
            if not faces:
                raise fail("INVALID_ARGUMENT", "faces cannot be empty", "Pass get_faces indexes to draft")
            pool = self._part_face_objects(doc)
            if not pool:
                raise fail("FEATURE_CREATE_FAILED", "No faces available for draft", "extrude a base body first")
            idxs = [int(i) for i in faces]
            neu = int(neutral)
            n = len(pool)
            for idx in idxs + [neu]:
                if idx < 0 or idx >= n:
                    raise fail(
                        "INVALID_ARGUMENT",
                        f"Face index out of range: {idx}",
                        f"Use get_faces; valid range 0..{n - 1}",
                        index=idx,
                    )
            if neu in idxs:
                raise fail("INVALID_ARGUMENT", "Neutral face cannot be listed in faces", "Use a different plane for neutral")
            sm = _get(doc, "SelectionManager")
            doc.ClearSelection2(True)
            d_neu = _get(sm, "CreateSelectData")
            d_neu.Mark = 1
            d_face = _get(sm, "CreateSelectData")
            d_face.Mark = 2
            if not pool[neu].Select4(False, d_neu):
                raise fail("SELECT_FAILED", f"Cannot select neutral face {neu}", "Check index with get_faces")
            for fi in idxs:
                if not pool[fi].Select4(True, d_face):
                    raise fail("SELECT_FAILED", f"Cannot select draft face {fi}", "Check index with get_faces")
            try:
                feat = doc.FeatureManager.InsertMultiFaceDraft(
                    float(angle_rad), bool(flip), False, 0, False, False,
                )
            except Exception as exc:
                raise self._map_error(exc) from exc
            finally:
                self._clear_selection(doc)
            if feat is None:
                raise fail("FEATURE_CREATE_FAILED", "Draft failed", "Neutral face must be adjacent to draft faces; reduce angle_deg")
            real = self._feature_real_name(feat, "Draft")
            return FeatureInfo(name=self._register("Draft", real), kind="draft")

        return self._call(_fn)

    def combine(self, op: str, keep: int = 0) -> FeatureInfo:
        def _fn() -> FeatureInfo:
            import pythoncom
            from win32com.client import VARIANT

            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            if op not in COMBINE_OPS:
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Unknown combine operation: {op!r}",
                    f"op: {', '.join(COMBINE_OPS)}",
                    requested=op,
                )
            bodies = self._bodies_of(doc)
            if len(bodies) < 2:
                raise fail("FEATURE_CREATE_FAILED", "Combine needs at least two bodies", "Use two non-intersecting extrudes to get multiple bodies")
            if keep < 0 or keep >= len(bodies):
                raise fail(
                    "INVALID_ARGUMENT",
                    f"keep body index out of range: {keep}",
                    f"Valid range 0..{len(bodies) - 1}",
                )
            names = []
            for bd in bodies:
                try:
                    names.append(str(_get(bd, "Name")))
                except Exception:
                    names.append("")
            callout = VARIANT(pythoncom.VT_DISPATCH, None)
            ext = doc.Extension
            doc.ClearSelection2(True)
            code = SW_COMBINE_OP[op]
            if op == "cut":
                ok0 = bool(ext.SelectByID2(names[keep], "SOLIDBODY", 0, 0, 0, False, 1, callout, 0))
                oks = [ok0]
                for i, name in enumerate(names):
                    if i == keep:
                        continue
                    oks.append(bool(ext.SelectByID2(name, "SOLIDBODY", 0, 0, 0, True, 2, callout, 0)))
            else:
                oks = []
                for i, name in enumerate(names):
                    oks.append(bool(ext.SelectByID2(name, "SOLIDBODY", 0, 0, 0, i > 0, 2, callout, 0)))
            if not all(oks):
                raise fail("SELECT_FAILED", "Cannot select bodies to combine", "Use two non-intersecting extrudes to get multiple bodies")
            none = VARIANT(pythoncom.VT_DISPATCH, None)
            try:
                feat = doc.FeatureManager.InsertCombineFeature(code, none, none)
            except Exception as exc:
                raise self._map_error(exc) from exc
            finally:
                self._clear_selection(doc)
            if feat is None:
                raise fail("FEATURE_CREATE_FAILED", "Combine failed", "add for separate bodies; cut/common need intersection")
            real = self._feature_real_name(feat, "Combine")
            return FeatureInfo(name=self._register("Combine", real), kind="combine")

        return self._call(_fn)

    def split_body(self, plane: str) -> FeatureInfo:
        def _fn() -> FeatureInfo:
            import pythoncom
            from win32com.client import VARIANT

            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create a part first")
            self._require_part_doc(doc, "Use a part document to split body")
            orig = self._bodies_of(doc)
            if not orig:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "No body available to split",
                    "extrude or loft a body, then split_body",
                )
            orig_names = []
            for bd in orig:
                try:
                    orig_names.append(str(_get(bd, "Name")))
                except Exception:
                    orig_names.append("")
            doc.ClearSelection2(True)
            if not self._select_plane(doc, plane, append=False, mark=0):
                raise fail(
                    "FEATURE_NOT_FOUND",
                    f"Reference plane not found：{plane!r}",
                    "Use list_planes for reference plane names",
                    requested=plane,
                )
            fm = doc.FeatureManager
            try:
                pre = fm.PreSplitBody
                if callable(pre):
                    pre = pre()
            except Exception as exc:
                log.debug("PreSplitBody failed: %s", traceback.format_exc())
                raise self._map_error(exc) from exc
            pieces = list(pre or ())
            if len(pieces) < 2:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Reference plane did not split the body",
                    "Use a plane through the body interior, e.g. Right Plane on a centered cube",
                    requested=plane,
                )
            created = []
            try:
                for body in pieces:
                    feat = doc.CreateFeatureFromBody3(body, False, 0)
                    if feat is None:
                        raise fail(
                            "FEATURE_CREATE_FAILED",
                            "Cannot import split pieces into the part",
                            "Confirm PreSplitBody returned bodies and the part is not locked",
                        )
                    created.append(feat)
            except CadMcpError:
                raise
            except Exception as exc:
                log.debug("CreateFeatureFromBody3 failed: %s", traceback.format_exc())
                raise self._map_error(exc) from exc
            none = VARIANT(pythoncom.VT_DISPATCH, None)
            doc.ClearSelection2(True)
            oks = []
            for name in orig_names:
                if not name:
                    continue
                try:
                    oks.append(
                        bool(doc.Extension.SelectByID2(name, "SOLIDBODY", 0, 0, 0, bool(oks), 0, none, 0))
                    )
                except Exception:
                    log.debug("Select original body %s failed: %s", name, traceback.format_exc())
                    oks.append(False)
            if not any(oks):
                raise fail("SELECT_FAILED", "Cannot select original body to split", "Original body name should remain in the Bodies folder")
            del_feat = None
            try:
                del_feat = fm.InsertDeleteBody2(False)
            except Exception:
                log.debug("InsertDeleteBody2 failed: %s", traceback.format_exc())
                try:
                    del_feat = fm.InsertDeleteBody
                    if callable(del_feat):
                        del_feat = del_feat()
                except Exception as exc:
                    log.debug("InsertDeleteBody failed: %s", traceback.format_exc())
                    raise self._map_error(exc) from exc
            leftover = self._bodies_of(doc)
            if len(leftover) < 2:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Fewer than 2 bodies after split",
                    "PostSplitBody returns None in 2025; import pieces then delete original",
                )
            if del_feat is None:
                created_del = [
                    f for f in self._features_of(doc)
                    if str(_get(f, "GetTypeName2")) == "DeleteBody"
                ]
                del_feat = created_del[-1] if created_del else created[-1]
            real = self._feature_real_name(del_feat, "DeleteBody")
            return FeatureInfo(name=self._register("DeleteBody", real), kind="split_body")

        return self._call(_fn, timeout=180.0)

    def parting_line(
        self,
        pull_face: int,
        edges: Sequence[int] | None = None,
        *,
        flip: bool = False,
    ) -> FeatureInfo:
        def _fn() -> FeatureInfo:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create a part first")
            self._require_part_doc(doc, "Use a part document for mold parting line")
            if not self._bodies_of(doc):
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "No body available for parting line",
                    "extrude base body, then parting_line",
                )
            edge_pool = self._part_edge_objects(doc)
            if not edge_pool:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Solid has no usable edges",
                    "Create a body with edges, then use get_edges for indexes",
                )
            edge_idxs: list[int]
            if edges is None:
                edge_idxs = list(range(len(edge_pool)))
            else:
                if not edges:
                    raise fail(
                        "INVALID_ARGUMENT",
                        "edges cannot be empty",
                        "Omit edges to select all, or pass get_edges indexes",
                    )
                edge_idxs = [int(x) for x in edges]
            before = {
                str(_get(f, "Name"))
                for f in self._features_of(doc)
                if str(_get(f, "GetTypeName2") or "") == "MoldPartingLine"
            }
            doc.ClearSelection2(True)
            if self._select_one_face(doc, int(pull_face), mark=1, clear=False) < 1:
                raise fail(
                    "SELECT_FAILED",
                    f"Cannot select pull direction face {pull_face}",
                    "Check index with get_faces",
                )
            n_edge = self._select_edge_indexes_marked(
                doc, edge_idxs, mark=4, clear=False,
            )
            if n_edge < 1:
                raise fail(
                    "SELECT_FAILED",
                    "Cannot select parting edges",
                    "Check indexes with get_edges; cube can omit edges",
                )
            feat = None
            try:
                feat = doc.FeatureManager.InsertMoldPartingLine(bool(flip))
            except Exception as exc:
                log.debug("InsertMoldPartingLine failed: %s", traceback.format_exc())
                raise self._map_error(exc) from exc
            if feat is None:
                created = [
                    f
                    for f in self._features_of(doc)
                    if str(_get(f, "GetTypeName2") or "") == "MoldPartingLine"
                    and str(_get(f, "Name")) not in before
                ]
                feat = created[-1] if created else None
            if feat is None:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "InsertMoldPartingLine returned None",
                    "Confirm pull face and parting edge marks; complex parts need explicit edge loop",
                )
            real = self._feature_real_name(feat, "PartingLine")
            return FeatureInfo(name=self._register("PartingLine", real), kind="parting_line")

        return self._call(_fn, timeout=180.0)

    def parting_surface(
        self,
        parting_line: str | None = None,
        *,
        radiate: bool = False,
        offset_m: float = 0.0,
        knit: bool = False,
    ) -> FeatureInfo:
        def _fn() -> FeatureInfo:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create a part first")
            self._require_part_doc(doc, "Use a part document for mold parting surface")
            if radiate and offset_m < 0:
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Radiate offset cannot be negative (internal meters): {offset_m}",
                    "Pass offset ≥ 0, or radiate=false",
                )
            lines = [
                f
                for f in self._features_of(doc)
                if str(_get(f, "GetTypeName2") or "") == "MoldPartingLine"
            ]
            if parting_line is not None:
                feat_pl = self._find_feature(doc, str(parting_line))
                if feat_pl is None or str(_get(feat_pl, "GetTypeName2") or "") != "MoldPartingLine":
                    raise fail(
                        "FEATURE_NOT_FOUND",
                        f"Parting line not found {parting_line!r}",
                        "parting_line first, or check name in list_features",
                        requested=parting_line,
                    )
            else:
                if not lines:
                    raise fail(
                        "FEATURE_CREATE_FAILED",
                        "No parting line available",
                        "parting_line first, then parting_surface",
                    )
                feat_pl = lines[-1]
            before = {
                str(_get(f, "Name"))
                for f in self._features_of(doc)
                if str(_get(f, "GetTypeName2") or "") == "MoldPartingGeom"
            }
            doc.ClearSelection2(True)
            try:
                ok = bool(feat_pl.Select2(False, 0))
            except Exception:
                ok = False
            if not ok:
                raise fail(
                    "SELECT_FAILED",
                    f"Cannot select parting line {self._feature_real_name(feat_pl, '')}",
                    "Confirm parting line is still in the feature tree",
                )
            # TLB: Radiate/Smooth=I4, Reverse*/Knit=BOOL, Offset/Angle/SmoothDistance=R8
            try:
                feat = doc.FeatureManager.InsertMoldPartingSurface(
                    1 if radiate else 0,
                    False,
                    False,
                    float(offset_m) if radiate else 0.0,
                    0.0,
                    0,
                    0.0,
                    bool(knit),
                )
            except Exception as exc:
                log.debug("InsertMoldPartingSurface failed: %s", traceback.format_exc())
                raise self._map_error(exc) from exc
            if feat is None:
                created = [
                    f
                    for f in self._features_of(doc)
                    if str(_get(f, "GetTypeName2") or "") == "MoldPartingGeom"
                    and str(_get(f, "Name")) not in before
                ]
                feat = created[-1] if created else None
            if feat is None:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "InsertMoldPartingSurface returned None",
                    "Confirm valid parting line; complex molds may need shut-off surfaces",
                )
            real = self._feature_real_name(feat, "PartingSurface")
            return FeatureInfo(name=self._register("PartingSurface", real), kind="parting_surface")

        return self._call(_fn, timeout=180.0)

    def shut_off_surface(self, edges: Sequence[int] | None = None) -> FeatureInfo:
        def _fn() -> FeatureInfo:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create a part first")
            self._require_part_doc(doc, "Use a part document for mold shut-off surface")
            lines = [
                f
                for f in self._features_of(doc)
                if str(_get(f, "GetTypeName2") or "") == "MoldPartingLine"
            ]
            if not lines:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "No parting line available",
                    "parting_line first, then shut_off_surface",
                )
            edge_pool = self._part_edge_objects(doc)
            if not edge_pool:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Solid has no usable edges",
                    "Create a body with edges, then use get_edges for indexes",
                )
            if edges is None:
                edge_idxs = list(range(len(edge_pool)))
            else:
                if not edges:
                    raise fail(
                        "INVALID_ARGUMENT",
                        "edges cannot be empty",
                        "Omit edges to select all, or pass get_edges indexes",
                    )
                edge_idxs = [int(x) for x in edges]
                for ei in edge_idxs:
                    if ei < 0 or ei >= len(edge_pool):
                        raise fail(
                            "INVALID_ARGUMENT",
                            f"Edge index out of range: {ei}",
                            f"Use get_edges; valid range 0..{len(edge_pool) - 1}",
                            index=ei,
                        )
            before = {
                str(_get(f, "Name"))
                for f in self._features_of(doc)
                if str(_get(f, "GetTypeName2") or "") == "MoldShutOffSrf"
            }
            doc.ClearSelection2(True)
            n_edge = self._select_edge_indexes_marked(
                doc, edge_idxs, mark=0, clear=False,
            )
            if n_edge < 1:
                raise fail(
                    "SELECT_FAILED",
                    "Cannot select shut-off edges",
                    "Check indexes with get_edges; cube can omit edges",
                )
            feat = None
            try:
                # 2025: method creates MoldShutOffSrf but return marshaling often reports member-not-found
                feat = doc.FeatureManager.InsertMoldShutOffSurface()
            except Exception:
                log.debug("InsertMoldShutOffSurface marshaling failed (use feature tree): %s", traceback.format_exc())
                feat = None
            created = [
                f
                for f in self._features_of(doc)
                if str(_get(f, "GetTypeName2") or "") == "MoldShutOffSrf"
                and str(_get(f, "Name")) not in before
            ]
            if feat is not None:
                try:
                    if str(_get(feat, "GetTypeName2") or "") != "MoldShutOffSrf":
                        feat = None
                except Exception:
                    feat = None
            if feat is None and created:
                feat = created[-1]
            if feat is None:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "InsertMoldShutOffSurface did not create feature",
                    "Confirm parting_line exists; omit edges to select all (works for cube)",
                )
            real = self._feature_real_name(feat, "ShutOff")
            return FeatureInfo(name=self._register("ShutOff", real), kind="shut_off_surface")

        return self._call(_fn, timeout=180.0)

    def hole_wizard(
        self,
        face: int,
        diameter_m: float,
        end: str = "blind",
        depth_m: float | None = None,
        x_m: float | None = None,
        y_m: float | None = None,
    ) -> FeatureInfo:
        def _fn() -> FeatureInfo:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create a part first")
            self._require_part_doc(doc, "Use a part document for Hole Wizard")
            if end not in HOLE_WIZARD_ENDS:
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Unknown hole end condition: {end!r}",
                    f"end: {', '.join(HOLE_WIZARD_ENDS)}",
                    requested=end,
                )
            if diameter_m <= 0:
                raise fail("INVALID_ARGUMENT", "Hole diameter must be positive", "Pass diameter > 0")
            if end == "blind" and (depth_m is None or depth_m <= 0):
                raise fail("INVALID_ARGUMENT", "Blind holes need positive depth", "Pass depth > 0 when end=blind")
            if not self._bodies_of(doc):
                raise fail("FEATURE_CREATE_FAILED", "Hole Wizard needs an existing solid", "extrude base body, then select face")
            refs = self.list_faces()
            target = next((f for f in refs if f.index == int(face)), None)
            if not self._select_one_face(doc, int(face), mark=0, clear=True):
                raise fail("SELECT_FAILED", f"Cannot select face {face}", "Check index with get_faces")
            size = f"Ø{diameter_m * 1000.0:.1f}"
            end_type = SW_END_THROUGH_ALL if end == "through_all" else SW_END_BLIND
            depth = float(depth_m or 0.0)
            try:
                feat = doc.FeatureManager.HoleWizard5(
                    2, 8, 143, size, end_type,
                    float(diameter_m), depth, 0.0,
                    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                    0, False, True, True, False, False, False,
                )
            except Exception as exc:
                log.debug("HoleWizard5 failed: %s", traceback.format_exc())
                raise self._map_error(exc) from exc
            if feat is None:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    f"Hole Wizard failed (size {size} not in ISO drill chart or invalid for face)",
                    "Use chart sizes for diameter, e.g. 6 → Ø6.0; select a planar face",
                )
            u_req, v_req = x_m, y_m
            sub = _get(feat, "GetFirstSubFeature")
            moved = False
            while sub is not None and not moved:
                try:
                    if str(_get(sub, "GetTypeName2")) != "ProfileFeature":
                        sub = _get(sub, "GetNextSubFeature")
                        continue
                    sub.Select2(False, 0)
                    doc.EditSketch()
                    skobj = _get(doc, "GetActiveSketch2")
                    pts = list(_get(skobj, "GetSketchPoints") or ()) if skobj else []
                    if not pts:
                        try:
                            doc.SketchManager.InsertSketch(True)
                        except Exception:
                            pass
                        sub = _get(sub, "GetNextSubFeature")
                        continue
                    u, v = u_req, v_req
                    if u is None or v is None:
                        if target is not None and skobj is not None:
                            try:
                                xf = _get(skobj, "ModelToSketchTransform")
                                a = list(_get(xf, "ArrayData"))
                                px, py, pz = target.centroid_m
                                u = a[0] * px + a[1] * py + a[2] * pz + a[9]
                                v = a[3] * px + a[4] * py + a[5] * pz + a[10]
                            except Exception:
                                log.debug("Hole sketch coordinate transform failed: %s", traceback.format_exc())
                    if u is not None and v is not None:
                        pts[0].SetCoords(float(u), float(v), 0.0)
                        moved = True
                    doc.SketchManager.InsertSketch(True)
                except Exception:
                    log.debug("Move hole sketch point failed: %s", traceback.format_exc())
                    try:
                        doc.SketchManager.InsertSketch(True)
                    except Exception:
                        pass
                    break
                sub = _get(sub, "GetNextSubFeature") if not moved else None
            real = self._feature_real_name(feat, "Hole-Wizard")
            return FeatureInfo(name=self._register("Hole-Wizard", real), kind="hole_wizard")

        return self._call(_fn, timeout=180.0)

    def insert_thread(
        self,
        diameter_m: float,
        pitch_m: float,
        length_m: float | None = None,
        internal: bool = False,
    ) -> FeatureInfo:
        def _fn() -> FeatureInfo:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create a part first and extrude a cylinder")
            if self._sketch_open:
                raise fail(
                    "SKETCH_OP_FAILED",
                    "Sketch is still open; close it before creating a feature",
                    "Call end_sketch to close the sketch, then insert_thread",
                )
            if not self._has_solid(doc):
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "No material to cut (no solid features yet)",
                    "Extrude cylinder at nominal diameter, then insert_thread",
                )
            length = thread_length_m(pitch_m, length_m)
            pts = thread_profile_xy(diameter_m, pitch_m, internal=internal)
            r = diameter_m / 2.0
            self.begin_sketch("Front Plane")
            self.draw_circle(0.0, 0.0, r)
            self.end_sketch()
            self.create_helix(pitch_m, height_m=length)
            self.begin_sketch("Front Plane")
            for i in range(3):
                a, b = pts[i], pts[(i + 1) % 3]
                self.sketch_line(a[0], a[1], b[0], b[1])
            self.end_sketch()
            cut = self.sweep_cut()
            return FeatureInfo(name=cut.name, kind="thread")

        return self._call(_fn, timeout=180.0)

    def delete_feature(self, name: str) -> None:
        def _fn() -> None:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            real = self._aliases.get(name, name)
            feat = self._resolve_feature(doc, name)  # raises FEATURE_NOT_FOUND
            doc.ClearSelection2(True)  # Avoid deleting the user's current selection
            if not feat.Select2(False, 0):
                raise fail("SELECT_FAILED", f"Cannot select feature {name}", "Confirm the feature exists and no dialog is open")
            try:
                ok = bool(doc.Extension.DeleteSelection2(_DELETE_ABSORBED | _DELETE_CHILDREN))
            except Exception as exc:
                raise self._map_error(exc) from exc
            finally:
                doc.ClearSelection2(True)
            if not ok:
                raise self._com_failed(
                    f"Failed to delete feature: {name}",
                    "Check for an open property manager or feature locked by another object",
                )
            for k in [k for k, v in self._aliases.items() if k == name or v == real]:
                del self._aliases[k]  # Clear logical name alias mapping

        return self._call(_fn)

    def suppress_feature(self, name: str, suppress: bool = True) -> FeatureInfo:
        def _fn() -> FeatureInfo:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            feat = self._resolve_feature(doc, name)  # raises FEATURE_NOT_FOUND; supports logical names
            action = _SUPPRESS_FEATURE if suppress else _UNSUPPRESS_FEATURE
            try:
                ok = bool(feat.SetSuppression2(action, _THIS_CONFIGURATION, None))
            except Exception as exc:
                raise self._map_error(exc) from exc
            if not ok:
                verb = "Suppress" if suppress else "Unsuppress"
                raise self._com_failed(f"{verb}feature failed: {name}", "Check for an open property manager")
            return FeatureInfo(name=name, kind="unknown")

        return self._call(_fn)
