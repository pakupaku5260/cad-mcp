"""COM backend · read-only queries (features / faces / edges / mass / fingerprint / interference).

S6-1a-1: list_features / list_faces / list_edges / get_faces / get_edges
S6-1a-2: + select_face / select_edge / selected_entities
S6-1a-3: + list_component_faces / list_component_edges
S6-1b: + check_interference / _sw_interference_pairs
S6-1c: + mass_properties / fingerprint

Dependencies (self, MRO):
- ``_call`` / ``_map_error`` (STAThreadMixin)
- ``_bodies_of`` / ``_face_geometry`` / ``_edge_geometry`` (GeometryMixin)
- ``_features_of`` (NamingMixin)
- ``_get`` (_helpers)

imports:
- ``cadmcp.backend.protocol.models`` (FaceRef / EdgeRef / FeatureInfo)
- ``cadmcp.backend.selectors`` (query_faces)
- ``cadmcp.errors`` (CadMcpError / fail)
- ``._constants`` (_SKIP_FEATURE_TYPES)
- ``._helpers`` (_get / feature_kind_from_sw)
"""
from __future__ import annotations

import logging
import traceback
from typing import Any

from cadmcp.backend.protocol.geometry_engine import aabb_pair_status
from cadmcp.backend.protocol.models import (
    EdgeRef,
    FaceRef,
    FeatureInfo,
    FingerprintSI,
    InterferencePair,
    MassPropsSI,
    VertexRef,
)
from cadmcp.backend.protocol.parsers import interference_component_pairs
from cadmcp.errors import CadMcpError, fail
from cadmcp.selectors import (
    EDGE_FILTER_KINDS,
    FACE_FILTER_KINDS,
    filter_by_kind,
    query_faces,
)

from ._constants import (
    _SEL_EDGE,
    _SEL_FACE,
    _SKIP_FEATURE_TYPES,
    SW_DOC_ASSEMBLY,
)
from ._helpers import _get, feature_kind_from_sw

log = logging.getLogger(__name__)


class QueryMixin:
    """Read-only queries (S6-1a-1: 5 methods)."""

    def _init_state(self) -> None:
        pass  # stateless

    def list_features(self) -> list[FeatureInfo]:
        def _fn() -> list[FeatureInfo]:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            feats: list[FeatureInfo] = []
            try:
                for feat in self._features_of(doc):
                    try:
                        tname = str(_get(feat, "GetTypeName2"))
                    except Exception:
                        tname = ""
                    if tname in _SKIP_FEATURE_TYPES or tname.endswith("Folder"):
                        continue
                    try:
                        name = str(_get(feat, "Name"))
                    except Exception:
                        name = "Unknown"
                    feats.append(FeatureInfo(name=name, kind=feature_kind_from_sw(tname)))
            except CadMcpError:
                raise
            except Exception as exc:
                raise self._map_error(exc) from exc
            return feats

        return self._call(_fn)

    def list_faces(self) -> list[FaceRef]:
        def _fn() -> list[FaceRef]:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            faces: list[FaceRef] = []
            try:
                for body in self._bodies_of(doc):
                    for face in _get(body, "GetFaces") or ():
                        kind, centroid, normal, axis = self._face_geometry(face)
                        faces.append(
                            FaceRef(
                                index=len(faces),
                                kind=kind,
                                centroid_m=centroid,
                                normal_m=normal,
                                axis_m=axis,
                            )
                        )
            except CadMcpError:
                raise
            except Exception as exc:
                raise self._map_error(exc) from exc
            return faces

        return self._call(_fn)

    def list_edges(self) -> list[EdgeRef]:
        def _fn() -> list[EdgeRef]:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            edges: list[EdgeRef] = []
            try:
                for body in self._bodies_of(doc):
                    for edge in _get(body, "GetEdges") or ():
                        kind, midpoint = self._edge_geometry(edge)
                        edges.append(EdgeRef(index=len(edges), kind=kind, midpoint_m=midpoint))
            except CadMcpError:
                raise
            except Exception as exc:
                raise self._map_error(exc) from exc
            return edges

        return self._call(_fn)

    def list_vertices(self) -> list[VertexRef]:
        def _fn() -> list[VertexRef]:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            verts: list[VertexRef] = []
            try:
                for body in self._bodies_of(doc):
                    for vert in _get(body, "GetVertices") or ():
                        try:
                            p = list(_get(vert, "GetPoint") or ())
                            if len(p) < 3:
                                continue
                            pos = (float(p[0]), float(p[1]), float(p[2]))
                        except Exception:
                            continue
                        verts.append(VertexRef(index=len(verts), position_m=pos))
            except CadMcpError:
                raise
            except Exception as exc:
                raise self._map_error(exc) from exc
            return verts

        return self._call(_fn)

    def get_faces(self, kind: str | None = None, query: str | None = None) -> list[FaceRef]:
        return query_faces(self.list_faces(), kind, query)

    def get_edges(self) -> list[EdgeRef]:
        return self.list_edges()

    def get_vertices(self) -> list[VertexRef]:
        return self.list_vertices()

    def select_face(self, index: int) -> None:
        def _fn() -> None:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            faces = [f for body in self._bodies_of(doc) for f in (_get(body, "GetFaces") or ())]
            if not faces:
                raise fail("REF_NOT_FOUND", "No selectable faces in the document", "Create a solid first (e.g. extrude)")
            if index < 0 or index >= len(faces):
                raise fail("INVALID_ARGUMENT", f"Face index out of range: {index}", f"Valid range 0..{len(faces) - 1}")
            self._clear_selection(doc)
            if not self._select_entity(doc, faces[index]):
                raise fail(
                    "SELECT_FAILED",
                    f"Cannot select face {index}",
                    "Confirm part edit mode and that SolidWorks has no modal dialog open",
                )

        return self._call(_fn)

    def select_edge(self, index: int) -> None:
        def _fn() -> None:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            edges = [e for body in self._bodies_of(doc) for e in (_get(body, "GetEdges") or ())]
            if not edges:
                raise fail("REF_NOT_FOUND", "No selectable edges in the document", "Create a solid first (e.g. extrude)")
            if index < 0 or index >= len(edges):
                raise fail("INVALID_ARGUMENT", f"Edge index out of range: {index}", f"Valid range 0..{len(edges) - 1}")
            self._clear_selection(doc)
            if not self._select_entity(doc, edges[index]):
                raise fail(
                    "SELECT_FAILED",
                    f"Cannot select edge {index}",
                    "Confirm part edit mode and that SolidWorks has no modal dialog open",
                )

        return self._call(_fn)

    def selected_entities(self) -> list[FaceRef | EdgeRef]:
        def _fn() -> list[FaceRef | EdgeRef]:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            items: list[FaceRef | EdgeRef] = []
            try:
                sel = _get(doc, "SelectionManager")
                if sel is None:
                    return []
                count = int(_get(sel, "GetSelectedObjectCount2", -1) or 0)
                if count <= 0:
                    return []
                faces_pool: list[FaceRef] | None = None  # build on demand when face/edge selected
                edges_pool: list[EdgeRef] | None = None
                for i in range(1, count + 1):
                    try:
                        sel_type = int(_get(sel, "GetSelectedObjectType3", i, -1))
                        obj = _get(sel, "GetSelectedObject6", i, -1)
                    except Exception:
                        log.debug("Read selection object %d failed: %s", i, traceback.format_exc())
                        continue
                    if obj is None:
                        continue
                    if sel_type == _SEL_FACE:
                        if faces_pool is None:
                            faces_pool = self.list_faces()
                        kind, c, nrm, _axis = self._face_geometry(obj)
                        idx = next(
                            (f.index for f in faces_pool
                             if f.kind == kind and self._same_point(f.centroid_m, c)),
                            -1,
                        )
                        items.append(FaceRef(index=idx, kind=kind, centroid_m=c, normal_m=nrm))
                    elif sel_type == _SEL_EDGE:
                        if edges_pool is None:
                            edges_pool = self.list_edges()
                        kind, m = self._edge_geometry(obj)
                        idx = next(
                            (e.index for e in edges_pool
                             if e.kind == kind and self._same_point(e.midpoint_m, m)),
                            -1,
                        )
                        items.append(EdgeRef(index=idx, kind=kind, midpoint_m=m))
            except CadMcpError:
                raise
            except Exception as exc:
                raise self._map_error(exc) from exc
            return items

        return self._call(_fn)

    def list_component_faces(self, component: str, kind: str | None = None) -> list[FaceRef]:
        def _fn() -> list[FaceRef]:
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
                    "Create an assembly with new_assembly before querying component faces",
                )
            comp = self._component_by_name(doc, component)
            if comp is None:
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Component not found: {component!r}",
                    "Instance name from insert_component return value, e.g. p1-1",
                    component=component,
                )
            out: list[FaceRef] = []
            for face in self._component_face_objects(comp):
                face_kind, centroid, normal, axis = self._face_geometry(face, comp)
                out.append(
                    FaceRef(
                        index=len(out),
                        kind=face_kind,
                        centroid_m=centroid,
                        normal_m=normal,
                        axis_m=axis,
                    )
                )
            return filter_by_kind(out, kind, allowed=FACE_FILTER_KINDS, what="face")

        return self._call(_fn)

    def list_component_edges(self, component: str, kind: str | None = None) -> list[EdgeRef]:
        def _fn() -> list[EdgeRef]:
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
                    "Create an assembly with new_assembly before querying component edges",
                )
            comp = self._component_by_name(doc, component)
            if comp is None:
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Component not found: {component!r}",
                    "Instance name from insert_component return value, e.g. p1-1",
                    component=component,
                )
            out: list[EdgeRef] = []
            for edge in self._component_edge_objects(comp):
                edge_kind, midpoint = self._edge_geometry(edge, comp)
                out.append(EdgeRef(index=len(out), kind=edge_kind, midpoint_m=midpoint))
            return filter_by_kind(out, kind, allowed=EDGE_FILTER_KINDS, what="edge")

        return self._call(_fn)

    def check_interference(
        self,
        component1: str | None = None,
        component2: str | None = None,
        coincident_as_interference: bool = False,
    ) -> tuple[list[InterferencePair], str]:
        def _fn() -> tuple[list[InterferencePair], str]:
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
                    "Create an assembly with new_assembly before checking interference",
                )
            named = self._assembly_component_names(doc)
            wanted = interference_component_pairs(named, component1, component2)
            sw_pairs = self._sw_interference_pairs(doc, wanted, coincident_as_interference)
            if sw_pairs is not None:
                return sw_pairs, "solidworks"
            boxes: dict[str, tuple[float, float, float, float, float, float] | None] = {}
            for name, comp in self._assembly_component_objs(doc):
                boxes[name] = self._component_bbox_m(comp)
            out: list[InterferencePair] = []
            for a, b in wanted:
                ba, bb = boxes.get(a), boxes.get(b)
                if ba is None or bb is None:
                    out.append(InterferencePair(a=a, b=b, status="unknown"))
                    continue
                status = aabb_pair_status(ba, bb, coincident_as_interference=coincident_as_interference)
                if status == "clear":
                    continue
                out.append(InterferencePair(a=a, b=b, status=status))
            return out, "aabb"

        return self._call(_fn, timeout=180.0)

    def _sw_interference_pairs(
        self,
        doc: Any,
        wanted: list[tuple[str, str]],
        coincident_as_interference: bool,
    ) -> list[InterferencePair] | None:
        wanted_set = set(wanted)
        mgr = None
        try:
            mgr = _get(doc, "InterferenceDetectionManager")
            if mgr is None:
                return None
            try:
                mgr.TreatCoincidenceAsInterference = bool(coincident_as_interference)
            except Exception:
                log.debug("Set TreatCoincidenceAsInterference failed: %s", traceback.format_exc())
            try:
                mgr.MakeInterferingPartsTransparent = False
            except Exception:
                log.debug("Set MakeInterferingPartsTransparent failed: %s", traceback.format_exc())
            count = int(_get(mgr, "GetInterferenceCount") or 0)
            raw = _get(mgr, "GetInterferences") if count else None
            if raw is None:
                items: list[Any] = []
            elif isinstance(raw, (list, tuple)):
                items = list(raw)
            else:
                try:
                    items = list(raw)
                except TypeError:
                    items = [raw]
            found: dict[tuple[str, str], InterferencePair] = {}
            for inf in items:
                names: list[str] = []
                try:
                    comps = _get(inf, "Components")
                except Exception:
                    comps = None
                for comp in comps or ():
                    try:
                        names.append(str(_get(comp, "Name2") or ""))
                    except Exception:
                        log.debug("Interference component name failed: %s", traceback.format_exc())
                names = [n for n in names if n]
                if len(names) < 2:
                    continue
                key = tuple(sorted((names[0], names[1])))
                if key not in wanted_set:
                    continue
                vol = None
                try:
                    vol = float(_get(inf, "Volume") or 0.0)
                except Exception:
                    vol = None
                possible = False
                try:
                    possible = bool(_get(inf, "IsPossibleInterference"))
                except Exception:
                    possible = False
                if possible:
                    status = "unknown"
                elif vol is not None and vol > 1e-12:
                    status = "interfere"
                else:
                    status = "interfere" if coincident_as_interference else "contact"
                found[key] = InterferencePair(a=key[0], b=key[1], status=status, volume_m3=vol)
            return [found[k] for k in wanted if k in found]
        except Exception:
            log.debug("InterferenceDetectionManager failed: %s", traceback.format_exc())
            return None
        finally:
            if mgr is not None:
                try:
                    _get(mgr, "Done")
                except Exception:
                    log.debug("InterferenceDetectionManager.Done failed: %s", traceback.format_exc())

    def mass_properties(self) -> MassPropsSI:
        def _fn() -> MassPropsSI:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            try:
                _get(doc, "ForceRebuild3", True)
            except Exception:
                pass

            if not self._has_solid(doc):
                return MassPropsSI(volume_m3=0.0, surface_area_m2=0.0, mass_kg=0.0,
                                center_of_mass_m=(0.0, 0.0, 0.0))

            try:
                mp = _get(doc.Extension, "CreateMassProperty")
            except Exception as exc:
                raise self._map_error(exc) from exc
            if mp is None:  # empty part (no solid yet) has no mass properties
                return MassPropsSI(
                    volume_m3=0.0,
                    surface_area_m2=0.0,
                    mass_kg=0.0,
                    center_of_mass_m=(0.0, 0.0, 0.0),
                )
            try:
                com = _get(mp, "CenterOfMass")
                return MassPropsSI(
                    volume_m3=float(_get(mp, "Volume")),
                    surface_area_m2=float(_get(mp, "SurfaceArea")),
                    mass_kg=float(_get(mp, "Mass")),
                    center_of_mass_m=(float(com[0]), float(com[1]), float(com[2])),
                )
            except Exception as exc:
                raise self._map_error(exc) from exc

        return self._call(_fn)

    def fingerprint(self) -> FingerprintSI:
        def _fn() -> FingerprintSI:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            # mp = self.mass_properties()      # re-entrant safe
            # faces = self.list_faces()
            # edges = self.list_edges()
            mp = self.mass_properties()      # re-entrant safe
            face_count, edge_count = self._entity_counts(doc)
            bbox = self._part_bbox_m(doc)
            return FingerprintSI(
                volume_m3=mp.volume_m3,
                surface_area_m2=mp.surface_area_m2,
                mass_kg=mp.mass_kg,
                # face_count=len(faces),
                # edge_count=len(edges),
                face_count=face_count,
                edge_count=edge_count,
                bbox_m=bbox,
            )
        return self._call(_fn)
