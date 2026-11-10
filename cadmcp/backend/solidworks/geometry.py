"""COM backend · geometry (faces/edges/bbox/transforms).

All geometry methods compose with ComBackend via MRO.

Dependencies (self):
- ``_bodies_of`` (this module, S3-3b)
- ``_write_comp_transform`` (this module, S3-3c)
- ``_select_component`` (SelectionMixin, migrated)
- ``_assembly_component_objs`` (AssemblyMixin, S6)

imports:
- ``math``
- ``._constants._SURFACE_KINDS / _CURVE_KINDS / _SW_COMP_LIGHTWEIGHT``
- ``._helpers._as_bbox6 / _union_bbox6 / _get``
"""
from __future__ import annotations

import logging
import math
import traceback
from typing import Any

from ._constants import (
    _CURVE_KINDS,
    _SURFACE_KINDS,
    _SW_COMP_LIGHTWEIGHT,
    SW_DOC_ASSEMBLY,
)
from ._helpers import _as_bbox6, _get, _union_bbox6

log = logging.getLogger(__name__)


class GeometryMixin:
    """Geometry (faces/edges/bounding boxes/transforms)."""

    def _init_state(self) -> None:
        pass  # stateless

    @staticmethod
    def _component_is_lightweight(comp: Any) -> bool:
        try:
            return int(_get(comp, "GetSuppression2")) == _SW_COMP_LIGHTWEIGHT
        except Exception:
            try:
                return int(_get(comp, "GetSuppression")) == _SW_COMP_LIGHTWEIGHT
            except Exception:
                return False

    @staticmethod
    def _comp_point(comp: Any, pt: tuple[float, float, float]) -> tuple[float, float, float]:
        """Part coords → assembly coords (IMathTransform.ArrayData: row-major 3×3 + translation)."""
        try:
            xf = _get(comp, "Transform2")
            a = list(_get(xf, "ArrayData"))
            x, y, z = pt
            return (
                a[0] * x + a[1] * y + a[2] * z + a[9],
                a[3] * x + a[4] * y + a[5] * z + a[10],
                a[6] * x + a[7] * y + a[8] * z + a[11],
            )
        except Exception:
            log.debug("Component transform failed; using part coords: %s", traceback.format_exc())
            return pt

    @staticmethod
    def _comp_dir(comp: Any, vec: tuple[float, float, float]) -> tuple[float, float, float]:
        try:
            xf = _get(comp, "Transform2")
            a = list(_get(xf, "ArrayData"))
            x, y, z = vec
            return (
                a[0] * x + a[1] * y + a[2] * z,
                a[3] * x + a[4] * y + a[5] * z,
                a[6] * x + a[7] * y + a[8] * z,
            )
        except Exception:
            return vec

    @staticmethod
    def _unit_dir(vec: tuple[float, float, float]) -> tuple[float, float, float] | None:
        x, y, z = vec
        n = math.sqrt(x * x + y * y + z * z)
        if n < 1e-9:
            return None
        return (x / n, y / n, z / n)

    @staticmethod
    def _face_normal(face: Any) -> tuple[float, float, float] | None:
        try:
            raw = _get(face, "Normal")
            if raw is not None and len(raw) >= 3:
                unit = GeometryMixin._unit_dir((float(raw[0]), float(raw[1]), float(raw[2])))
                if unit is not None:
                    return unit
        except Exception:
            log.debug("Face.Normal failed: %s", traceback.format_exc())
        try:
            surf = _get(face, "GetSurface")
            if int(_get(surf, "Identity")) != 4001:
                return None
            p = _get(surf, "PlaneParams")
            return GeometryMixin._unit_dir((float(p[0]), float(p[1]), float(p[2])))
        except Exception:
            log.debug("PlaneParams failed: %s", traceback.format_exc())
            return None

    @staticmethod
    def _same_point(p: tuple[float, ...], q: tuple[float, ...]) -> bool:
        return all(abs(a - b) < 1e-9 for a, b in zip(p, q, strict=True))

    def _component_face_objects(self, comp: Any) -> list[Any]:
        try:
            body = _get(comp, "GetBody")
        except Exception:
            log.debug("GetBody failed: %s", traceback.format_exc())
            body = None
        if body is None:
            try:
                bodies = list(_get(comp, "GetBodies3", 0, False) or ())
            except Exception:
                log.debug("GetBodies3 failed: %s", traceback.format_exc())
                bodies = []
        else:
            bodies = [body]
        faces: list[Any] = []
        for body in bodies:
            faces.extend(_get(body, "GetFaces") or ())
        return faces

    def _component_edge_objects(self, comp: Any) -> list[Any]:
        try:
            body = _get(comp, "GetBody")
        except Exception:
            log.debug("GetBody failed: %s", traceback.format_exc())
            body = None
        if body is None:
            try:
                bodies = list(_get(comp, "GetBodies3", 0, False) or ())
            except Exception:
                log.debug("GetBodies3 failed: %s", traceback.format_exc())
                bodies = []
        else:
            bodies = [body]
        edges: list[Any] = []
        for body in bodies:
            edges.extend(_get(body, "GetEdges") or ())
        return edges

    def _part_edge_objects(self, doc: Any) -> list[Any]:
        out: list[Any] = []
        for body in self._bodies_of(doc):
            out.extend(_get(body, "GetEdges") or ())
        return out

    def _part_face_objects(self, doc: Any) -> list[Any]:
        out: list[Any] = []
        for body in self._bodies_of(doc):
            out.extend(_get(body, "GetFaces") or ())
        return out

    def _part_vertex_objects(self, doc: Any) -> list[Any]:
        out: list[Any] = []
        for body in self._bodies_of(doc):
            out.extend(_get(body, "GetVertices") or ())
        return out

    def _component_is_fixed(self, comp: Any) -> bool:
        for name in ("IsFixed", "GetFixed"):
            try:
                val = getattr(comp, name)
                if callable(val) and not hasattr(val, "_oleobj_"):
                    val = val()
                return bool(val)
            except Exception:
                continue
        return False

    def _write_comp_transform(self, comp: Any, array16: list[float]) -> bool:
        import pythoncom
        from win32com.client import VARIANT

        data = [float(v) for v in array16]
        arr = VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, data)
        xf = _get(comp, "Transform2")
        try:
            xf.ArrayData = arr
            try:
                ok = _get(comp, "SetTransformAndSolve2", xf)
                if ok is None or bool(ok):
                    return True
            except Exception:
                log.debug("SetTransformAndSolve2 failed: %s", traceback.format_exc())
            comp.Transform2 = xf
            return True
        except Exception:
            log.debug("Writing Transform2.ArrayData failed: %s", traceback.format_exc())
        try:
            mu = _get(self.sw, "GetMathUtility")
            xf2 = _get(mu, "CreateTransform", arr)
            if xf2 is None:
                return False
            try:
                ok = _get(comp, "SetTransformAndSolve2", xf2)
                if ok is None or bool(ok):
                    return True
            except Exception:
                log.debug("CreateTransform+SetTransform failed: %s", traceback.format_exc())
            comp.Transform2 = xf2
            return True
        except Exception:
            log.debug("CreateTransform failed: %s", traceback.format_exc())
            return False

    def _snap_component_origin(
        self, asm: Any, comp: Any, x_m: float, y_m: float, z_m: float,
    ) -> tuple[float, float, float]:
        """Place part origin at assembly (x,y,z). Translate relative to current transform."""
        origin = self._comp_point(comp, (0.0, 0.0, 0.0))
        dx, dy, dz = x_m - origin[0], y_m - origin[1], z_m - origin[2]
        if math.hypot(dx, dy, dz) < 1e-9:
            return origin
        try:
            selected = self._select_component(asm, comp)
            if selected and self._component_is_fixed(comp):
                try:
                    _get(asm, "UnFixComponent")
                except Exception:
                    log.debug("UnFixComponent failed: %s", traceback.format_exc())
            xf = _get(comp, "Transform2")
            a = list(_get(xf, "ArrayData"))
            a[9] += dx
            a[10] += dy
            a[11] += dz
            if self._write_comp_transform(comp, a):
                try:
                    _get(asm, "EditRebuild3")
                except Exception:
                    log.debug("Post-insert rebuild failed: %s", traceback.format_exc())
            origin = self._comp_point(comp, (0.0, 0.0, 0.0))
        except Exception:
            log.debug("Align part origin failed: %s", traceback.format_exc())
        return origin

    def _face_geometry(
        self, face: Any, comp: Any | None = None,
    ) -> tuple[str, tuple[float, float, float], tuple[float, float, float] | None, tuple[float, float, float] | None]:
        """(kind, centroid approx, normal, cylinder axis): centroid = face bbox center; comp maps to assembly."""
        centroid = (0.0, 0.0, 0.0)
        kind = "unknown"
        normal: tuple[float, float, float] | None = None
        axis: tuple[float, float, float] | None = None
        try:
            b = _get(face, "GetBox")  # xmin,ymin,zmin,xmax,ymax,zmax (meters)
            centroid = (
                (float(b[0]) + float(b[3])) / 2,
                (float(b[1]) + float(b[4])) / 2,
                (float(b[2]) + float(b[5])) / 2,
            )
        except Exception:
            log.debug("Read face bbox failed: %s", traceback.format_exc())
        try:
            code = int(_get(_get(face, "GetSurface"), "Identity"))
            kind = _SURFACE_KINDS.get(code, f"surface_{code}")
        except Exception:
            log.debug("Read face type failed: %s", traceback.format_exc())
        normal = self._face_normal(face)
        if kind == "cylinder":
            try:
                p = list(_get(_get(face, "GetSurface"), "CylinderParams") or ())
                if len(p) >= 6:
                    axis = self._unit_dir((float(p[3]), float(p[4]), float(p[5])))
            except Exception:
                log.debug("CylinderParams failed: %s", traceback.format_exc())
        if comp is not None:
            centroid = self._comp_point(comp, centroid)
            if normal is not None:
                normal = self._comp_dir(comp, normal)
            if axis is not None:
                axis = self._unit_dir(self._comp_dir(comp, axis))
        return kind, centroid, normal, axis

    def _edge_geometry(
        self, edge: Any, comp: Any | None = None,
    ) -> tuple[str, tuple[float, float, float]]:
        """(kind, midpoint): line = avg of endpoints; curves = evaluate at mid parameter; comp maps to assembly."""
        midpoint = (0.0, 0.0, 0.0)
        kind = "unknown"
        try:
            code = int(_get(_get(edge, "GetCurve"), "Identity"))
            kind = _CURVE_KINDS.get(code, f"curve_{code}")
        except Exception:
            log.debug("Read edge type failed: %s", traceback.format_exc())
        try:
            # [0:3] start [3:6] end [6] start param [7] end param; rest uninitialized, unused
            p = _get(edge, "GetCurveParams2")
            midpoint = tuple((float(s) + float(e)) / 2 for s, e in zip(p[0:3], p[3:6], strict=True))
            if kind != "line":
                try:
                    pt = _get(edge, "Evaluate2", (float(p[6]) + float(p[7])) / 2, 0)
                    midpoint = (float(pt[0]), float(pt[1]), float(pt[2]))
                except Exception:
                    log.debug("Edge evaluate failed; using endpoint average: %s", traceback.format_exc())
        except Exception:
            log.debug("Read edge curve params failed: %s", traceback.format_exc())
        if comp is not None:
            midpoint = self._comp_point(comp, midpoint)
        return kind, midpoint

    def _bodies_of_feature(self, feat: Any) -> list[Any]:
        bodies: list[Any] = []
        for face in _get(feat, "GetFaces") or ():
            body = _get(face, "GetBody")
            if body is not None and all(body is not x for x in bodies):
                bodies.append(body)
        return bodies

    def _bodies_of(self, doc: Any) -> list[Any]:
        if doc is None:
            return []
        try:
            bodies = doc.GetBodies2(0, False)
        except TypeError:
            try:
                bodies = doc.GetBodies2(0)
            except Exception:
                log.debug("GetBodies2(0) failed: %s", traceback.format_exc())
                return []
        except Exception:
            log.debug("GetBodies2 failed: %s", traceback.format_exc())
            return []
        return list(bodies) if bodies else []

    def _has_solid(self, doc: Any) -> bool:
        if self._bodies_of(doc):
            return True
        try:
            if int(_get(doc, "GetType")) == SW_DOC_ASSEMBLY:
                return bool(self._assembly_component_objs(doc))
        except Exception:
            log.debug("Assembly solid probe failed: %s", traceback.format_exc())
        return False

    def _body_bbox_m(self, body: Any) -> tuple[float, float, float, float, float, float] | None:
        """Body bounding box (meters). Prefer GetBox (same as faces); GetBodyBox is fallback."""
        for name in ("GetBox", "GetBodyBox"):
            try:
                parsed = _as_bbox6(_get(body, name))
            except Exception:
                log.debug("Body.%s failed: %s", name, traceback.format_exc())
                parsed = None
            if parsed is not None:
                return parsed
        return None

    def _component_bbox_m(self, comp: Any) -> tuple[float, float, float, float, float, float] | None:
        """Component bbox in assembly coords. Prefer IComponent2.GetBox else transform part box."""
        for args in ((False,), (True,), ()):
            try:
                parsed = _as_bbox6(comp.GetBox(*args))
            except TypeError:
                continue
            except Exception:
                log.debug("Component.GetBox%s failed: %s", args, traceback.format_exc())
                parsed = None
            if parsed is not None:
                return parsed
        try:
            part = _get(comp, "GetModelDoc2")
        except Exception:
            part = None
        if part is None:
            return None
        boxes: list[tuple[float, float, float, float, float, float]] = []
        for body in self._bodies_of(part):
            b = self._body_bbox_m(body)
            if b is None:
                continue
            corners = (
                (b[0], b[1], b[2]), (b[3], b[1], b[2]),
                (b[0], b[4], b[2]), (b[3], b[4], b[2]),
                (b[0], b[1], b[5]), (b[3], b[1], b[5]),
                (b[0], b[4], b[5]), (b[3], b[4], b[5]),
            )
            pts = [self._comp_point(comp, c) for c in corners]
            xs, ys, zs = zip(*pts, strict=True)
            boxes.append((min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)))
        return _union_bbox6(boxes) if boxes else None

    def _assembly_bbox_m(self, doc: Any) -> tuple[float, float, float, float, float, float]:
        boxes = [
            b for _, comp in self._assembly_component_objs(doc)
            if (b := self._component_bbox_m(comp)) is not None
        ]
        return _union_bbox6(boxes) if boxes else (0.0,) * 6

    def _part_bbox_m(self, doc: Any) -> tuple[float, float, float, float, float, float]:
        """Part/assembly bounding box (meters).

        With solids, union per-body GetBox. GetPartBox can lag after helix sweeps
        (volume/face count changed, bbox stale → sweep_helix fingerprint jitter).
        Without solids, fall back to GetPartBox so helix+sketch still count (fake parity).
        Assembly GetBodies2 is often empty; use component GetBox / transformed part boxes.
        """
        try:
            if int(_get(doc, "GetType")) == SW_DOC_ASSEMBLY:
                return self._assembly_bbox_m(doc)
        except Exception:
            log.debug("Assembly type probe failed: %s", traceback.format_exc())
        boxes = [b for body in self._bodies_of(doc) if (b := self._body_bbox_m(body)) is not None]
        if boxes:
            return _union_bbox6(boxes)
        try:
            parsed = _as_bbox6(doc.GetPartBox(True))
        except Exception:
            log.debug("GetPartBox failed: %s", traceback.format_exc())
            parsed = None
        return parsed if parsed is not None else (0.0,) * 6

    def _entity_counts(self, doc: Any) -> tuple[int, int]:
        """(face_count, edge_count): use body count APIs, not per-entity geometry (slow)."""
        faces = edges = 0
        bodies = self._bodies_of(doc)
        if not bodies:
            try:
                if int(_get(doc, "GetType")) == SW_DOC_ASSEMBLY:
                    for _, comp in self._assembly_component_objs(doc):
                        try:
                            body = _get(comp, "GetBody")
                            if body is not None:
                                bodies.append(body)
                                continue
                        except Exception:
                            pass
                        try:
                            part = _get(comp, "GetModelDoc2")
                        except Exception:
                            part = None
                        if part is not None:
                            bodies.extend(self._bodies_of(part))
            except Exception:
                log.debug("Assembly face/edge count failed: %s", traceback.format_exc())
        for body in bodies:
            try:
                faces += int(_get(body, "GetFaceCount"))
                edges += int(_get(body, "GetEdgeCount"))
            except Exception:
                log.debug("GetFaceCount/GetEdgeCount failed; enumerating: %s", traceback.format_exc())
                faces += len(_get(body, "GetFaces") or ())
                edges += len(_get(body, "GetEdges") or ())
        return faces, edges
