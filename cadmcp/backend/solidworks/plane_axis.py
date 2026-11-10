"""COM backend · reference planes / axes (create_plane / create_axis).

State ownership:
- ``_plane_uv_root`` (PlaneN → Front/Top/Right for sketch UV)

Dependencies (self, MRO):
- ``_call`` / ``_map_error`` (STAThreadMixin)
- ``_select_plane`` / ``_select_axis_feat`` / ``_select_one_edge`` (SelectionMixin)
- ``_feature_real_name`` / ``_register`` (NamingMixin)
- ``_features_of`` (NamingMixin)
- ``_edge_geometry`` (GeometryMixin)
- ``_get`` (_helpers)

imports:
- ``cadmcp.backend.protocol.constants`` (DEFAULT_PLANES / PLANE_ANGLE_AXIS_PLANES / REVOLVE_AXES / canonical_plane)
- ``cadmcp.backend.protocol.models`` (FeatureInfo)
- ``cadmcp.backend.protocol.parsers`` (validate_create_plane)
- ``._constants`` (SW_DOC_PART / _SW_REFPLANE_*)
- ``._helpers`` (_get)
"""
from __future__ import annotations

import logging
import traceback
from collections.abc import Sequence
from typing import Any

from cadmcp.backend.protocol.constants import (
    DEFAULT_PLANES,
    PLANE_ANGLE_AXIS_PLANES,
    REVOLVE_AXES,
)
from cadmcp.backend.protocol.models import FeatureInfo
from cadmcp.backend.protocol.parsers import canonical_plane
from cadmcp.backend.protocol.validators import validate_create_plane
from cadmcp.errors import CadMcpError, fail

from ._constants import (
    _SW_REFPLANE_ANGLE,
    _SW_REFPLANE_COINCIDENT,
    _SW_REFPLANE_DISTANCE,
    SW_DOC_PART,
)
from ._helpers import _get

log = logging.getLogger(__name__)


class PlaneAxisMixin:
    """Reference planes / axes (S4-3a: list_planes / create_plane / _insert_offset_plane)."""

    def _init_state(self) -> None:
        """Migrate ``_plane_uv_root`` (issue-4 resolved)."""
        self._plane_uv_root: dict[str, str] = {}

    def _reset_plane_state(self) -> None:
        """Clear plane UV root map (sole state owner: PlaneAxisMixin)."""
        self._plane_uv_root.clear()

    def list_planes(self) -> list[str]:
        extra = [k for k in sorted(self._aliases) if k.startswith("Plane")]
        return list(DEFAULT_PLANES) + extra

    def create_plane(
        self,
        reference: str | None = None,
        offset_m: float = 0.0,
        flip: bool = False,
        *,
        mode: str = "offset",
        angle_rad: float | None = None,
        axis: str | None = None,
        points_m: Sequence[tuple[float, float, float]] | None = None,
    ) -> FeatureInfo:
        def _fn() -> FeatureInfo:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            if int(_get(doc, "GetType")) != SW_DOC_PART:
                raise fail("INVALID_ARGUMENT", "Active document is not a part", "Use a part document to create a plane")
            validate_create_plane(mode, reference, True, angle_rad, axis, points_m)
            if mode == "offset":
                feat = self._insert_offset_plane(doc, str(reference), offset_m, flip)
                root = self._plane_uv_root.get(str(reference)) or canonical_plane(str(reference)) or "Front Plane"
            elif mode == "angle":
                feat = self._insert_angle_plane(doc, str(reference), str(axis), float(angle_rad or 0.0), flip)
                root = self._plane_uv_root.get(str(reference)) or canonical_plane(str(reference)) or "Front Plane"
            else:
                feat = self._insert_points_plane(doc, points_m)  # type: ignore[arg-type]
                root = "Front Plane"
            real = self._feature_real_name(feat, "Plane")
            logical = self._register("Plane", real)
            self._plane_uv_root[logical] = root
            self._plane_uv_root[real] = root
            try:
                _get(doc, "ForceRebuild3", True)
            except Exception:
                pass
            return FeatureInfo(name=logical, kind="plane")

        return self._call(_fn)

    def _insert_offset_plane(self, doc: Any, reference: str, offset_m: float, flip: bool) -> Any:
        doc.ClearSelection2(True)
        if not self._select_plane(doc, reference, append=False, mark=0):
            raise fail(
                "FEATURE_NOT_FOUND",
                f"Reference plane not found: {reference!r}",
                "Use list_planes for available plane names",
                requested=reference,
            )
        signed = -float(offset_m) if flip else float(offset_m)
        feat = doc.FeatureManager.InsertRefPlane(_SW_REFPLANE_DISTANCE, signed, 0, 0, 0, 0)
        if feat is None:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "Failed to create offset reference plane",
                "Confirm the reference plane exists and offset is a finite distance",
            )
        return feat

    def _insert_angle_plane(
        self, doc: Any, reference: str, axis: str, angle_rad: float, flip: bool,
    ) -> Any:
        axis_name = axis
        if axis in REVOLVE_AXES:
            pair = PLANE_ANGLE_AXIS_PLANES[axis]
            created = self.create_axis(planes=pair)
            axis_name = created.name
        doc.ClearSelection2(True)
        if not self._select_plane(doc, reference, append=False, mark=0):
            raise fail(
                "FEATURE_NOT_FOUND",
                f"Reference plane not found: {reference!r}",
                "Use list_planes for available plane names",
                requested=reference,
            )
        if not self._select_axis_feat(doc, axis_name, append=True, mark=1):
            raise fail(
                "FEATURE_NOT_FOUND",
                f"Reference axis not found: {axis!r}",
                "Call create_axis first, or pass +x/+y/+z",
                requested=axis,
            )
        signed = -float(angle_rad) if flip else float(angle_rad)
        feat = doc.FeatureManager.InsertRefPlane(
            _SW_REFPLANE_ANGLE, signed, _SW_REFPLANE_COINCIDENT, 0, 0, 0,
        )
        if feat is None:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "Failed to create angled reference plane",
                "Axis must lie in the reference plane; use create_axis for intersection axes",
            )
        return feat

    def _insert_points_plane(
        self, doc: Any, points_m: Sequence[tuple[float, float, float]],
    ) -> Any:
        import pythoncom
        from win32com.client import VARIANT

        p0, p1, p2 = (tuple(float(c) for c in p) for p in points_m)
        e1 = (p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2])
        e2 = (p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2])
        nx = e1[1] * e2[2] - e1[2] * e2[1]
        ny = e1[2] * e2[0] - e1[0] * e2[2]
        nz = e1[0] * e2[1] - e1[1] * e2[0]
        if nx * nx + ny * ny + nz * nz < 1e-16:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "Three points are colinear; cannot define a plane",
                "Provide three non-colinear points",
            )
        sm = doc.SketchManager
        try:
            sm.Insert3DSketch(True)
            for p in (p0, p1, p2):
                if sm.CreatePoint(p[0], p[1], p[2]) is None:
                    raise fail("FEATURE_CREATE_FAILED", "Cannot create reference point", "Confirm point coordinates are valid")
            sm.Insert3DSketch(True)
        except CadMcpError:
            raise
        except Exception as exc:
            log.debug("Three-point sketch failed: %s", traceback.format_exc())
            raise fail("FEATURE_CREATE_FAILED", "Cannot create three-point sketch", "Use mode=offset or angle") from exc
        callout = VARIANT(pythoncom.VT_DISPATCH, None)
        ext = doc.Extension
        doc.ClearSelection2(True)
        for i, p in enumerate((p0, p1, p2)):
            try:
                ok = bool(
                    ext.SelectByID2("", "EXTSKETCHPOINT", p[0], p[1], p[2], i > 0, i, callout, 0)
                )
            except Exception:
                log.debug("Select point failed: %s", traceback.format_exc())
                ok = False
            if not ok:
                raise fail(
                    "SELECT_FAILED",
                    "Cannot select reference points for three-point plane",
                    "Confirm points are in model coordinates",
                )
        feat = doc.FeatureManager.InsertRefPlane(
            _SW_REFPLANE_COINCIDENT, 0, _SW_REFPLANE_COINCIDENT, 0, _SW_REFPLANE_COINCIDENT, 0,
        )
        if feat is None:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "Failed to create three-point reference plane",
                "Three points cannot be colinear",
            )
        return feat

    def create_axis(
        self, planes: tuple[str, str] | None = None, edge: int | None = None,
    ) -> FeatureInfo:
        def _fn() -> FeatureInfo:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            if int(_get(doc, "GetType")) != SW_DOC_PART:
                raise fail("INVALID_ARGUMENT", "Active document is not a part", "Use a part document to create a reference axis")
            has_planes = planes is not None
            has_edge = edge is not None
            if has_planes == has_edge:
                raise fail(
                    "INVALID_ARGUMENT",
                    "create_axis requires planes or edge, not both",
                    "Pass planes for two-plane intersection, or edge index for a straight edge",
                )
            before = {
                str(_get(f, "Name"))
                for f in self._features_of(doc)
                if str(_get(f, "GetTypeName2")) == "RefAxis"
            }
            if planes is not None:
                doc.ClearSelection2(True)
                if not self._select_plane(doc, planes[0], append=False, mark=0):
                    raise fail(
                        "FEATURE_NOT_FOUND",
                        f"Reference plane not found: {planes[0]!r}",
                        "Use list_planes for available plane names",
                        requested=planes[0],
                    )
                if not self._select_plane(doc, planes[1], append=True, mark=0):
                    raise fail(
                        "FEATURE_NOT_FOUND",
                        f"Reference plane not found: {planes[1]!r}",
                        "Use list_planes for available plane names",
                        requested=planes[1],
                    )
                try:
                    ok = bool(_get(doc, "InsertAxis2", True))
                except Exception as exc:
                    raise fail(
                        "FEATURE_CREATE_FAILED",
                        "Failed to create reference axis",
                        "Select two intersecting reference planes",
                    ) from exc
                if not ok:
                    raise fail(
                        "FEATURE_CREATE_FAILED",
                        "Planes are parallel or do not define a reference axis",
                        "Select two intersecting reference planes",
                    )
            else:
                idx = int(edge)  # type: ignore[arg-type]
                pool = self._part_edge_objects(doc)
                if not pool:
                    raise fail("REF_NOT_FOUND", "No selectable edges in the document", "Create a solid first (e.g. extrude)")
                if idx < 0 or idx >= len(pool):
                    raise fail(
                        "INVALID_ARGUMENT",
                        f"Edge index out of range: {idx}",
                        f"Use get_edges; valid range 0..{len(pool) - 1}",
                        index=idx,
                    )
                kind, _mid = self._edge_geometry(pool[idx])
                if kind != "line":
                    raise fail(
                        "INVALID_ARGUMENT",
                        f"Reference axis edge must be a line (got {kind!r})",
                        "Use get_edges and pick kind=line index",
                    )
                doc.ClearSelection2(True)
                if self._select_one_edge(doc, idx, mark=0) == 0:
                    raise fail(
                        "FEATURE_CREATE_FAILED",
                        f"Cannot select edge {idx}",
                        "Use get_edges to confirm a straight edge",
                    )
                try:
                    ok = bool(_get(doc, "InsertAxis2", True))
                except Exception as exc:
                    raise fail(
                        "FEATURE_CREATE_FAILED",
                        "Failed to create reference axis from edge",
                        "Select a straight edge",
                    ) from exc
                if not ok:
                    raise fail(
                        "FEATURE_CREATE_FAILED",
                        "Failed to create reference axis from edge",
                        "Select a straight edge",
                    )
            try:
                _get(doc, "ForceRebuild3", True)
            except Exception:
                pass
            created = [
                f
                for f in self._features_of(doc)
                if str(_get(f, "GetTypeName2")) == "RefAxis" and str(_get(f, "Name")) not in before
            ]
            if not created:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Failed to create reference axis",
                    "Confirm selected planes intersect or the edge is a line",
                )
            real = self._feature_real_name(created[-1], "Axis")
            return FeatureInfo(name=self._register("Axis", real), kind="axis")

        return self._call(_fn)

    def _ensure_ref_axis(self, doc: Any, axis: str) -> Any | None:
        """Insert reference axis from two planes: +z = Top∩Right, +y = Front∩Right, +x = Front∩Top."""
        planes = {
            "x": ("Front Plane", "Top Plane"),
            "y": ("Front Plane", "Right Plane"),
            "z": ("Top Plane", "Right Plane"),
        }
        pair = planes.get(axis[1])
        if pair is None:
            return None
        before = {
            str(_get(f, "Name"))
            for f in self._features_of(doc)
            if str(_get(f, "GetTypeName2")) == "RefAxis"
        }
        doc.ClearSelection2(True)
        if not self._select_plane(doc, pair[0], append=False, mark=0):
            return None
        if not self._select_plane(doc, pair[1], append=True, mark=0):
            return None
        try:
            if not _get(doc, "InsertAxis2", True):
                return None
        except Exception:
            log.debug("InsertAxis2 failed: %s", traceback.format_exc())
            return None
        try:
            _get(doc, "ForceRebuild3", True)
        except Exception:
            pass
        created = [
            f
            for f in self._features_of(doc)
            if str(_get(f, "GetTypeName2")) == "RefAxis" and str(_get(f, "Name")) not in before
        ]
        return created[-1] if created else None
