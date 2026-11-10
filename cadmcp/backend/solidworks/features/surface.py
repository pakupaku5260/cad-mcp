"""Features · surfaces (extrude / knit / fill / boundary / thicken / trim / extend / fillet).

S5-5 + SURF3–6: main APIs include trim/extend/fillet/untrim_surface; helpers include _feature_kind, etc.

Dependencies (self, MRO):
- `_call` / `_map_error`（STAThreadMixin）
- `_require_part_doc`（InfrastructureMixin）
- `_select_pending_sketch` / `_consume_sketch_name` / `_pending_sketch_name` / `_sketch_open`
  / `_completed_sketches`（SketchMixin）
- `_select_sketch_or_curve` / `_clear_selection`（SelectionMixin）
- `_find_feature` / `_real_name` / `_feature_real_name` / `_register` / `_features_of`（NamingMixin）
- `_get`（_helpers）

imports:
- `cadmcp.backend.protocol.models`（FeatureInfo）
- `cadmcp.errors`（fail）
- `.._constants`（`_SURFACE_EXTRU_TAIL` / `_SKETCH_FEATURE_TYPES`）
- `.._helpers`（_get）
"""
from __future__ import annotations

import logging
import traceback
from collections.abc import Sequence
from typing import Any

from cadmcp.backend.protocol.models import FeatureInfo
from cadmcp.errors import CadMcpError, fail

from .._constants import _SKETCH_FEATURE_TYPES, _SURFACE_EXTRU_TAIL
from .._helpers import _get

log = logging.getLogger(__name__)


class SurfaceMixin:
    """Surfaces (S5-5: 5 main + 7 helpers)."""

    def _init_state(self) -> None:
        pass  # stateless

    def _feature_kind(self, feat: Any) -> str:
        try:
            return str(_get(feat, "GetTypeName2"))
        except Exception:
            return ""

    def _new_features_of_type(self, doc: Any, tname: str, before: set[str]) -> list[Any]:
        out: list[Any] = []
        for feat in self._features_of(doc):
            try:
                name = str(_get(feat, "Name"))
                if name in before:
                    continue
                if str(_get(feat, "GetTypeName2") or "") == tname:
                    out.append(feat)
            except Exception:
                continue
        return out

    def _sheet_body_names(self, doc: Any) -> list[str]:
        try:
            bodies = doc.GetBodies2(1, True) or ()
        except TypeError:
            try:
                bodies = doc.GetBodies2(1) or ()
            except Exception:
                log.debug("GetBodies2 sheet bodies failed: %s", traceback.format_exc())
                return []
        except Exception:
            log.debug("GetBodies2 sheet bodies failed: %s", traceback.format_exc())
            return []
        names: list[str] = []
        for body in list(bodies):
            try:
                names.append(str(_get(body, "Name")))
            except Exception:
                continue
        return names

    def _resolve_sheet_bodies(self, doc: Any, surfaces: Sequence[str] | None) -> list[str]:
        sheets = self._sheet_body_names(doc)
        if not surfaces:
            return sheets[-2:] if len(sheets) >= 2 else sheets
        out: list[str] = []
        for raw in surfaces:
            real = self._aliases.get(str(raw), str(raw))
            if real in sheets:
                out.append(real)
                continue
            feat = self._find_feature(doc, real)
            name = None if feat is None else self._feature_real_name(feat, real)
            if name in sheets:
                out.append(name)
                continue
            raise fail(
                "FEATURE_NOT_FOUND",
                f"Surface not found {raw!r}",
                "Use a surface-extrude name from list_features, or omit surfaces to knit the last two",
                requested=raw,
            )
        return out

    def _sheet_body_objects(self, doc: Any) -> list[Any]:
        try:
            bodies = doc.GetBodies2(1, False) or ()
        except TypeError:
            try:
                bodies = doc.GetBodies2(1) or ()
            except Exception:
                log.debug("GetBodies2 sheet body objects failed: %s", traceback.format_exc())
                return []
        except Exception:
            log.debug("GetBodies2 sheet body objects failed: %s", traceback.format_exc())
            return []
        return [b for b in list(bodies) if b is not None]

    def _resolve_fill_body(self, doc: Any, surface: str | None) -> Any:
        sheets = self._sheet_body_objects(doc)
        if surface is not None:
            feat = self._find_feature(doc, surface)
            if feat is None:
                raise fail(
                    "FEATURE_NOT_FOUND",
                    f"Surface not found {surface!r}",
                    "Use Surface-ExtrudeN from list_features",
                    requested=surface,
                )
            try:
                faces = list(_get(feat, "GetFaces") or [])
            except Exception:
                faces = []
            for face in faces:
                body = _get(face, "GetBody")
                if body is not None:
                    return body
            real = self._feature_real_name(feat, surface)
            for body in sheets:
                try:
                    if str(_get(body, "Name")) == real:
                        return body
                except Exception:
                    continue
            raise fail(
                "FEATURE_NOT_FOUND",
                f"No sheet body for surface {surface!r}",
                "Use surface-extrude name from list_features, or omit surface to use the latest sheet body",
                requested=surface,
            )
        if not sheets:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "No sheet body available to fill",
                "extrude_surface for an open sheet body, then fill_surface to cap edges",
            )
        return sheets[-1]

    def _resolve_thicken_target(self, doc: Any, surface: str | None) -> Any:
        if surface is not None:
            feat = self._find_feature(doc, surface)
            if feat is None:
                raise fail(
                    "FEATURE_NOT_FOUND",
                    f"Surface not found {surface!r}",
                    "Use surface-extrude name from list_features",
                    requested=surface,
                )
            return feat
        last = None
        for feat in self._features_of(doc):
            try:
                if str(_get(feat, "GetTypeName2") or "") in {"ExtruRefSurface", "SewRefSurface"}:
                    last = feat
            except Exception:
                continue
        if last is None:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "No surface available to thicken",
                "extrude_surface on a closed profile, then thicken",
            )
            return last

    def _surface_feature_sheet_names(self, doc: Any) -> list[str]:
        """Surface sheet body names in feature-tree order (Extru/Sew/Fill/Blend/Trim); default trim tool/target."""
        out: list[str] = []
        sheets = set(self._sheet_body_names(doc))
        for feat in self._features_of(doc):
            try:
                kind = str(_get(feat, "GetTypeName2") or "")
            except Exception:
                continue
            if kind not in {
                "ExtruRefSurface",
                "SewRefSurface",
                "FillRefSurface",
                "BlendRefSurface",
                "TrimRefSurface",
                "ExtendRefSurface",
                "UnTrimRefSurf",
            }:
                continue
            real = self._feature_real_name(feat, "")
            if real in sheets:
                out.append(real)
                continue
            try:
                faces = list(_get(feat, "GetFaces") or [])
            except Exception:
                faces = []
            for face in faces:
                body = _get(face, "GetBody")
                if body is None:
                    continue
                try:
                    name = str(_get(body, "Name"))
                except Exception:
                    continue
                if name in sheets:
                    out.append(name)
                    break
        return out

    def _resolve_trim_pair(
        self, doc: Any, tool: str | None, target: str | None
    ) -> tuple[str, str]:
        if tool is not None and target is not None:
            return (
                self._resolve_sheet_bodies(doc, [tool])[0],
                self._resolve_sheet_bodies(doc, [target])[0],
            )
        ordered = self._surface_feature_sheet_names(doc)
        if len(ordered) < 2:
            sheets = self._sheet_body_names(doc)
            if len(sheets) < 2:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Trim needs at least two surfaces",
                    "extrude_surface twice (intersecting), then trim_surface",
                )
            ordered = sheets
        if tool is None and target is None:
            return ordered[-1], ordered[-2]
        if tool is not None:
            tool_name = self._resolve_sheet_bodies(doc, [tool])[0]
            others = [n for n in ordered if n != tool_name]
            if not others:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "No target surface available to trim",
                    "extrude_surface intersecting tool, or pass target explicitly",
                )
            return tool_name, others[-1]
        target_name = self._resolve_sheet_bodies(doc, [target])[0]
        others = [n for n in ordered if n != target_name]
        if not others:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "Trim tool surface not found",
                "extrude_surface intersecting target, or pass tool explicitly",
            )
        return others[-1], target_name

    def _resolve_loft_profiles(self, doc: Any, profiles: Sequence[str] | None) -> list[str]:
        if self._sketch_open:
            raise fail(
                "SKETCH_OP_FAILED",
                "Sketch is still open; close it before creating a feature",
                "Call end_sketch to close the sketch, then  loft",
            )
        completed = list(self._completed_sketches)

        def _as_sketch(name: str) -> str | None:
            real = self._real_name(name)
            if real in completed:
                return real
            if name in completed:
                return name
            feat = self._find_feature(doc, name)
            if feat is not None and self._feature_kind(feat) in _SKETCH_FEATURE_TYPES:
                return self._feature_real_name(feat, name)
            return None

        if profiles:
            names: list[str] = []
            for raw in profiles:
                found = _as_sketch(str(raw))
                if found is None:
                    raise fail(
                        "SKETCH_NOT_FOUND",
                        f"Loft profile sketch not found {raw!r}",
                        "Use completed sketch names like Sketch1; or omit profiles to use the last two sketches",
                        requested=raw,
                    )
                names.append(found)
        else:
            names = completed[-2:]
        if len(names) < 2:
            raise fail(
                "INVALID_ARGUMENT",
                "Loft needs at least two profile sketches",
                "Draw closed profiles on two parallel planes, end_sketch each, then loft",
            )
        return names

    def extrude_surface(self, depth_m: float, sketch: str | None = None) -> FeatureInfo:
        def _fn() -> FeatureInfo:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create a part first")
            self._require_part_doc(doc, "Use a part document for surface extrude")
            if depth_m <= 0:
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Surface extrude depth must be positive (internal meters): {depth_m}",
                    "Pass depth > 0 (unit follows unit param, default mm)",
                )
            feat_sk, sk_name = self._select_pending_sketch(doc, sketch)
            before = {str(_get(f, "Name")) for f in self._features_of(doc)}
            fm = doc.FeatureManager
            try:
                feat_sk.Select2(False, 0)
                doc.EditSketch()
                feat = fm.FeatureExtruRefSurface3(
                    True, False, False, 0, 0, float(depth_m), float(depth_m),
                    *_SURFACE_EXTRU_TAIL,
                )
            except Exception as exc:
                log.debug("FeatureExtruRefSurface3 failed: %s", traceback.format_exc())
                raise self._map_error(exc) from exc
            created = self._new_features_of_type(doc, "ExtruRefSurface", before)
            if feat is None and created:
                feat = created[-1]
            if feat is None:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Surface extrude failed (API returned None)",
                    "end_sketch then extrude_surface; confirm sketch remains in the feature tree",
                )
            real = self._feature_real_name(feat, "Surface-Extrude")
            self._consume_sketch_name(sk_name)
            self._pending_sketch_name = None
            return FeatureInfo(name=self._register("Surface-Extrude", real), kind="extrude_surface")

        return self._call(_fn, timeout=180.0)

    def knit(self, surfaces: Sequence[str] | None = None) -> FeatureInfo:
        def _fn() -> FeatureInfo:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create a part first")
            self._require_part_doc(doc, "Use a part document to knit surfaces")
            names = self._resolve_sheet_bodies(doc, surfaces)
            if len(names) < 2:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Knit needs at least two surfaces",
                    "extrude_surface twice, then knit",
                )
            import pythoncom
            from win32com.client import VARIANT

            callout = VARIANT(pythoncom.VT_DISPATCH, None)
            doc.ClearSelection2(True)
            for i, name in enumerate(names):
                try:
                    ok = bool(
                        doc.Extension.SelectByID2(
                            name, "SURFACEBODY", 0, 0, 0, i > 0, 1, callout, 0,
                        )
                    )
                except Exception:
                    log.debug("Select sheet body %s failed: %s", name, traceback.format_exc())
                    ok = False
                if not ok:
                    raise fail(
                        "SELECT_FAILED",
                        f"Cannot select surface sheet body {name!r}",
                        "Check surface-extrude names with list_features",
                    )
            before = {str(_get(f, "Name")) for f in self._features_of(doc)}
            fm = doc.FeatureManager
            try:
                feat = fm.InsertSewRefSurface(False, False, False, 1e-5, 1e-4)
            except Exception as exc:
                log.debug("InsertSewRefSurface failed: %s", traceback.format_exc())
                raise self._map_error(exc) from exc
            finally:
                self._clear_selection(doc)
            created = self._new_features_of_type(doc, "SewRefSurface", before)
            if feat is None and created:
                feat = created[-1]
            if feat is None:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Knit failed (API returned None)",
                    "Surfaces must share an edge; knit adjacent surface extrudes",
                )
            real = self._feature_real_name(feat, "Surface-Knit")
            return FeatureInfo(name=self._register("Surface-Knit", real), kind="knit")

        return self._call(_fn, timeout=180.0)

    def fill_surface(self, surface: str | None = None, edge: int = 0) -> FeatureInfo:
        def _fn() -> FeatureInfo:
            import pythoncom
            from win32com.client import VARIANT

            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create a part first")
            self._require_part_doc(doc, "Use a part document for fill surface")
            if self._sketch_open:
                raise fail(
                    "SKETCH_OP_FAILED",
                    "Sketch is still open; close it before creating a feature",
                    "Call end_sketch to close the sketch, then  fill_surface",
                )
            body = self._resolve_fill_body(doc, surface)
            try:
                edges = list(_get(body, "GetEdges") or [])
            except Exception:
                edges = []
            idx = int(edge)
            if not edges or idx < 0 or idx >= len(edges):
                raise fail(
                    "INVALID_ARGUMENT" if edges else "FEATURE_CREATE_FAILED",
                    "No sheet body edges available for fill" if not edges else f"Edge index out of range: {idx}",
                    "extrude_surface for a sheet body; use edge 0 for the circular cap",
                    index=idx,
                )
            empty = VARIANT(pythoncom.VT_EMPTY, None)
            arr = VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, (edges[idx],))
            curv = VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_I4, (0,))
            before = {str(_get(f, "Name")) for f in self._features_of(doc)}
            fm = doc.FeatureManager
            try:
                feat = fm.InsertFillSurface2(0, 0, arr, curv, empty, empty)
            except Exception as exc:
                log.debug("InsertFillSurface2 failed: %s", traceback.format_exc())
                raise self._map_error(exc) from exc
            created = self._new_features_of_type(doc, "FillRefSurface", before)
            if feat is None and created:
                feat = created[-1]
            if feat is None and not created:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Fill surface failed (API did not create feature)",
                    "Select open sheet edges (end circle of circular extrude); single-arg InsertFillSurface unavailable",
                )
            if feat is None:
                feat = created[-1]
            real = self._feature_real_name(feat, "Surface-Fill")
            return FeatureInfo(name=self._register("Surface-Fill", real), kind="fill_surface")

        return self._call(_fn, timeout=180.0)

    def boundary_surface(self, profiles: Sequence[str] | None = None) -> FeatureInfo:
        def _fn() -> FeatureInfo:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create a part first")
            self._require_part_doc(doc, "Use a part document for boundary surface")
            names = self._resolve_loft_profiles(doc, profiles)
            doc.ClearSelection2(True)
            for i, name in enumerate(names):
                if not self._select_sketch_or_curve(doc, name, append=i > 0, mark=1, is_sketch=True):
                    raise fail(
                        "SELECT_FAILED",
                        f"Cannot select boundary profile {name!r}",
                        "Confirm sketch is in the tree and not deleted or suppressed",
                    )
            before = {str(_get(f, "Name")) for f in self._features_of(doc)}
            try:
                # InsertNetBlend2: two circles always become solid Boundary1 (volume>0), not a surface.
                feat = doc.InsertLoftRefSurface2(False, False, False, 1.0, 0, 0)
            except Exception as exc:
                log.debug("InsertLoftRefSurface2 failed: %s", traceback.format_exc())
                raise self._map_error(exc) from exc
            finally:
                self._clear_selection(doc)
            created = self._new_features_of_type(doc, "BlendRefSurface", before)
            if feat is None and created:
                feat = created[-1]
            if feat is None:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Boundary surface failed (API did not create feature)",
                    "Two closed profiles must not be coplanar (offset plane via create_plane, then second sketch)",
                )
            real = self._feature_real_name(feat, "Surface-Loft")
            for name in names:
                self._consume_sketch_name(name)
            return FeatureInfo(name=self._register("Surface-Boundary", real), kind="boundary_surface")

        return self._call(_fn, timeout=180.0)

    def thicken(self, thickness_m: float, surface: str | None = None) -> FeatureInfo:
        def _fn() -> FeatureInfo:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create a part first")
            self._require_part_doc(doc, "Use a part document to thicken surface")
            if thickness_m <= 0:
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Thicken thickness must be positive (internal meters): {thickness_m}",
                    "Pass thickness > 0 (unit follows unit param, default mm)",
                )
            target = self._resolve_thicken_target(doc, surface)
            kind = self._feature_kind(target)
            if kind == "SewRefSurface":
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Open surface cannot thicken to a solid",
                    "Thicken closed-profile surface extrude; knitted open sheets cannot thicken",
                )
            doc.ClearSelection2(True)
            try:
                ok = bool(target.Select2(False, 1))
            except Exception:
                log.debug("Thicken face selection failed: %s", traceback.format_exc())
                ok = False
            if not ok:
                raise fail("SELECT_FAILED", "Cannot select surface to thicken", "Check surface names with list_features")
            before = {str(_get(f, "Name")) for f in self._features_of(doc)}
            fm = doc.FeatureManager
            try:
                feat = fm.FeatureBossThicken(
                    float(thickness_m), 0, 0, False, True, True, True,
                )
            except Exception as exc:
                log.debug("FeatureBossThicken failed: %s", traceback.format_exc())
                raise self._map_error(exc) from exc
            finally:
                self._clear_selection(doc)
            created = self._new_features_of_type(doc, "Thicken", before)
            if feat is None and created:
                feat = created[-1]
            if feat is None:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Open surface cannot thicken to a solid",
                    "Thicken closed-profile surface extrude; knitted open sheets cannot thicken",
                )
            real = self._feature_real_name(feat, "Thicken")
            return FeatureInfo(name=self._register("Thicken", real), kind="thicken")

        return self._call(_fn, timeout=180.0)

    def trim_surface(
        self,
        tool: str | None = None,
        target: str | None = None,
        keep: int = 0,
    ) -> FeatureInfo:
        def _fn() -> FeatureInfo:
            import pythoncom
            from win32com.client import VARIANT

            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create a part first")
            self._require_part_doc(doc, "Use a part document for surface trim")
            if self._sketch_open:
                raise fail(
                    "SKETCH_OP_FAILED",
                    "Sketch is still open; close it before creating a feature",
                    "Call end_sketch to close the sketch, then  trim_surface",
                )
            if int(keep) < 0:
                raise fail(
                    "INVALID_ARGUMENT",
                    f"keep cannot be negative: {keep}",
                    "Pass keep≥0 (GetPreTrimmedBodies piece index, default 0)",
                    index=int(keep),
                )
            tool_name, target_name = self._resolve_trim_pair(doc, tool, target)
            if tool_name == target_name:
                raise fail(
                    "INVALID_ARGUMENT",
                    "tool and target cannot be the same surface",
                    "Specify trim tool and target sheet body separately",
                )
            callout = VARIANT(pythoncom.VT_DISPATCH, None)
            doc.ClearSelection2(True)
            try:
                ok_tool = bool(
                    doc.Extension.SelectByID2(
                        tool_name, "SURFACEBODY", 0, 0, 0, False, 0, callout, 0,
                    )
                )
            except Exception:
                log.debug("Select trim tool %s failed: %s", tool_name, traceback.format_exc())
                ok_tool = False
            if not ok_tool:
                raise fail(
                    "SELECT_FAILED",
                    f"Cannot select trim tool sheet body {tool_name!r}",
                    "Check surface-extrude names with list_features",
                )
            before = {str(_get(f, "Name")) for f in self._features_of(doc)}
            fm = doc.FeatureManager
            sm = doc.SelectionManager
            pre_opened = False
            try:
                if not bool(fm.PreTrimSurface(False, True, False, False)):
                    raise fail(
                        "FEATURE_CREATE_FAILED",
                        "Surface trim pre-process failed",
                        "Confirm surfaces intersect; extrude_surface to get intersecting sheets first",
                    )
                pre_opened = True
                target_obj = None
                for body in self._sheet_body_objects(doc):
                    try:
                        if str(_get(body, "Name")) == target_name:
                            target_obj = body
                            break
                    except Exception:
                        continue
                if target_obj is None:
                    raise fail(
                        "FEATURE_CREATE_FAILED",
                        f"Target sheet body not found {target_name!r}",
                        "Check surface names in list_features and retry",
                    )
                try:
                    pieces = list(fm.GetPreTrimmedBodies(target_obj) or [])
                except Exception as exc:
                    log.debug("GetPreTrimmedBodies failed: %s", traceback.format_exc())
                    raise self._map_error(exc) from exc
                idx = int(keep)
                if not pieces or idx >= len(pieces) or pieces[idx] is None:
                    raise fail(
                        "INVALID_ARGUMENT" if pieces else "FEATURE_CREATE_FAILED",
                        "No trim pieces available to keep"
                        if not pieces
                        else f"keep out of piece range: {idx} (of {len(pieces)} pieces)",
                        "Surfaces must intersect; use keep 0 or 1",
                        index=idx,
                    )
                try:
                    data = sm.CreateSelectData
                    if callable(data) and not hasattr(data, "_oleobj_"):
                        data = data()
                    data.Mark = 0
                    # append=False: official SelectByID2(append=True) fails to create feature in 2025
                    ok_keep = bool(pieces[idx].Select2(False, data))
                except Exception:
                    log.debug("Select keep piece failed: %s", traceback.format_exc())
                    ok_keep = False
                if not ok_keep:
                    raise fail(
                        "SELECT_FAILED",
                        f"Cannot select keep piece keep={idx}",
                        "Try keep=0/1, or confirm tool cuts target",
                    )
                feat = fm.PostTrimSurface(True)
                pre_opened = False
            except CadMcpError:
                raise
            except Exception as exc:
                log.debug("Surface trim failed: %s", traceback.format_exc())
                raise self._map_error(exc) from exc
            finally:
                if pre_opened:
                    # After PreTrim opens the property page, PostTrim must finish or a modal dialog remains
                    try:
                        fm.PostTrimSurface(True)
                    except Exception:
                        log.debug("Trim finish PostTrimSurface failed: %s", traceback.format_exc())
                self._clear_selection(doc)
            created = self._new_features_of_type(doc, "TrimRefSurface", before)
            if feat is None and created:
                feat = created[-1]
            if feat is None:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Surface trim failed (API did not create feature)",
                    "Surfaces must intersect; default tool is the last sheet in the feature tree",
                )
            real = self._feature_real_name(feat, "Surface-Trim")
            return FeatureInfo(name=self._register("Surface-Trim", real), kind="trim_surface")

        return self._call(_fn, timeout=180.0)

    def extend_surface(
        self,
        distance_m: float,
        surface: str | None = None,
        edge: int | None = None,
        linear: bool = True,
    ) -> FeatureInfo:
        def _fn() -> FeatureInfo:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create a part first")
            self._require_part_doc(doc, "Use a part document for surface extend")
            if self._sketch_open:
                raise fail(
                    "SKETCH_OP_FAILED",
                    "Sketch is still open; close it before creating a feature",
                    "Call end_sketch to close the sketch, then  extend_surface",
                )
            if distance_m <= 0:
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Extend distance must be positive (internal meters): {distance_m}",
                    "Pass distance > 0 (unit follows unit param, default mm)",
                )
            body = self._resolve_fill_body(doc, surface)
            doc.ClearSelection2(True)
            if edge is None:
                try:
                    faces = [f for f in list(_get(body, "GetFaces") or ()) if f is not None]
                except Exception:
                    faces = []
                if not faces:
                    raise fail(
                        "FEATURE_CREATE_FAILED",
                        "Sheet body has no face to extend",
                        "extrude_surface for open sheet, then extend_surface",
                    )
                try:
                    ok = bool(faces[0].Select2(False, 0))
                except Exception:
                    log.debug("Extend face selection failed: %s", traceback.format_exc())
                    ok = False
                if not ok:
                    raise fail("SELECT_FAILED", "Cannot select surface to extend", "Check surface names with list_features")
            else:
                try:
                    edges = [e for e in list(_get(body, "GetEdges") or ()) if e is not None]
                except Exception:
                    edges = []
                idx = int(edge)
                if not edges or idx < 0 or idx >= len(edges):
                    raise fail(
                        "INVALID_ARGUMENT" if edges else "FEATURE_CREATE_FAILED",
                        "No sheet body edges to extend" if not edges else f"Edge index out of range: {idx}",
                        "extrude_surface first; edge is sheet edge index, or omit edge to extend whole face",
                        index=idx,
                    )
                try:
                    ok = bool(edges[idx].Select2(False, 0))
                except Exception:
                    log.debug("Extend edge selection failed: %s", traceback.format_exc())
                    ok = False
                if not ok:
                    raise fail(
                        "SELECT_FAILED",
                        f"Cannot select extend edge edge={idx}",
                        "Change edge, or omit edge to extend the whole face",
                    )
            before = {str(_get(f, "Name")) for f in self._features_of(doc)}
            try:
                # EndCondition=0: by distance; return is always None—use feature tree
                doc.InsertExtendSurface(bool(linear), 0, float(distance_m))
            except Exception as exc:
                log.debug("InsertExtendSurface failed: %s", traceback.format_exc())
                raise self._map_error(exc) from exc
            finally:
                self._clear_selection(doc)
            created = self._new_features_of_type(doc, "ExtendRefSurface", before)
            if not created:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Surface extend failed (API did not create feature)",
                    "Select open sheet edge or face; some edges (e.g. cylinder rulings) may not extend",
                )
            feat = created[-1]
            real = self._feature_real_name(feat, "Surface-Extend")
            return FeatureInfo(name=self._register("Surface-Extend", real), kind="extend_surface")

        return self._call(_fn, timeout=180.0)

    def fillet_surface(
        self, radius_m: float, surface: str | None = None, edge: int = 0
    ) -> FeatureInfo:
        def _fn() -> FeatureInfo:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create a part first")
            self._require_part_doc(doc, "Use a part document for surface fillet")
            if self._sketch_open:
                raise fail(
                    "SKETCH_OP_FAILED",
                    "Sketch is still open; close it before creating a feature",
                    "Call end_sketch to close the sketch, then  fillet_surface",
                )
            if radius_m <= 0:
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Fillet radius must be positive (internal meters): {radius_m}",
                    "Pass radius > 0 (unit follows unit param, default mm)",
                )
            body = self._resolve_fill_body(doc, surface)
            try:
                edges = [e for e in list(_get(body, "GetEdges") or ()) if e is not None]
            except Exception:
                edges = []
            idx = int(edge)
            if not edges or idx < 0 or idx >= len(edges):
                raise fail(
                    "INVALID_ARGUMENT" if edges else "FEATURE_CREATE_FAILED",
                    "No sheet body edges to fillet" if not edges else f"Edge index out of range: {idx}",
                    "extrude_surface for sheet body; use edge 0 or 1",
                    index=idx,
                )
            doc.ClearSelection2(True)
            try:
                ok = bool(edges[idx].Select2(False, 0))
            except Exception:
                log.debug("Surface fillet edge selection failed: %s", traceback.format_exc())
                ok = False
            if not ok:
                raise fail(
                    "SELECT_FAILED",
                    f"Cannot select surface edge edge={idx}",
                    "Use open sheet edge index; circular extrude is usually 0/1",
                )
            before = {str(_get(f, "Name")) for f in self._features_of(doc)}
            fm = doc.FeatureManager
            feat = None
            try:
                # Same params as solid fillet; 2025 may create Fillet on sheet edges, volume still 0
                feat = fm.FeatureFillet3(195, float(radius_m), 0.0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
            except Exception as exc:
                log.debug("FeatureFillet3 on sheet body failed: %s", traceback.format_exc())
                raise self._map_error(exc) from exc
            finally:
                self._clear_selection(doc)
            created = self._new_features_of_type(doc, "Fillet", before)
            if feat is None and created:
                feat = created[-1]
            if feat is None:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Surface fillet failed (API did not create feature)",
                    "Select open sheet edges; radius must be within machinable range",
                )
            real = self._feature_real_name(feat, "Fillet")
            return FeatureInfo(name=self._register("Surface-Fillet", real), kind="fillet_surface")

        return self._call(_fn, timeout=180.0)

    def untrim_surface(self, surface: str | None = None) -> FeatureInfo:
        def _fn() -> FeatureInfo:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create a part first")
            self._require_part_doc(doc, "Use a part document for untrim surface")
            if self._sketch_open:
                raise fail(
                    "SKETCH_OP_FAILED",
                    "Sketch is still open; close it before creating a feature",
                    "Call end_sketch to close the sketch, then  untrim_surface",
                )
            body = self._resolve_fill_body(doc, surface)
            try:
                faces = [f for f in list(_get(body, "GetFaces") or ()) if f is not None]
            except Exception:
                faces = []
            if not faces:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Sheet body has no face to untrim",
                    "trim_surface first, then untrim_surface",
                )
            doc.ClearSelection2(True)
            try:
                ok = bool(faces[0].Select2(False, 0))
            except Exception:
                log.debug("Untrim face selection failed: %s", traceback.format_exc())
                ok = False
            if not ok:
                raise fail("SELECT_FAILED", "Cannot select surface to untrim", "Check surface names with list_features")
            before = {str(_get(f, "Name")) for f in self._features_of(doc)}
            fm = doc.FeatureManager
            feat = None
            try:
                # swFaceUntrimTypeAllEdges=0, swEdgeUntrimTypeConnectEndPoints=1
                feat = fm.InsertUntrimSurface(0, 1, 0.0, True)
            except Exception as exc:
                log.debug("InsertUntrimSurface failed: %s", traceback.format_exc())
                raise self._map_error(exc) from exc
            finally:
                self._clear_selection(doc)
            created = self._new_features_of_type(doc, "UnTrimRefSurf", before)
            if feat is None and created:
                feat = created[-1]
            if feat is None:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Untrim failed (API did not create feature)",
                    "trim_surface first; only works on trimmed sheets",
                )
            real = self._feature_real_name(feat, "Surface-Untrim")
            return FeatureInfo(name=self._register("Surface-Untrim", real), kind="untrim_surface")

        return self._call(_fn, timeout=180.0)
