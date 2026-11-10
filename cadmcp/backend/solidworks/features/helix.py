"""Features · helix / sweep / loft.

S5-6a：create_helix + _last_helix_feature
S5-6b：+ _resolve_sweep_pair / _sweep_impl / sweep / sweep_cut
S5-6c：+ loft / loft_cut / _loft_impl / _as_completed_sketch / _resolve_loft_guides

Dependencies (self, MRO):
- `_call` / `_map_error`（STAThreadMixin）
- `_select_pending_sketch` / `_consume_sketch_name` / `_pending_sketch_name`（SketchMixin）
- `_features_of` / `_feature_real_name` / `_register` / `_find_feature` / `_real_name` /
  `_completed_sketches`（NamingMixin / SketchMixin）
- `_feature_kind`（SurfaceMixin，S5-5）
- `_get`（_helpers）

imports:
- `cadmcp.backend.protocol.models`（FeatureInfo / HelixInfo）
- `cadmcp.errors`（fail）
- `.._constants`（_HELIX_PITCH_REV / _HELIX_HEIGHT_PITCH / _HELIX_FEATURE_TYPES / _SKETCH_FEATURE_TYPES）
- `.._helpers`（_get）
"""
from __future__ import annotations

import logging
import traceback
from collections.abc import Sequence
from typing import Any

from cadmcp.backend.protocol.models import FeatureInfo, HelixInfo
from cadmcp.errors import fail

from .._constants import (
    _HELIX_FEATURE_TYPES,
    _HELIX_HEIGHT_PITCH,
    _HELIX_PITCH_REV,
    _LOFT_BOSS_ARGS,
    _LOFT_CENTERLINE_MARK,
    _LOFT_CUT_ARGS,
    _SKETCH_FEATURE_TYPES,
)
from .._helpers import _get

log = logging.getLogger(__name__)


class HelixMixin:
    """Helix / sweep / loft (S5-6a: 2 methods)."""

    def _init_state(self) -> None:
        pass  # stateless

    def create_helix(
        self,
        pitch_m: float,
        revolutions: float = 1.0,
        height_m: float | None = None,
        start_angle_rad: float = 0.0,
        clockwise: bool = False,
    ) -> HelixInfo:
        def _fn() -> HelixInfo:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            if pitch_m <= 0:
                raise fail("INVALID_ARGUMENT", "Pitch must be positive", "Pass pitch > 0")
            if height_m is None:
                if revolutions <= 0:
                    raise fail("INVALID_ARGUMENT", "Revolution count must be positive", "Pass revolutions > 0, or pass height instead")
                helixdef, height, revs = _HELIX_PITCH_REV, 0.0, float(revolutions)
            else:
                if height_m <= 0:
                    raise fail("INVALID_ARGUMENT", "Helix height must be positive", "Pass height > 0")
                helixdef, height, revs = _HELIX_HEIGHT_PITCH, float(height_m), 0.0
            # Prerequisite: select completed circle sketch (probe: InsertHelix after Select2)
            _sk_feat, sk_name = self._select_pending_sketch(doc, None)
            before = {str(_get(f, "Name")) for f in self._features_of(doc)}
            try:
                # InsertHelix(Reversed, Clockwised, Tapered, Outward, Helixdef,
                #             Height, Pitch, Revolution, TaperAngle, Startangle)
                # Length in meters, angle in radians (probe: SI args work; GetDefinition unreadable with late binding)
                doc.InsertHelix(
                    False, bool(clockwise), False, False, helixdef,
                    height, float(pitch_m), revs, 0.0, float(start_angle_rad),
                )
            except Exception as exc:
                log.debug("InsertHelix failed: %s", traceback.format_exc())
                raise self._map_error(exc) from exc
            new = [f for f in self._features_of(doc) if str(_get(f, "Name")) not in before]
            helix_feats = []
            for f in new:
                try:
                    if str(_get(f, "GetTypeName2")) == "Helix":
                        helix_feats.append(f)
                except Exception:
                    continue
            if not helix_feats:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Failed to create helix",
                    "Need a circle after end_sketch; rectangles cannot make a helix",
                )
            self._pending_sketch_name = None
            real = self._feature_real_name(helix_feats[-1], "Helix")
            self._consume_sketch_name(sk_name)
            return HelixInfo(name=self._register("Helix", real))

        return self._call(_fn)

    def _last_helix_feature(self, doc: Any) -> tuple[str, Any] | None:
        last: tuple[str, Any] | None = None
        for feat in self._features_of(doc):
            try:
                if str(_get(feat, "GetTypeName2")) == "Helix":
                    last = (str(_get(feat, "Name")), feat)
            except Exception:
                continue
        return last

    def _resolve_sweep_pair(
        self, doc: Any, profile_sketch: str | None, path_sketch: str | None,
    ) -> tuple[str, bool, str, bool]:
        """Resolve profile/path: explicit names first, else profile=last completed sketch, path=previous (or helix)."""
        if self._sketch_open:
            raise fail(
                "SKETCH_OP_FAILED",
                "Sketch is still open; close it before creating a feature",
                "Call end_sketch to close the sketch, then create the feature",
            )
        completed = list(self._completed_sketches)

        def _as_sketch(name: str) -> str | None:
            real = self._real_name(name)
            if real in completed:
                return real
            if name in completed:
                return name
            return None

        if profile_sketch is not None:
            profile = _as_sketch(profile_sketch)
            if profile is None:
                feat = self._find_feature(doc, profile_sketch)
                if feat is not None and self._feature_kind(feat) in _SKETCH_FEATURE_TYPES:
                    profile = self._feature_real_name(feat, profile_sketch)
            if profile is None:
                raise fail(
                    "SKETCH_NOT_FOUND",
                    f"Profile sketch not found {profile_sketch!r}",
                    "start_sketch → closed profile → end_sketch; or omit name for last completed sketch",
                    requested=profile_sketch,
                )
        else:
            if not completed:
                raise fail(
                    "SKETCH_NOT_FOUND",
                    "No profile sketch available for sweep",
                    "Sketch path and end_sketch, then profile and end_sketch, then sweep",
                )
            profile = completed[-1]

        path: tuple[str, bool] | None = None
        if path_sketch is not None:
            sk = _as_sketch(path_sketch)
            if sk is not None:
                path = (sk, True)
            else:
                feat = self._find_feature(doc, path_sketch)
                if feat is not None and self._feature_kind(feat) in _HELIX_FEATURE_TYPES:
                    path = (self._feature_real_name(feat, path_sketch), False)
        else:
            others = [x for x in completed if x != profile]
            if others:
                path = (others[-1], True)
            else:
                helix = self._last_helix_feature(doc)
                if helix is not None:
                    path = (helix[0], False)
        if path is None:
            raise fail(
                "SKETCH_NOT_FOUND",
                f"Path sketch not found {path_sketch!r} (available sketches: {', '.join(completed) or 'none'}）",
                "Sweep needs two sketches: path then profile, each end_sketch; or pass path_sketch",
                requested=path_sketch,
            )
        if path[1] and path[0] == profile:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "Profile sketch cannot also be the path",
                "Create separate path and profile sketches, then sweep",
            )
        return profile, True, path[0], path[1]

    def _sweep_impl(
        self, kind: str, profile_sketch: str | None, path_sketch: str | None,
    ) -> FeatureInfo:
        def _fn() -> FeatureInfo:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            profile_name, profile_is_sketch, path_name, path_is_sketch = self._resolve_sweep_pair(
                doc, profile_sketch, path_sketch,
            )
            if kind == "sweep_cut":
                try:
                    bodies = _get(doc, "GetBodies2", 0, False) or ()
                except Exception:
                    log.debug("GetBodies2 failed: %s", traceback.format_exc())
                    bodies = ()
                if not bodies:
                    raise fail(
                        "FEATURE_CREATE_FAILED",
                        "No material to cut (no solid features yet)",
                        "extrude or revolve a base solid first, then sweep cut",
                    )
            doc.ClearSelection2(True)
            if not self._select_sketch_or_curve(
                doc, profile_name, append=False, mark=1, is_sketch=profile_is_sketch,
            ):
                raise fail(
                    "SELECT_FAILED",
                    f"Cannot select sweep profile {profile_name!r}",
                    "Confirm sketch is in the tree and not deleted or suppressed",
                )
            if not self._select_sketch_or_curve(
                doc, path_name, append=True, mark=4, is_sketch=path_is_sketch,
            ):
                raise fail(
                    "SELECT_FAILED",
                    f"Cannot select sweep path {path_name!r}",
                    "Confirm path sketch/helix in tree; path and profile meet at an endpoint",
                )
            # 2025 probe: full path sketch mark=4 sweeps U polyline; broken segments return None from InsertProtrusionSwept4.
            # TwistAngle / TwistCtrlOption hits DISP_E_MEMBERNOTFOUND; no twist in this phase.
            fm = doc.FeatureManager
            try:
                if kind == "sweep":
                    feat = fm.InsertProtrusionSwept4(
                        False, True, 0, False, False, 0, 0,
                        False, 0.0, 0.0, 0, 0,
                        True, True, True, 0.0, True,
                        False, 0.0, 0,
                    )
                else:
                    # Official Insert Swept-cut 19-parameter combo from sample
                    feat = fm.InsertCutSwept4(
                        False, True, 0, False, False, 0, 0,
                        False, 0.0, 0.0, 0, 0,
                        True, True, 0.0, True,
                        True, True, False,
                    )
            except Exception as exc:
                log.debug("%s failed: %s", kind, traceback.format_exc())
                raise self._map_error(exc) from exc
            finally:
                self._clear_selection(doc)
            if feat is None:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Sweep failed (API returned None)",
                    "Confirm closed profile, path meets profile, sweep is self-intersection-free",
                )
            prefix = "Sweep" if kind == "sweep" else "Cut-Sweep"
            real = self._feature_real_name(feat, prefix)
            self._consume_sketch_name(profile_name)
            if path_is_sketch:
                self._consume_sketch_name(path_name)
            self._pending_sketch_name = None
            return FeatureInfo(name=self._register(prefix, real), kind=kind)

        return self._call(_fn, timeout=180.0)

    def sweep(
        self, profile_sketch: str | None = None, path_sketch: str | None = None,
    ) -> FeatureInfo:
        return self._sweep_impl("sweep", profile_sketch, path_sketch)

    def sweep_cut(
        self, profile_sketch: str | None = None, path_sketch: str | None = None,
    ) -> FeatureInfo:
        return self._sweep_impl("sweep_cut", profile_sketch, path_sketch)

    def loft(
        self,
        profiles: Sequence[str] | None = None,
        *,
        guides: Sequence[str] | None = None,
        centerline: str | None = None,
    ) -> FeatureInfo:
        return self._loft_impl("loft", profiles, guides, centerline)

    def loft_cut(
        self,
        profiles: Sequence[str] | None = None,
        *,
        guides: Sequence[str] | None = None,
        centerline: str | None = None,
    ) -> FeatureInfo:
        return self._loft_impl("loft_cut", profiles, guides, centerline)

    def _as_completed_sketch(self, doc: Any, name: str) -> str | None:
        completed = list(self._completed_sketches)
        real = self._real_name(name)
        if real in completed:
            return real
        if name in completed:
            return name
        feat = self._find_feature(doc, name)
        if feat is not None and self._feature_kind(feat) in _SKETCH_FEATURE_TYPES:
            return self._feature_real_name(feat, name)
        return None

    def _sketch_is_closed_profile(self, doc: Any, name: str) -> bool:
        feat = self._find_feature(doc, name)
        if feat is None:
            return False
        try:
            sk = _get(feat, "GetSpecificFeature2")
            regions = list(_get(sk, "GetSketchRegions") or [])
            if regions:
                return True
        except Exception:
            log.debug("Read sketch regions failed: %s", traceback.format_exc())
        try:
            sk = _get(feat, "GetSpecificFeature2")
            segs = list(_get(sk, "GetSketchSegments") or [])
            if segs and all(int(_get(s, "GetType")) == 1 for s in segs):
                return True
        except Exception:
            log.debug("Read sketch segments failed: %s", traceback.format_exc())
        return False

    def _resolve_loft_guides(
        self, doc: Any, guides: Sequence[str] | None, profiles: Sequence[str],
    ) -> list[str]:
        if not guides:
            return []
        prof = set(profiles)
        out: list[str] = []
        for raw in guides:
            found = self._as_completed_sketch(doc, str(raw))
            if found is None:
                raise fail(
                    "SKETCH_NOT_FOUND",
                    f"Loft guide sketch not found {raw!r}",
                    "Use completed open-curve sketch name, e.g. lateral line Sketch3",
                    requested=raw,
                )
            if found in prof or str(raw) in prof or self._real_name(str(raw)) in prof:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    f"Guide {raw!r} cannot also be a profile",
                    "guides: separate open-curve sketch, not a profile name",
                    requested=raw,
                )
            if self._sketch_is_closed_profile(doc, found):
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    f"Guide {raw!r} must be an open curve",
                    "sketch_line for lateral guide; do not use closed circle/rectangle",
                    requested=raw,
                )
            out.append(found)
        return out

    def _sketch_is_open_curve(self, doc: Any, name: str) -> bool:
        """Centerline: no closed regions and not a full circle with coincident ends. Single arc/spline/line counts as open."""
        feat = self._find_feature(doc, self._real_name(name)) or self._find_feature(doc, name)
        if feat is None:
            return False
        try:
            sk = _get(feat, "GetSpecificFeature2")
        except Exception:
            log.debug("Read centerline sketch failed: %s", traceback.format_exc())
            return False
        try:
            if list(_get(sk, "GetSketchRegions") or []):
                return False
        except Exception:
            log.debug("Read sketch regions failed: %s", traceback.format_exc())
        try:
            segs = [s for s in list(_get(sk, "GetSketchSegments") or []) if s is not None]
        except Exception:
            log.debug("Read sketch segments failed: %s", traceback.format_exc())
            return False
        if not segs:
            return False
        if len(segs) == 1:
            try:
                if int(_get(segs[0], "GetType")) == 1:
                    start = _get(segs[0], "GetStartPoint2")
                    end = _get(segs[0], "GetEndPoint2")
                    same = all(
                        abs(float(_get(start, axis)) - float(_get(end, axis))) < 1e-9
                        for axis in ("X", "Y", "Z")
                    )
                    if same:
                        return False
            except Exception:
                log.debug("Check if arc is closed failed: %s", traceback.format_exc())
        return True

    def _resolve_loft_centerline(
        self, doc: Any, centerline: str | None, profiles: Sequence[str],
    ) -> str | None:
        if not centerline:
            return None
        found = self._as_completed_sketch(doc, str(centerline))
        if found is None:
            raise fail(
                "SKETCH_NOT_FOUND",
                f"Loft centerline sketch not found {centerline!r}",
                "Use completed open-curve name, e.g. 3D arc Sketch3",
                requested=centerline,
            )
        if found in profiles or str(centerline) in profiles or self._real_name(str(centerline)) in profiles:
            raise fail(
                "FEATURE_CREATE_FAILED",
                f"Centerline {centerline!r} cannot also be a profile",
                "centerline: separate open-curve sketch, not a profile name",
                requested=centerline,
            )
        if not self._sketch_is_open_curve(doc, found):
            raise fail(
                "FEATURE_CREATE_FAILED",
                f"Centerline {centerline!r} must be an open curve",
                "Use 3D line, arc, or spline; not closed circle/rectangle",
                requested=centerline,
            )
        return found

    def _loft_impl(
        self,
        kind: str,
        profiles: Sequence[str] | None,
        guides: Sequence[str] | None = None,
        centerline: str | None = None,
    ) -> FeatureInfo:
        def _fn() -> FeatureInfo:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create a part first")
            self._require_part_doc(doc, "Use a part document for loft")
            if guides and centerline:
                raise fail(
                    "INVALID_ARGUMENT",
                    "Loft cannot use both guides and centerline",
                    "Use guides or centerline, not both",
                )
            names = self._resolve_loft_profiles(doc, profiles)
            guide_names = self._resolve_loft_guides(doc, guides, names)
            center_name = self._resolve_loft_centerline(doc, centerline, names)
            if kind == "loft_cut" and not self._has_solid(doc):
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "No material to cut (no solid features yet)",
                    "extrude base solid first, then loft_cut",
                )
            doc.ClearSelection2(True)
            for i, name in enumerate(names):
                if not self._select_sketch_or_curve(doc, name, append=i > 0, mark=1, is_sketch=True):
                    raise fail(
                        "SELECT_FAILED",
                        f"Cannot select loft profile {name!r}",
                        "Confirm sketch is in the tree and not deleted or suppressed",
                    )
            for gname in guide_names:
                if not self._select_sketch_or_curve(doc, gname, append=True, mark=2, is_sketch=True):
                    raise fail(
                        "SELECT_FAILED",
                        f"Cannot select loft guide {gname!r}",
                        "Completed open-curve name; guide must pierce every profile",
                    )
            if center_name is not None:
                n_seg = self._select_sketch_segments(
                    doc, center_name, mark=_LOFT_CENTERLINE_MARK,
                )
                if n_seg < 1:
                    raise fail(
                        "SELECT_FAILED",
                        f"Cannot select loft centerline {center_name!r}",
                        "Centerline must be sketch segments; do not pick closed profiles",
                    )
            fm = doc.FeatureManager
            wrote_center = False
            try:
                if kind == "loft":
                    feat = fm.InsertProtrusionBlend(*_LOFT_BOSS_ARGS)
                else:
                    feat = fm.InsertCutBlend(*_LOFT_CUT_ARGS)
                if center_name and feat is not None:
                    try:
                        wrote_center = _get(_get(feat, "GetDefinition"), "Centerline") is not None
                    except Exception:
                        log.debug("Read Centerline failed: %s", traceback.format_exc())
                        wrote_center = False
            except Exception as exc:
                log.debug("%s failed: %s", kind, traceback.format_exc())
                raise self._map_error(exc) from exc
            finally:
                self._clear_selection(doc)
            if feat is None:
                if center_name:
                    hint = (
                        "Centerline must pierce each profile plane; tight bends or >semicircle may "
                        "return None. Use a gentler 3D arc or spline"
                    )
                elif guide_names:
                    hint = "Guides must pierce all profiles (e.g. line joining circles in Top); otherwise API returns None"
                else:
                    hint = "Confirm closed non-coplanar profiles and loft without self-intersection"
                raise fail("FEATURE_CREATE_FAILED", "Loft failed (API returned None)", hint)
            if guide_names:
                n_guides = 0
                try:
                    n_guides = int(_get(_get(feat, "GetDefinition"), "GetGuideCurvesCount") or 0)
                except Exception:
                    log.debug("Read GetGuideCurvesCount failed: %s", traceback.format_exc())
                    n_guides = -1
                if n_guides == 0:
                    try:
                        feat.Select2(False, 0)
                        doc.EditDelete()
                    except Exception:
                        log.debug("Delete loft without guides failed: %s", traceback.format_exc())
                    raise fail(
                        "FEATURE_CREATE_FAILED",
                        "Loft did not apply guide curves",
                        "Use open curves piercing all profiles (Top line or 3D sketch), not disjoint lateral lines",
                    )
            if center_name and not wrote_center:
                try:
                    feat.Select2(False, 0)
                    doc.EditDelete()
                except Exception:
                    log.debug("Delete loft without centerline failed: %s", traceback.format_exc())
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Loft did not apply centerline",
                    "Use open segments piercing profiles; whole sketch is not treated as centerline",
                )
            prefix = "Loft" if kind == "loft" else "Cut-Loft"
            real = self._feature_real_name(feat, prefix)
            for name in names:
                self._consume_sketch_name(name)
            self._pending_sketch_name = None
            return FeatureInfo(name=self._register(prefix, real), kind=kind)

        return self._call(_fn, timeout=180.0)

