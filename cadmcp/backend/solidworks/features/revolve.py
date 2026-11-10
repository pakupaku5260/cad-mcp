"""Feature domain · revolve (live SolidWorks).

Dependencies (self, MRO):
- ``_call`` / ``_map_error`` (STAThreadMixin)
- ``_select_pending_sketch`` / ``_consume_sketch_name`` (SketchMixin)
- ``_part_edge_objects`` / ``_edge_geometry`` (GeometryMixin)
- ``_get`` (_helpers)

imports:
- ``cadmcp.backend.protocol.constants`` (REVOLVE_AXES)
- ``cadmcp.backend.protocol.models`` (FeatureInfo)
- ``cadmcp.errors`` (CadMcpError / fail)
- ``.._helpers`` (_get)
"""
from __future__ import annotations

import logging
import math
import traceback

from cadmcp.backend.protocol.constants import REVOLVE_AXES
from cadmcp.backend.protocol.models import FeatureInfo
from cadmcp.errors import CadMcpError, fail

from .._helpers import _get

log = logging.getLogger(__name__)


class RevolveMixin:
    """Revolve (S5-2: 1 method)."""

    def _init_state(self) -> None:
        pass  # stateless

    def revolve_blind(
        self,
        angle_rad: float,
        axis: str,
        sketch: str | None = None,
        edge_index: int | None = None,
    ) -> FeatureInfo:
        def _fn() -> FeatureInfo:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            sk_feat, sk_name = self._select_pending_sketch(doc, sketch)
            if edge_index is None and axis not in REVOLVE_AXES:
                raise fail(
                    "INVALID_ARGUMENT", f"Unknown revolve axis: {axis!r}",
                    f"Valid axes: {', '.join(REVOLVE_AXES)}", requested=axis,
                )
            if not 0.0 < angle_rad <= math.tau + 1e-9:
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Revolve angle must be in (0, 360] deg (internal radians): {angle_rad}",
                    "Pass 0 < angle_deg <= 360",
                )
            try:
                sm = doc.SketchManager
                sel_data = _get(_get(doc, "SelectionManager"), "CreateSelectData")
                sel_data.Mark = 4
                if edge_index is not None:
                    pool = self._part_edge_objects(doc)
                    if edge_index < 0 or edge_index >= len(pool):
                        raise fail(
                            "INVALID_ARGUMENT",
                            f"Edge index out of range: {edge_index}",
                            f"Use get_edges; valid range 0..{len(pool) - 1}" if pool else "Create a solid first",
                            index=edge_index,
                        )
                    kind, _mid = self._edge_geometry(pool[edge_index])
                    if kind != "line":
                        raise fail(
                            "INVALID_ARGUMENT",
                            f"Revolve axis edge must be a line (got {kind!r})",
                            "Use get_edges and pick kind=line index",
                        )
                    doc.ClearSelection2(True)
                    sk_feat.Select2(False, 0)
                    if not pool[edge_index].Select4(True, sel_data):
                        raise fail("SELECT_FAILED", "Cannot select revolve axis edge", "Confirm get_edges index is still valid")
                else:
                    span = 0.1  # meters; axis is infinite — any non-zero length works
                    p = (-span, 0.0, span, 0.0) if axis[1] == "x" else (0.0, -span, 0.0, span)
                    sm.InsertSketch(True)
                    try:
                        seg = sm.CreateCenterLine(p[0], p[1], 0.0, p[2], p[3], 0.0)
                    finally:
                        sm.InsertSketch(True)
                    if seg is None:
                        raise fail("FEATURE_CREATE_FAILED", "Failed to create revolve axis centerline", "Confirm the sketch is editable")
                    sketch_obj = _get(sk_feat, "GetSpecificFeature2")
                    axis_seg = None
                    for s in _get(sketch_obj, "GetSketchSegments") or ():
                        try:
                            if bool(_get(s, "ConstructionGeometry")):
                                axis_seg = s
                        except Exception:
                            continue
                    if axis_seg is None:
                        raise fail("FEATURE_CREATE_FAILED", "Revolve axis centerline not found", "Confirm a construction line exists in the sketch")
                    doc.ClearSelection2(True)
                    sk_feat.Select2(False, 0)
                    if not axis_seg.Select4(True, sel_data):
                        raise fail("SELECT_FAILED", "Cannot select revolve axis", "Confirm the centerline is valid")
                feat = doc.FeatureManager.FeatureRevolve2(
                    True, True, False, False, False, False, 0, 0,
                    angle_rad, 0.0, False, False, 0.0, 0.0, 0, 0.0, 0.0,
                    True, True, True,
                )
            except CadMcpError:
                raise
            except Exception as exc:
                log.debug("revolve failed: %s", traceback.format_exc())
                raise self._map_error(exc) from exc
            if feat is None:
                raise fail(
                    "FEATURE_CREATE_FAILED", "FeatureRevolve2 returned None",
                    "Confirm profile is closed and does not cross the axis; edge axis must be coplanar with the sketch",
                )
            try:
                name = str(_get(feat, "Name"))
            except Exception:
                name = "Revolve"
            self._consume_sketch_name(sk_name)
            return FeatureInfo(name=name, kind="revolve")

        return self._call(_fn)
