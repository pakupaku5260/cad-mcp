"""Features · sheet metal (base flange / edge flange / unfold).

S5-7：base_flange / edge_flange / sheet_metal_unfold

Dependencies (self, MRO):
- `_call` / `_map_error`（STAThreadMixin）
- `_require_part_doc`（InfrastructureMixin）
- `_select_pending_sketch` / `_consume_sketch_name` / `_pending_sketch_name`（SketchMixin）
- `_part_edge_objects` / `_edge_geometry`（GeometryMixin）
- `_features_of` / `_feature_real_name` / `_register`（NamingMixin）
- `_get`（_helpers）

imports:
- `cadmcp.backend.protocol.models`（FeatureInfo / SheetMetalFlatSI）
- `cadmcp.errors`（CadMcpError / fail）
- `.._helpers`（_get）
"""
from __future__ import annotations

import logging
import math
import traceback
from pathlib import Path

from cadmcp.backend.protocol.models import FeatureInfo, SheetMetalFlatSI
from cadmcp.errors import CadMcpError, fail

from .._helpers import _get

log = logging.getLogger(__name__)


class SheetMetalMixin:
    """Sheet metal (S5-7: 3 methods)."""

    def _init_state(self) -> None:
        pass  # stateless

    def base_flange(
        self,
        thickness_m: float,
        radius_m: float | None = None,
        sketch: str | None = None,
    ) -> FeatureInfo:
        def _fn() -> FeatureInfo:
            import pythoncom
            from win32com.client import VARIANT

            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create a part first")
            self._require_part_doc(doc, "Use a part document for base flange")
            if thickness_m <= 0:
                raise fail("INVALID_ARGUMENT", "Sheet metal thickness must be positive", "Pass thickness > 0")
            radius = 0.5 * float(thickness_m) if radius_m is None else float(radius_m)
            if radius < 0:
                raise fail("INVALID_ARGUMENT", "Bend radius cannot be negative", "Omit radius to use 0.5×thickness")
            self._select_pending_sketch(doc, sketch)
            none = VARIANT(pythoncom.VT_DISPATCH, None)
            # UseDefaultRelief + ReliefNone; closed profile ExtrudeDist is 0.
            try:
                feat = doc.FeatureManager.InsertSheetMetalBaseFlange2(
                    float(thickness_m), False, float(radius), 0.0, 0.0, False, 0, 0, 0, none,
                    True, 4, 0.0, 0.0, 0.5, True, False, True, True,
                )
            except Exception as exc:
                log.debug("InsertSheetMetalBaseFlange2 failed: %s", traceback.format_exc())
                raise self._map_error(exc) from exc
            if feat is None:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Base flange failed (API returned None)",
                    "end_sketch a closed profile, then base_flange",
                )
            real = self._feature_real_name(feat, "Base-Flange")
            self._consume_sketch_name(self._pending_sketch_name)
            self._pending_sketch_name = None
            return FeatureInfo(name=self._register("Base-Flange", real), kind="base_flange")

        return self._call(_fn, timeout=180.0)

    def edge_flange(
        self,
        edge: int,
        length_m: float,
        angle_rad: float = math.pi / 2,
        radius_m: float | None = None,
    ) -> FeatureInfo:
        def _fn() -> FeatureInfo:
            import pythoncom
            from win32com.client import VARIANT

            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create a part first")
            self._require_part_doc(doc, "Use a part document for edge flange")
            if length_m <= 0:
                raise fail("INVALID_ARGUMENT", "Edge flange length must be positive", "Pass length > 0")
            if angle_rad <= 0 or angle_rad >= math.pi:
                raise fail("INVALID_ARGUMENT", "Edge flange angle must be in (0, 180) degrees", "Pass angle_deg, e.g.  90")
            sm_ok = False
            for feat in self._features_of(doc):
                try:
                    if str(_get(feat, "GetTypeName2")) in ("SMBaseFlange", "SheetMetal", "EdgeFlange"):
                        sm_ok = True
                        break
                except Exception:
                    continue
            if not sm_ok:
                raise fail("FEATURE_CREATE_FAILED", "Edge flange needs a base flange", "Closed sketch then base_flange")
            none = VARIANT(pythoncom.VT_DISPATCH, None)
            pool = self._part_edge_objects(doc)
            if not pool:
                raise fail("FEATURE_CREATE_FAILED", "No edges available for flange", "base_flange first")
            idx = int(edge)
            if idx < 0 or idx >= len(pool):
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Edge index out of range: {idx}",
                    f"Use get_edges; valid range 0..{len(pool) - 1}",
                    index=idx,
                )
            sm = _get(doc, "SelectionManager")
            data = _get(sm, "CreateSelectData")
            data.Mark = 0
            doc.ClearSelection2(True)
            try:
                ok = bool(pool[idx].Select4(False, data))
            except Exception:
                ok = False
            if not ok:
                raise fail("SELECT_FAILED", f"Cannot select edge {idx}", "Check index with get_edges")
            try:
                sk = doc.InsertSketchForEdgeFlange(pool[idx], float(angle_rad), False)
            except Exception as exc:
                log.debug("InsertSketchForEdgeFlange failed: %s", traceback.format_exc())
                raise self._map_error(exc) from exc
            try:
                doc.SketchManager.InsertSketch(True)
            except Exception:
                log.debug("Close edge-flange sketch failed: %s", traceback.format_exc())
            opt = 1 | 64 | 128  # default radius + relief ratio + default relief
            radius = 0.0005 if radius_m is None else float(radius_m)
            try:
                feat = doc.FeatureManager.InsertSheetMetalEdgeFlange(
                    pool[idx], sk, opt, float(angle_rad), float(radius), 2, float(length_m),
                    4, 0.5, 0.0, 0.0, 0, none,
                )
            except Exception as exc:
                log.debug("InsertSheetMetalEdgeFlange failed: %s", traceback.format_exc())
                raise self._map_error(exc) from exc
            if feat is None:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Edge flange failed (API returned None)",
                    "Pick long edge on sheet outline; adjust OffsetDistance after InsertSketchForEdgeFlange",
                )
            try:
                dataf = _get(feat, "GetDefinition")
                dataf.AccessSelections(doc, none)
                dataf.OffsetDistance = float(length_m)
                dataf.BendAngle = float(angle_rad)
                if radius_m is not None:
                    dataf.UseDefaultBendRadius = False
                    dataf.BendRadius = float(radius)
                if not bool(feat.ModifyDefinition(dataf, doc, none)):
                    raise fail("FEATURE_CREATE_FAILED", "Edge flange length update failed", "Check length and selected edge")
                try:
                    dataf.ReleaseSelectionAccess()
                except Exception:
                    pass
            except CadMcpError:
                raise
            except Exception as exc:
                log.debug("EdgeFlange ModifyDefinition failed: %s", traceback.format_exc())
                raise self._map_error(exc) from exc
            real = self._feature_real_name(feat, "Edge-Flange")
            return FeatureInfo(name=self._register("Edge-Flange", real), kind="edge_flange")

        return self._call(_fn, timeout=180.0)

    def sheet_metal_unfold(self) -> SheetMetalFlatSI:
        def _fn() -> SheetMetalFlatSI:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create a part first")
            self._require_part_doc(doc, "Use a part document to unfold sheet metal")
            target = None
            has_sm = False
            for feat in self._features_of(doc):
                try:
                    tname = str(_get(feat, "GetTypeName2") or "")
                except Exception:
                    continue
                if tname in ("SMBaseFlange", "SheetMetal", "EdgeFlange"):
                    has_sm = True
                if tname == "FlatPattern":
                    target = feat
            if not has_sm:
                raise fail("FEATURE_CREATE_FAILED", "No sheet metal to unfold", "base_flange first")
            if target is not None:
                try:
                    target.Select2(False, 0)
                    _get(doc, "EditUnsuppress2")
                except Exception:
                    log.debug("Unsuppress flat pattern failed: %s", traceback.format_exc())
            try:
                _get(doc, "SetBendState", 2)
            except Exception:
                log.debug("SetBendState Flattened failed: %s", traceback.format_exc())
            try:
                _get(doc, "ForceRebuild3", True)
            except Exception:
                pass
            box = list(_get(doc, "GetPartBox", True) or ())
            if len(box) < 6:
                raise fail("FEATURE_CREATE_FAILED", "Cannot read bounding box after unfold", "Confirm flat pattern is unsuppressed")
            dx = abs(float(box[3]) - float(box[0]))
            dy = abs(float(box[4]) - float(box[1]))
            dz = abs(float(box[5]) - float(box[2]))
            extents = sorted((dx, dy, dz), reverse=True)
            k = 0.5
            try:
                folder = _get(doc.FeatureManager, "GetSheetMetalFolder")
                metals = list(_get(folder, "GetSheetMetals") or ()) if folder is not None else []
                if metals:
                    k = float(_get(_get(metals[0], "GetDefinition"), "KFactor"))
            except Exception:
                log.debug("Read KFactor failed: %s", traceback.format_exc())
            return SheetMetalFlatSI(
                length_m=extents[0],
                width_m=extents[1],
                thickness_m=extents[2],
                k_factor=k,
            )

        return self._call(_fn, timeout=180.0)

    def miter_flange(
        self,
        edges: list[int],
        length_m: float,
        angle_rad: float = math.pi / 2,
        radius_m: float | None = None,
    ) -> FeatureInfo:
        """Miter flange: three-point normal plane + outward profile at edge end, then InsertSheetMetalMiterFlange (14 params).

        Selection: edges Mark=1, sketch Mark=0. angle: 0°=in-plane binormal, 90° (default)=sheet normal.
        """

        def _fn() -> FeatureInfo:
            import pythoncom
            from win32com.client import VARIANT

            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create a part first")
            self._require_part_doc(doc, "Use a part document for miter flange")
            if length_m <= 0:
                raise fail("INVALID_ARGUMENT", "Miter flange length must be positive", "Pass length > 0")
            if not edges:
                raise fail("INVALID_ARGUMENT", "Miter flange needs at least one edge", "Pass edges=[...]")
            pool = self._part_edge_objects(doc)
            sm = _get(doc, "SelectionManager")
            data = _get(sm, "CreateSelectData")
            none = VARIANT(pythoncom.VT_DISPATCH, None)

            idxs: list[int] = []
            for raw in edges:
                j = int(raw)
                if j < 0 or j >= len(pool):
                    raise fail(
                        "INVALID_ARGUMENT",
                        f"Edge index out of range: {j}",
                        f"Valid range 0..{len(pool) - 1}",
                    )
                idxs.append(j)

            primary = pool[idxs[0]]
            try:
                params = list(_get(primary, "GetCurveParams2") or ())
            except Exception:
                params = []
            if len(params) < 6:
                raise fail("FEATURE_CREATE_FAILED", "Cannot read miter path edge", "Pick a different profile edge")
            p0 = (float(params[0]), float(params[1]), float(params[2]))
            p1 = (float(params[3]), float(params[4]), float(params[5]))
            mid = ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2, (p0[2] + p1[2]) / 2)
            tangent = self._unit_dir((p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]))
            if tangent is None:
                raise fail("FEATURE_CREATE_FAILED", "Miter path edge degenerates", "Pick another straight profile edge")

            # Largest adjacent planar face sets normal reference
            normal = None
            face_cent = None
            best_area = -1.0
            try:
                adj = [f for f in list(_get(primary, "GetTwoAdjacentFaces2") or ()) if f is not None]
            except Exception:
                adj = []
            for face in adj:
                try:
                    nrm = self._face_normal(face)
                    if nrm is None:
                        continue
                    area = float(_get(face, "GetArea") or 0.0)
                    _kind, cent, _n, _ax = self._face_geometry(face)
                    if area >= best_area:
                        best_area = area
                        normal = nrm
                        face_cent = cent
                except Exception:
                    continue
            if normal is None:
                normal = (0.0, 0.0, 1.0)

            binormal = self._unit_dir(
                (
                    tangent[1] * normal[2] - tangent[2] * normal[1],
                    tangent[2] * normal[0] - tangent[0] * normal[2],
                    tangent[0] * normal[1] - tangent[1] * normal[0],
                )
            )
            if binormal is None:
                raise fail("FEATURE_CREATE_FAILED", "Cannot build miter outward direction", "Pick an edge on the sheet outline")
            if face_cent is not None:
                to_cent = (
                    face_cent[0] - mid[0],
                    face_cent[1] - mid[1],
                    face_cent[2] - mid[2],
                )
                if (
                    binormal[0] * to_cent[0]
                    + binormal[1] * to_cent[1]
                    + binormal[2] * to_cent[2]
                    > 0
                ):
                    binormal = (-binormal[0], -binormal[1], -binormal[2])

            # Three-point plane: end / end+N / end+B — perpendicular to path edge through endpoint
            span = 0.01
            pts = (
                p0,
                (p0[0] + normal[0] * span, p0[1] + normal[1] * span, p0[2] + normal[2] * span),
                (
                    p0[0] + binormal[0] * span,
                    p0[1] + binormal[1] * span,
                    p0[2] + binormal[2] * span,
                ),
            )
            try:
                plane = self._insert_points_plane(doc, pts)
            except CadMcpError:
                raise
            except Exception as exc:
                log.debug("Miter three-point plane failed: %s", traceback.format_exc())
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Cannot create miter flange normal plane",
                    "Confirm path edge is straight sheet-outline edge",
                ) from exc

            doc.ClearSelection2(True)
            try:
                ok_plane = bool(plane.Select2(False, 0))
            except Exception:
                ok_plane = False
            if not ok_plane:
                raise fail("FEATURE_CREATE_FAILED", "Cannot select miter flange normal plane", "Retry or pick a different edge")

            try:
                doc.SketchManager.InsertSketch(True)
                sk = _get(doc, "GetActiveSketch2") or _get(doc.SketchManager, "ActiveSketch")
                if sk is None:
                    raise fail("FEATURE_CREATE_FAILED", "Cannot open miter profile sketch", "Check normal faces")
                xf = list(_get(_get(sk, "ModelToSketchTransform"), "ArrayData"))
                u0 = xf[0] * p0[0] + xf[1] * p0[1] + xf[2] * p0[2] + xf[9]
                v0 = xf[3] * p0[0] + xf[4] * p0[1] + xf[5] * p0[2] + xf[10]
                n_u = xf[0] * normal[0] + xf[1] * normal[1] + xf[2] * normal[2]
                n_v = xf[3] * normal[0] + xf[4] * normal[1] + xf[5] * normal[2]
                b_u = xf[0] * binormal[0] + xf[1] * binormal[1] + xf[2] * binormal[2]
                b_v = xf[3] * binormal[0] + xf[4] * binormal[1] + xf[5] * binormal[2]
                n_len = math.hypot(n_u, n_v)
                b_len = math.hypot(b_u, b_v)
                if n_len < 1e-9 or b_len < 1e-9:
                    raise fail(
                        "FEATURE_CREATE_FAILED",
                        "Miter profile direction projection degenerate",
                        "Pick outline edge with clearer orthogonality to sheet",
                    )
                n_u, n_v = n_u / n_len, n_v / n_len
                b_u, b_v = b_u / b_len, b_v / b_len
                # 0°→in-plane binormal B; 90° (default)→sheet normal N (verified on hardware)
                ang = float(angle_rad)
                du = math.cos(ang) * b_u + math.sin(ang) * n_u
                dv = math.cos(ang) * b_v + math.sin(ang) * n_v
                dlen = math.hypot(du, dv)
                if dlen < 1e-9:
                    raise fail("FEATURE_CREATE_FAILED", "Invalid miter profile direction", "Check angle_deg")
                scale = float(length_m) / dlen
                du, dv = du * scale, dv * scale
                line = doc.SketchManager.CreateLine(
                    float(u0), float(v0), 0.0, float(u0 + du), float(v0 + dv), 0.0
                )
                doc.SketchManager.InsertSketch(True)
            except CadMcpError:
                raise
            except Exception as exc:
                log.debug("Miter flange profile sketch failed: %s", traceback.format_exc())
                try:
                    doc.SketchManager.InsertSketch(True)
                except Exception:
                    pass
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Cannot create miter flange profile sketch",
                    "Confirm path endpoint projects onto normal plane",
                ) from exc
            if line is None:
                raise fail("FEATURE_CREATE_FAILED", "Cannot create miter flange profile sketch", "Check length/angle")

            # Reselect: all path edges Mark=1 + latest ProfileFeature Mark=0
            doc.ClearSelection2(True)
            for i, idx in enumerate(idxs):
                data.Mark = 1
                if not bool(pool[idx].Select4(i > 0, data)):
                    raise fail("SELECT_FAILED", f"Cannot select edge {idx}", "Check with get_edges")
            sketch_feat = None
            for feat in self._features_of(doc):
                try:
                    if str(_get(feat, "GetTypeName2") or "") == "ProfileFeature":
                        sketch_feat = feat
                except Exception:
                    continue
            if sketch_feat is None:
                raise fail("FEATURE_CREATE_FAILED", "Miter profile sketch not found", "Retry miter_flange")
            try:
                data.Mark = 0
                if not bool(sketch_feat.Select2(True, data)):
                    sketch_feat.Select2(True, 0)
            except Exception:
                try:
                    sketch_feat.Select2(True, 0)
                except Exception:
                    log.debug("Select miter profile sketch failed: %s", traceback.format_exc())
                    raise fail("SELECT_FAILED", "Cannot select miter profile sketch", "Retry") from None

            radius = 0.0005 if radius_m is None else float(radius_m)
            use_default_radius = radius_m is None
            try:
                feat = doc.FeatureManager.InsertSheetMetalMiterFlange(
                    bool(use_default_radius),
                    float(radius),
                    0.0005,  # RipGap
                    True,  # UseDefaultRelief
                    True,  # UseReliefRatio
                    0.5,
                    0.0,
                    0.0,
                    0,  # ReliefType
                    True,  # TrimSideBends
                    0,  # FlangePos
                    0.0,
                    0.0,
                    none,
                )
            except Exception as exc:
                log.debug("InsertSheetMetalMiterFlange failed: %s", traceback.format_exc())
                raise self._map_error(exc) from exc
            if feat is None:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Miter flange failed",
                    "Need base flange; pick outer outline edge; profile must not cut into solid",
                )
            real = self._feature_real_name(feat, "Miter-Flange")
            return FeatureInfo(name=self._register("Miter-Flange", real), kind="miter_flange")

        return self._call(_fn, timeout=180.0)

    def hem_flange(
        self,
        edge: int,
        length_m: float,
        radius_m: float | None = None,
    ) -> FeatureInfo:
        """Hem: InsertSheetMetalHem2 (2025 typelib 16 params; Closed=0)."""

        def _fn() -> FeatureInfo:
            import pythoncom
            from win32com.client import VARIANT

            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create a part first")
            self._require_part_doc(doc, "Use a part document for hem")
            if length_m <= 0:
                raise fail("INVALID_ARGUMENT", "Hem length must be positive", "Pass length > 0")
            pool = self._part_edge_objects(doc)
            idx = int(edge)
            if idx < 0 or idx >= len(pool):
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Edge index out of range: {idx}",
                    f"Valid range 0..{len(pool) - 1}",
                )
            sm = _get(doc, "SelectionManager")
            data = _get(sm, "CreateSelectData")
            data.Mark = 1
            doc.ClearSelection2(True)
            if not bool(pool[idx].Select4(False, data)):
                raise fail("SELECT_FAILED", f"Cannot select edge {idx}", "Check with get_edges")
            radius = 0.0005 if radius_m is None else float(radius_m)
            none = VARIANT(pythoncom.VT_DISPATCH, None)
            # Type=0 Closed；Position=0 Material Inside
            try:
                feat = doc.FeatureManager.InsertSheetMetalHem2(
                    0,
                    0,
                    False,
                    float(length_m),
                    0.0,
                    0.0,
                    float(radius),
                    0.0,
                    none,
                    True,
                    0,
                    0,
                    True,
                    0.5,
                    0.0,
                    0.0,
                )
            except Exception as exc:
                log.debug("InsertSheetMetalHem2 failed: %s", traceback.format_exc())
                raise self._map_error(exc) from exc
            if feat is None:
                raise fail("FEATURE_CREATE_FAILED", "Hem failed", "Need base flange; select outline edge")
            real = self._feature_real_name(feat, "Hem")
            return FeatureInfo(name=self._register("Hem", real), kind="hem")

        return self._call(_fn, timeout=180.0)

    def export_flat_dxf(self, path: Path) -> None:
        """After unfold, ExportToDWG2 to DXF (GetPathName required; SheetMetalOptions includes flat geometry)."""

        def _fn() -> None:
            import pythoncom
            from win32com.client import VARIANT

            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create a part first")
            self._require_part_doc(doc, "Use a part document to export flat DXF")
            # Unfold in same STA callback when possible (avoid nested _call)
            try:
                for feat in self._features_of(doc):
                    try:
                        if str(_get(feat, "GetTypeName2") or "") == "FlatPattern":
                            feat.Select2(False, 0)
                            _get(doc, "EditUnsuppress2")
                    except Exception:
                        continue
                _get(doc, "SetBendState", 2)
                _get(doc, "ForceRebuild3", True)
            except Exception:
                log.debug("Unfold before export: %s", traceback.format_exc())
            out = str(Path(path).resolve())
            model = str(_get(doc, "GetPathName") or "")
            # ExportToDWG2 needs bound path on active doc; save_as default Copy bit skips GetPathName
            if not model:
                bind = Path(path).with_suffix(".sldprt")
                try:
                    res = _get(doc, "SaveAs3", str(bind), 0, 1)  # Silent, not Copy
                    failed = res is False or res == "1" or (
                        isinstance(res, int) and not isinstance(res, bool) and res != 0
                    )
                    if failed:
                        raise fail(
                            "SAVE_FAILED",
                            f"Failed to bind path before flat DXF export: {bind}",
                            "save_document first, then export_flat_dxf",
                        )
                except CadMcpError:
                    raise
                except Exception as exc:
                    log.debug("Bind path SaveAs3 failed: %s", traceback.format_exc())
                    raise self._map_error(exc) from exc
                model = str(_get(doc, "GetPathName") or "") or str(bind.resolve())
            empty = VARIANT(pythoncom.VT_EMPTY, None)
            # bit0=flat geometry bit1=hidden edges bit2=bend lines
            sheet_opts = 1 | 2 | 4
            try:
                ok = bool(
                    doc.ExportToDWG2(
                        out,
                        model,
                        1,  # DXF / sheet metal
                        True,
                        empty,
                        False,
                        False,
                        sheet_opts,
                        empty,
                    )
                )
            except Exception as exc:
                log.debug("ExportToDWG2 failed: %s", traceback.format_exc())
                raise self._map_error(exc) from exc
            if not ok and not Path(path).is_file():
                raise fail("SAVE_FAILED", f"Flat DXF export failed: {path}", "Confirm sheet is unfolded and path is writable")

        return self._call(_fn, timeout=180.0)

    def sheet_metal_bend_table(self) -> list[dict]:
        def _fn() -> list[dict]:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create a part first")
            self._require_part_doc(doc, "Use a part document to read bend table")
            rows: list[dict] = []
            try:
                folder = _get(doc.FeatureManager, "GetSheetMetalFolder")
                metals = list(_get(folder, "GetSheetMetals") or ()) if folder is not None else []
                for i, metal in enumerate(metals):
                    data = _get(metal, "GetDefinition")
                    k = float(_get(data, "KFactor") or 0.5)
                    radius = float(_get(data, "BendRadius") or 0.0)
                    rows.append(
                        {
                            "index": i,
                            "angle_deg": None,
                            "radius_m": radius,
                            "k_factor": k,
                        }
                    )
            except Exception:
                log.debug("Read bend table failed: %s", traceback.format_exc())
            return rows

        return self._call(_fn, timeout=60.0)
