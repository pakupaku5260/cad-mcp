"""Feature domain · patterns / mirror (live SolidWorks).

S5-4: linear_pattern_blind / circular_pattern_blind / mirror_feature

Dependencies (self, MRO):
- ``_call`` / ``_map_error`` (STAThreadMixin)
- ``_resolve_feature`` / ``_feature_real_name`` / ``_register`` (NamingMixin)
- ``_select_plane`` / ``_select_one_edge`` / ``_select_ref_axis`` (SelectionMixin)
- ``_ensure_ref_axis`` (PlaneAxisMixin)
- ``_bodies_of`` / ``_bodies_of_feature`` (GeometryMixin)
- ``_get`` (_helpers)

imports:
- ``cadmcp.backend.protocol.constants`` (REVOLVE_AXES)
- ``cadmcp.backend.protocol.models`` (FeatureInfo)
- ``cadmcp.errors`` (fail)
- ``._constants`` (SW_DOC_PART / _SW_MIRROR_*)
- ``.._helpers`` (_get)
"""
from __future__ import annotations

import logging
import math
import traceback
from typing import Any

from cadmcp.backend.protocol.constants import REVOLVE_AXES
from cadmcp.backend.protocol.models import FeatureInfo
from cadmcp.errors import fail

from .._constants import (
    _SW_MIRROR_BODY_MARK,
    _SW_MIRROR_FEAT_MARK,
    _SW_MIRROR_PLANE_MARK,
    SW_DOC_PART,
)
from .._helpers import _get

log = logging.getLogger(__name__)


class PatternMixin:
    """Patterns / mirror (S5-4: 3 methods)."""

    def _init_state(self) -> None:
        pass  # stateless

    def linear_pattern_blind(
        self, feature: str, dx_m: float, dy_m: float, dz_m: float, count: int,
    ) -> FeatureInfo:
        def _fn() -> FeatureInfo:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            if count < 2:
                raise fail("INVALID_ARGUMENT", f"Pattern count must be >= 2: {count}", "Pass count >= 2")

            # Spacing vector must lie on a single axis; direction ref = plane perpendicular (normal = axis)
            eps = 1e-12
            comps = [(abs(dx_m) > eps, "Right Plane", dx_m),
                     (abs(dy_m) > eps, "Top Plane", dy_m),
                     (abs(dz_m) > eps, "Front Plane", dz_m)]
            used = [c for c in comps if c[0]]
            if len(used) != 1:
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Linear pattern spacing must lie on exactly one axis: ({dx_m}, {dy_m}, {dz_m})",
                    "Set only one of dx, dy, dz nonzero",
                )
            _, direction_plane, spacing = used[0]

            src = self._resolve_feature(doc, feature)
            doc.ClearSelection2(True)
            if not src.Select2(False, 4):  # source feature: mark 4
                raise fail("SELECT_FAILED", f"Cannot select pattern source feature {feature}", "Confirm the feature exists")
            if not self._select_plane(doc, direction_plane, append=True, mark=1):  # direction: mark 1
                raise fail("SELECT_FAILED", "Cannot select pattern direction reference", "Confirm the reference plane exists")
            try:
                feat = doc.FeatureManager.FeatureLinearPattern(
                    count, abs(spacing), 1, 0.0, spacing < 0, False, "", "",
                )
            except Exception as exc:
                log.debug("FeatureLinearPattern failed: %s", traceback.format_exc())
                raise self._map_error(exc) from exc
            finally:
                doc.ClearSelection2(True)
            if feat is None:
                raise fail(
                    "FEATURE_CREATE_FAILED", "Linear pattern creation failed",
                    "Confirm the source can be patterned and direction/spacing are valid",
                )
            real = self._feature_real_name(feat, "LPattern")
            return FeatureInfo(name=self._register("LPattern", real), kind="linear_pattern")

        return self._call(_fn)

    def circular_pattern_blind(
        self,
        feature: str,
        count: int,
        axis: str,
        edge_index: int | None = None,
    ) -> FeatureInfo:
        def _fn() -> FeatureInfo:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            if count < 2:
                raise fail("INVALID_ARGUMENT", f"Pattern count must be >= 2: {count}", "Pass count >= 2")
            if axis not in REVOLVE_AXES:
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Unknown circular pattern axis: {axis!r}",
                    f"Axes: {', '.join(REVOLVE_AXES)}",
                    requested=axis,
                )
            src = self._resolve_feature(doc, feature)
            axis_feat = None
            if edge_index is None:
                axis_feat = self._ensure_ref_axis(doc, axis)
                src = self._resolve_feature(doc, feature)
            doc.ClearSelection2(True)
            if not src.Select2(False, 4):
                raise fail("SELECT_FAILED", f"Cannot select pattern source feature {feature}", "Confirm the feature exists")
            if edge_index is not None:
                if self._select_one_edge(doc, edge_index, mark=1) == 0:
                    raise fail(
                        "SELECT_FAILED",
                        f"Cannot select pattern axis edge {edge_index}",
                        "Use get_edges for straight edges",
                    )
            elif not self._select_ref_axis(doc, axis_feat, mark=1):
                raise fail(
                    "SELECT_FAILED",
                    f"Cannot select circular pattern axis {axis}",
                    "Pass edge=get_edges straight-edge index instead",
                )
            try:
                feat = doc.FeatureManager.FeatureCircularPattern3(
                    count, math.tau / count, axis.startswith("-"), "", False, False,
                )
            except Exception as exc:
                log.debug("FeatureCircularPattern3 failed: %s", traceback.format_exc())
                raise self._map_error(exc) from exc
            finally:
                doc.ClearSelection2(True)
            if feat is None:
                raise fail(
                    "FEATURE_CREATE_FAILED", "Circular pattern creation failed",
                    "Confirm the source can be patterned and axis is a line edge or origin axis",
                )
            real = self._feature_real_name(feat, "CirPattern")
            return FeatureInfo(name=self._register("CirPattern", real), kind="circular_pattern")

        return self._call(_fn)

    def mirror_feature(self, feature: str, plane: str, scope: str = "body") -> FeatureInfo:
        def _fn() -> FeatureInfo:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            if int(_get(doc, "GetType")) != SW_DOC_PART:
                raise fail("INVALID_ARGUMENT", "Active document is not a part", "Use a part document for mirror")
            if scope not in ("body", "feature"):
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Unknown mirror scope: {scope!r}",
                    "scope: body or feature",
                    requested=scope,
                )
            src = self._resolve_feature(doc, feature)
            sm = _get(doc, "SelectionManager")
            bodies: list[Any] = []
            if scope == "body":
                bodies = self._bodies_of_feature(src) or self._bodies_of(doc)
                if not bodies:
                    raise fail(
                        "FEATURE_CREATE_FAILED",
                        f"Feature {feature!r} has no solid body to mirror",
                        "Extrude a solid first, then mirror",
                    )
            fm = doc.FeatureManager
            feat = None
            body = scope == "body"

            def _select() -> None:
                doc.ClearSelection2(True)
                if body:
                    data = _get(sm, "CreateSelectData")
                    data.Mark = _SW_MIRROR_BODY_MARK
                    if not bodies[0].Select2(False, data):
                        raise fail("SELECT_FAILED", f"Cannot select solid for {feature}", "Confirm the feature produced a solid")
                    for extra in bodies[1:]:
                        extra.Select2(True, data)
                elif not src.Select2(False, _SW_MIRROR_FEAT_MARK):
                    raise fail("SELECT_FAILED", f"Cannot select feature {feature}", "Use list_features")
                if not self._select_plane(doc, plane, append=True, mark=_SW_MIRROR_PLANE_MARK):
                    raise fail(
                        "INVALID_ARGUMENT",
                        f"Reference plane not found: {plane!r}",
                        "Use list_planes for available plane names",
                        requested=plane,
                    )

            for merge in (False, True):
                _select()
                try:
                    feat = fm.InsertMirrorFeature(body, False, merge, False)
                except Exception as exc:
                    log.debug("InsertMirrorFeature failed: %s", traceback.format_exc())
                    raise self._map_error(exc) from exc
                if feat is not None:
                    break
            try:
                _get(doc, "ForceRebuild3", True)
            except Exception:
                pass
            if feat is None:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Mirror feature creation failed",
                    "Confirm source has a solid and the plane exists; surface bosses may need scope=body",
                )
            real = self._feature_real_name(feat, "Mirror")
            return FeatureInfo(name=self._register("Mirror", real), kind="mirror")

        return self._call(_fn)
