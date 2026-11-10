"""Feature domain · extrude and cut (live SolidWorks).

S5-1a: _extrude_end_args + 4 internal COM wrappers.
S5-1b: + extrude_blind
S5-1c: + extrude_cut (includes _has_solid)

Dependencies (self, MRO):
- ``_call`` (STAThreadMixin)
- ``_map_error`` (STAThreadMixin)
- ``_select_pending_sketch`` / ``_consume_sketch_name`` (SketchMixin, S4-1a)
- ``_bodies_of`` (GeometryMixin, S3-3b)
- ``_get`` (_helpers)

imports:
- ``cadmcp.backend.protocol.constants`` (SW_END_* / EXTRUDE_DEPTHLESS)
- ``cadmcp.backend.protocol.validators`` (validate_extrude_options)
- ``cadmcp.backend.protocol.geometry_engine`` (thin_wall_com_args)
- ``cadmcp.errors`` (fail)
- ``._helpers`` (_get)
"""
from __future__ import annotations

import logging
import traceback
from typing import Any

from cadmcp.backend.protocol.constants import (
    EXTRUDE_DEPTHLESS,
    SW_END_BLIND,
    SW_END_MIDPLANE,
    SW_END_THROUGH_ALL,
    SW_END_UP_TO_NEXT,
    SW_END_UP_TO_SURFACE,
    SW_END_UP_TO_VERTEX,
)
from cadmcp.backend.protocol.geometry_engine import thin_wall_com_args
from cadmcp.backend.protocol.models import FeatureInfo
from cadmcp.backend.protocol.validators import (
    validate_extrude_options,
    validate_thin_options,
)
from cadmcp.errors import fail

from .._helpers import _get

log = logging.getLogger(__name__)


class ExtrudeMixin:
    """Extrude and cut (S5-1a: internal methods)."""

    def _init_state(self) -> None:
        pass  # stateless

    @staticmethod
    def _extrude_end_args(
        direction: str,
        depth_m: float,
        depth2_m: float | None,
        end_face: int | None = None,
        end_vertex: int | None = None,
        end_body: int | None = None,
    ) -> tuple[bool, int, int, float, float]:
        validate_extrude_options(direction, depth2_m, end_face, end_vertex, end_body)
        dummy = depth_m if depth_m > 0 else 0.01
        if direction == "midplane":
            return True, SW_END_MIDPLANE, 0, depth_m, depth_m
        if direction == "both":
            assert depth2_m is not None
            return False, SW_END_BLIND, SW_END_BLIND, depth_m, depth2_m
        if direction == "through_all":
            return True, SW_END_THROUGH_ALL, 0, dummy, dummy
        if direction == "up_to_next":
            return True, SW_END_UP_TO_NEXT, 0, dummy, dummy
        # up_to_body: native T1=7 / Modify up-to-body unavailable; creation uses up-to-face (T1=4).
        if direction in ("up_to_surface", "up_to_body"):
            return True, SW_END_UP_TO_SURFACE, 0, dummy, dummy
        if direction == "up_to_vertex":
            return True, SW_END_UP_TO_VERTEX, 0, dummy, dummy
        return True, SW_END_BLIND, 0, depth_m, depth_m

    def _resolve_body_hit_face(self, doc: Any, end_body: int) -> int:
        """Pick end face on target body: plane with largest centroid z (matches T2 Front offset cases).

        Feature tree shows up-to-face, not native UpToBody. May differ on complex bodies/profiles.
        """
        bodies = self._bodies_of(doc)
        if not bodies:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "Up-to-body extrude requires an existing solid",
                "Extrude a base body first, then direction=up_to_body",
            )
        if end_body < 0 or end_body >= len(bodies):
            raise fail(
                "INVALID_ARGUMENT",
                f"Body index out of range: {end_body}",
                f"Valid range 0..{len(bodies) - 1}; single-body parts are usually 0",
                index=end_body,
            )
        best: tuple[int, float] | None = None
        global_i = 0
        for bi, body in enumerate(bodies):
            for face in _get(body, "GetFaces") or ():
                if bi == end_body:
                    kind, centroid, normal, _axis = self._face_geometry(face)
                    if kind == "plane" and normal is not None:
                        z = float(centroid[2])
                        if best is None or z > best[1]:
                            best = (global_i, z)
                global_i += 1
        if best is None:
            raise fail(
                "FEATURE_CREATE_FAILED",
                f"Body {end_body} has no usable planar end face",
                "Change end_body, or use direction=up_to_surface with end_face",
                index=end_body,
            )
        return best[0]

    def _feature_extrusion2(
        self, doc: Any, sd: bool, reverse: bool, t1: int, t2: int, d1: float, d2: float,
        *, merge: bool = True,
    ) -> Any:
        fm = doc.FeatureManager
        try:
            return fm.FeatureExtrusion2(
                sd, False, reverse, t1, t2, d1, d2,
                False, False, False, False, 0.0, 0.0,
                False, False, False, False, merge, True, True,
                0, 0.0, False,
            )
        except Exception:
            log.debug("FeatureExtrusion2 long signature failed: %s", traceback.format_exc())
            return fm.FeatureExtrusion2(
                sd, False, reverse, t1, t2, d1, d2,
                False, False, False, False, 0.0, 0.0,
                False, False, False, merge, True, True, True,
            )

    def _feature_extrusion_thin2(
        self, doc: Any, sd: bool, reverse: bool, t1: int, t2: int, d1: float, d2: float,
        *, merge: bool, thk1: float, thk2: float, rev_thin: int,
    ) -> Any:
        return doc.FeatureManager.FeatureExtrusionThin2(
            sd, False, reverse, t1, t2, d1, d2,
            False, False, False, False, 0.0, 0.0,
            False, False, False, False, merge,
            thk1, thk2, 0.0, rev_thin, 0, False, 0.0,
            True, True, 0, 0.0, False,
        )

    def _feature_cut4(
        self, doc: Any, sd: bool, reverse: bool, t1: int, t2: int, d1: float, d2: float,
    ) -> Any:
        return doc.FeatureManager.FeatureCut4(
            sd, False, reverse, t1, t2, d1, d2,
            False, False, False, False, 0.0, 0.0,
            False, False, False, False, False, True, True,
            False, False, False, 0, 0.0, False,
            False,
        )

    def _feature_cut_thin2(
        self, doc: Any, sd: bool, reverse: bool, t1: int, t2: int, d1: float, d2: float,
        *, thk1: float, thk2: float, rev_thin: int,
    ) -> Any:
        return doc.FeatureManager.FeatureCutThin2(
            sd, False, reverse, t1, t2, d1, d2,
            False, False, False, False, 0.0, 0.0,
            False, False, False, False,
            thk1, thk2, 0.0, rev_thin, 0, False, 0.0,
            True, True, 0, 0.0, False,
        )

    def extrude_blind(
        self,
        depth_m: float,
        sketch: str | None = None,
        *,
        direction: str = "blind",
        depth2_m: float | None = None,
        reverse: bool = False,
        end_face: int | None = None,
        end_vertex: int | None = None,
        end_body: int | None = None,
        merge: bool = True,
        thin: bool = False,
        thickness_m: float | None = None,
        thin_type: str = "one",
    ) -> FeatureInfo:
        def _fn() -> FeatureInfo:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            validate_thin_options(thin, thickness_m, thin_type, direction)
            if direction not in EXTRUDE_DEPTHLESS and depth_m <= 0:
                raise fail(
                    "INVALID_ARGUMENT", f"Extrude depth must be positive (internal meters): {depth_m}",
                    "Pass depth > 0 (unit from unit parameter, default mm)",
                )
            if direction in (
                "through_all", "up_to_next", "up_to_vertex", "up_to_body",
            ) and not self._bodies_of(doc):
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Through/up-to-next/up-to-vertex/up-to-body extrude requires an existing solid",
                    "Extrude a base body first, then through_all / up_to_next / up_to_vertex / up_to_body",
                )
            hit_face = end_face
            if direction == "up_to_body":
                hit_face = self._resolve_body_hit_face(doc, int(end_body))
            sd, t1, t2, d1, d2 = self._extrude_end_args(
                direction, depth_m, depth2_m, end_face, end_vertex, end_body
            )
            pending = self._pending_sketch_name
            if pending is None or (sketch is not None and sketch != pending):
                raise fail(
                    "SKETCH_NOT_FOUND",
                    f"No ended sketch available for the feature (requested {sketch!r}, current: {pending})",
                    "Call start_sketch → draw → end_sketch, then run the feature",
                )

            def _pick() -> None:
                feat_sk = self._find_feature(doc, pending)
                doc.ClearSelection2(True)
                if feat_sk is None or not feat_sk.Select2(False, 0):
                    raise fail("SELECT_FAILED", f"Cannot select sketch {pending}", "Confirm the sketch still exists")
                if direction in ("up_to_surface", "up_to_body"):
                    if self._select_one_face(doc, int(hit_face), mark=1, clear=False) < 1:
                        raise fail(
                            "SELECT_FAILED",
                            f"Cannot select end face {hit_face}",
                            "Verify index with get_faces, or change end_body",
                        )
                if direction == "up_to_vertex":
                    if self._select_one_vertex(doc, int(end_vertex), mark=1, clear=False) < 1:
                        raise fail(
                            "SELECT_FAILED",
                            f"Cannot select end vertex {end_vertex}",
                            "Verify index with get_vertices",
                        )

            _pick()
            if thin:
                thk1, thk2, rev_thin = thin_wall_com_args(thin_type, float(thickness_m))
                feat = self._feature_extrusion_thin2(
                    doc, sd, reverse, t1, t2, d1, d2, merge=merge,
                    thk1=thk1, thk2=thk2, rev_thin=rev_thin,
                )
            else:
                feat = self._feature_extrusion2(doc, sd, reverse, t1, t2, d1, d2, merge=merge)
            if feat is None and direction in (
                "up_to_surface", "up_to_next", "up_to_vertex", "up_to_body",
            ) and not thin:
                _pick()
                feat = self._feature_extrusion2(doc, sd, not reverse, t1, t2, d1, d2, merge=merge)
            if feat is None:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "FeatureExtrusionThin2 returned None" if thin else "FeatureExtrusion2 returned None",
                    "Confirm the sketch is closed and in a valid state",
                )
            name = "Boss-Extrude"
            try:
                name = str(_get(feat, "GetName"))
            except Exception:
                try:
                    name = str(feat.Name)
                except Exception:
                    pass
            self._consume_sketch_name(pending)
            return FeatureInfo(name=self._register("Boss-Extrude", name), kind="extrude")

        return self._call(_fn)

    def extrude_cut(
        self,
        depth_m: float,
        sketch: str | None = None,
        *,
        direction: str = "blind",
        depth2_m: float | None = None,
        reverse: bool | None = None,
        end_face: int | None = None,
        end_vertex: int | None = None,
        end_body: int | None = None,
        thin: bool = False,
        thickness_m: float | None = None,
        thin_type: str = "one",
    ) -> FeatureInfo:
        def _fn() -> FeatureInfo:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            validate_thin_options(thin, thickness_m, thin_type, direction)
            _sk_feat, sk_name = self._select_pending_sketch(doc, sketch)
            if direction not in EXTRUDE_DEPTHLESS and depth_m <= 0:
                raise fail(
                    "INVALID_ARGUMENT", f"Cut depth must be positive (internal meters): {depth_m}",
                    "Pass depth > 0 (unit from unit parameter, default mm)",
                )
            hit_face = end_face
            if direction == "up_to_body":
                hit_face = self._resolve_body_hit_face(doc, int(end_body))
            sd, t1, t2, d1, d2 = self._extrude_end_args(
                direction, depth_m, depth2_m, end_face, end_vertex, end_body
            )
            # Dir=False when sketch plane already cuts into solid; Dir=True when flush on boss face (live probe).
            # When reverse is omitted, probe False→True so front-view holes through-thickness.
            dir_tries = (bool(reverse),) if reverse is not None else (False, True)
            feat = None
            last_exc: Exception | None = None
            try:
                for ddir in dir_tries:
                    try:
                        self._select_pending_sketch(doc, sketch)
                        if direction in ("up_to_surface", "up_to_body"):
                            if self._select_one_face(doc, int(hit_face), mark=1, clear=False) < 1:
                                raise fail(
                                    "SELECT_FAILED",
                                    f"Cannot select end face {hit_face}",
                                    "Verify index with get_faces, or change end_body",
                                )
                        if direction == "up_to_vertex":
                            if self._select_one_vertex(doc, int(end_vertex), mark=1, clear=False) < 1:
                                raise fail(
                                    "SELECT_FAILED",
                                    f"Cannot select end vertex {end_vertex}",
                                    "Verify index with get_vertices",
                                )
                        if thin:
                            thk1, thk2, rev_thin = thin_wall_com_args(thin_type, float(thickness_m))
                            feat = self._feature_cut_thin2(
                                doc, sd, ddir, t1, t2, d1, d2,
                                thk1=thk1, thk2=thk2, rev_thin=rev_thin,
                            )
                        else:
                            feat = self._feature_cut4(doc, sd, ddir, t1, t2, d1, d2)
                    except Exception as exc:
                        last_exc = exc
                        log.debug("FeatureCut Dir=%s failed: %s", ddir, traceback.format_exc())
                        feat = None
                    if feat is not None:
                        break
                if feat is None and last_exc is not None:
                    raise last_exc
            except Exception as exc:
                log.debug("extrude_cut failed: %s", traceback.format_exc())
                raise self._map_error(exc) from exc
            if feat is None:
                raise fail(
                    "FEATURE_CREATE_FAILED", "Extrude cut failed",
                    "Confirm material exists, sketch is valid, and cut direction passes through material",
                )
            try:
                name = str(_get(feat, "Name"))
            except Exception:
                name = "Cut-Extrude"
            self._consume_sketch_name(sk_name)
            return FeatureInfo(name=self._register("Cut-Extrude", name), kind="extrude_cut")

        return self._call(_fn)
