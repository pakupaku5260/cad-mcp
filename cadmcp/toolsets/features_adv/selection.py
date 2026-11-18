"""Selection toolset: face/edge pick and query; includes GUI selection readback."""

from __future__ import annotations

from cadmcp.backend.protocol.models import EdgeRef, FaceRef
from cadmcp.errors import fail
from cadmcp.kernel import OpContext
from cadmcp.registry import ToolSpec, make_schema
from cadmcp.selectors import (
    FACE_FILTER_KINDS,
    FACE_QUERIES,
    Ref,
    resolve,
    resolve_ref_id,
)
from cadmcp.toolsets.paging import paginate

from ._common import _UNIT_DESC, _UNIT_ENUM, _unit_ctx


def _select_xyz(
    x: float | None, y: float | None, z: float | None
) -> tuple[float, float, float] | None:
    given = (x is not None, y is not None, z is not None)
    if not any(given):
        return None
    if not all(given):
        raise fail("INVALID_ARGUMENT", "x/y/z must all be given or all omitted", "Pass full coords from get_entities")
    return float(x), float(y), float(z)


def _anchor_m(
    entities: list[FaceRef] | list[EdgeRef],
    index: int,
    xyz_m: tuple[float, float, float] | None,
) -> tuple[float, float, float] | None:
    if xyz_m is not None:
        return xyz_m
    if 0 <= index < len(entities):
        ent = entities[index]
        return ent.centroid_m if isinstance(ent, FaceRef) else ent.midpoint_m
    return None


def _backend_persist_index(backend: object, ref_id: str, kind: str) -> int | None:
    """Fake typed reverse lookup, then SW STA-wrapped ``_index_by_persist_ref``."""
    typed = "_face_by_persist_ref" if kind == "face" else "_edge_by_persist_ref"
    fn = getattr(backend, typed, None)
    if callable(fn):
        hit = fn(ref_id)
        if hit is not None:
            return int(hit.index)
    fn = getattr(backend, "_index_by_persist_ref", None)
    if callable(fn):
        return fn(ref_id, kind=kind)
    return None


def _select_by_ref_id(
    ctx: OpContext,
    *,
    kind: str,
    ref_id: str,
    index: int,
    xyz_m: tuple[float, float, float] | None,
) -> int:
    """ref_id exact (string) → backend reverse lookup → REF_STALE / REF_UNSUPPORTED."""
    entities = ctx.backend.list_faces() if kind == "face" else ctx.backend.list_edges()
    for ent in entities:
        if ent.ref_id == ref_id:
            return ent.index
    backend_idx = _backend_persist_index(ctx.backend, ref_id, kind)
    if backend_idx is not None:
        return backend_idx
    # Raises REF_UNSUPPORTED / REF_STALE / REF_NOT_FOUND (never returns).
    resolve_ref_id(ref_id, entities, anchor_m=_anchor_m(entities, index, xyz_m))
    raise AssertionError("resolve_ref_id must raise on miss")


def select_face(
    ctx: OpContext,
    index: int,
    x: float | None = None,
    y: float | None = None,
    z: float | None = None,
    unit: str = "mm",
    ref_id: str | None = None,
) -> dict:
    xyz = _select_xyz(x, y, z)
    uc = _unit_ctx(ctx, unit) if (ref_id is not None or xyz is not None) else None
    xyz_m = None if xyz is None or uc is None else (uc.to_m(xyz[0]), uc.to_m(xyz[1]), uc.to_m(xyz[2]))

    # Order: ref_id exact → index + coords (resolve) → bare index. ref_id wins when both given.
    if ref_id is not None:
        selected = _select_by_ref_id(ctx, kind="face", ref_id=ref_id, index=index, xyz_m=xyz_m)
        ctx.backend.select_face(selected)
        out: dict = {"selected_face": selected, "quality": "persist"}
        if uc is not None:
            out["unit"] = uc.external_unit
        return out

    if xyz is None:
        ctx.backend.select_face(index)
        return {"selected_face": index, "quality": "index"}
    assert uc is not None and xyz_m is not None
    hit = resolve(Ref(index, xyz_m[0], xyz_m[1], xyz_m[2]), ctx.backend.list_faces())
    ctx.backend.select_face(hit.entity.index)
    return {
        "selected_face": hit.entity.index,
        "quality": hit.quality,
        "unit": uc.external_unit,
    }


def select_edge(
    ctx: OpContext,
    index: int,
    x: float | None = None,
    y: float | None = None,
    z: float | None = None,
    unit: str = "mm",
    ref_id: str | None = None,
) -> dict:
    xyz = _select_xyz(x, y, z)
    uc = _unit_ctx(ctx, unit) if (ref_id is not None or xyz is not None) else None
    xyz_m = None if xyz is None or uc is None else (uc.to_m(xyz[0]), uc.to_m(xyz[1]), uc.to_m(xyz[2]))

    if ref_id is not None:
        selected = _select_by_ref_id(ctx, kind="edge", ref_id=ref_id, index=index, xyz_m=xyz_m)
        ctx.backend.select_edge(selected)
        out: dict = {"selected_edge": selected, "quality": "persist"}
        if uc is not None:
            out["unit"] = uc.external_unit
        return out

    if xyz is None:
        ctx.backend.select_edge(index)
        return {"selected_edge": index, "quality": "index"}
    assert uc is not None and xyz_m is not None
    hit = resolve(Ref(index, xyz_m[0], xyz_m[1], xyz_m[2]), ctx.backend.list_edges())
    ctx.backend.select_edge(hit.entity.index)
    return {
        "selected_edge": hit.entity.index,
        "quality": hit.quality,
        "unit": uc.external_unit,
    }


def get_faces(
    ctx: OpContext,
    kind: str | None = None,
    query: str | None = None,
    unit: str = "mm",
    limit: int | None = None,
    offset: int | None = None,
) -> dict:
    uc = _unit_ctx(ctx, unit)
    all_faces = []
    for f in ctx.backend.get_faces(kind=kind, query=query):
        row = {
            "index": f.index,
            "kind": f.kind,
            "centroid": list(uc.tuple_from_m(f.centroid_m)),
            "ref_id": f.ref_id,
        }
        if f.normal_m is not None:
            row["normal"] = [float(v) for v in f.normal_m]
        if f.axis_m is not None:
            row["axis"] = [float(v) for v in f.axis_m]
        all_faces.append(row)
    faces, start = paginate(all_faces, limit, offset)
    out: dict = {"faces": faces, "length_unit": uc.external_unit}
    if kind:
        out["kind"] = kind
    if query:
        out["query"] = query
    if start is not None:
        out["total"] = len(all_faces)
        out["offset"] = start
    return out


def get_edges(
    ctx: OpContext, limit: int | None = None, offset: int | None = None
) -> dict:
    u = ctx.units
    all_edges = [
        {
            "index": e.index,
            "kind": e.kind,
            "midpoint": list(u.tuple_from_m(e.midpoint_m)),
            "ref_id": e.ref_id,
        }
        for e in ctx.backend.get_edges()
    ]
    edges, start = paginate(all_edges, limit, offset)
    out: dict = {"edges": edges, "length_unit": u.external_unit}
    if start is not None:
        out["total"] = len(all_edges)
        out["offset"] = start
    return out


def get_vertices(
    ctx: OpContext,
    unit: str = "mm",
    limit: int | None = None,
    offset: int | None = None,
) -> dict:
    uc = _unit_ctx(ctx, unit)
    all_verts = [
        {
            "index": v.index,
            "position": list(uc.tuple_from_m(v.position_m)),
            "ref_id": v.ref_id,
        }
        for v in ctx.backend.get_vertices()
    ]
    vertices, start = paginate(all_verts, limit, offset)
    out: dict = {"vertices": vertices, "length_unit": uc.external_unit}
    if start is not None:
        out["total"] = len(all_verts)
        out["offset"] = start
    return out


def get_selection(ctx: OpContext) -> dict:
    """GUI picks → service refs (§9 fallback): re-resolve and return match quality."""
    u = ctx.units
    faces = ctx.backend.list_faces()
    edges = ctx.backend.list_edges()
    items = []
    for ent in ctx.backend.selected_entities():
        is_face = isinstance(ent, FaceRef)
        pool = faces if is_face else edges
        coords = ent.centroid_m if is_face else ent.midpoint_m
        hit = resolve(Ref(ent.index, *coords), pool)  # Re-resolve each call; no guessing
        hit_coords = hit.entity.centroid_m if is_face else hit.entity.midpoint_m
        item = {
            "type": "face" if is_face else "edge",
            "index": hit.entity.index,  # Current handle in pool (stale index updated)
            "kind": hit.entity.kind,
            "coords": list(u.tuple_from_m(hit_coords)),
            "quality": hit.quality,
            "ref_id": hit.entity.ref_id,
        }
        if is_face and hit.entity.normal_m is not None:
            item["normal"] = [float(v) for v in hit.entity.normal_m]
        items.append(item)
    return {"entities": items, "length_unit": u.external_unit}


SPECS: list[ToolSpec] = [
    ToolSpec(
        name="select_face",
        toolset="selection",
        description=(
            "Select a face by index from get_faces/get_entities. "
            "Prefer optional ref_id when both given; else pass x,y,z (centroid) after edits "
            "(re-resolves within 2mm); bare index alone is unsafe."
        ),
        input_schema=make_schema(
            {
                "index": {"type": "integer"},
                "x": {"type": "number"},
                "y": {"type": "number"},
                "z": {"type": "number"},
                "unit": {"type": "string", "enum": _UNIT_ENUM, "description": _UNIT_DESC},
                "ref_id": {
                    "type": "string",
                    "description": "Opaque persist ref from get_entities; wins over index when both given.",
                },
            },
            ["index"],
        ),
        handler=select_face,
        mutating=True,
    ),
    ToolSpec(
        name="select_edge",
        toolset="selection",
        description=(
            "Select an edge by index from get_edges/get_entities. "
            "Prefer optional ref_id when both given; else pass x,y,z (midpoint) after edits "
            "(re-resolves within 2mm); bare index alone is unsafe."
        ),
        input_schema=make_schema(
            {
                "index": {"type": "integer"},
                "x": {"type": "number"},
                "y": {"type": "number"},
                "z": {"type": "number"},
                "unit": {"type": "string", "enum": _UNIT_ENUM, "description": _UNIT_DESC},
                "ref_id": {
                    "type": "string",
                    "description": "Opaque persist ref from get_entities; wins over index when both given.",
                },
            },
            ["index"],
        ),
        handler=select_edge,
        mutating=True,
    ),
    ToolSpec(
        name="get_faces",
        toolset="selection",
        description=(
            "List faces (index, centroid, plane normal, cylinder axis, ref_id). "
            "kind=plane|cylinder|cone filters; query=max_z|min_z|max_x|min_x|max_y|min_y "
            "picks extreme centroids; query=axis_z|axis_x|axis_y picks cylinders parallel to that axis. "
            "limit/offset paginate; indexes stay global."
        ),
        input_schema=make_schema(
            {
                "kind": {
                    "type": "string",
                    "enum": sorted(FACE_FILTER_KINDS),
                    "description": "Optional face kind filter.",
                },
                "query": {
                    "type": "string",
                    "enum": sorted(FACE_QUERIES),
                    "description": "Optional semantic query (extreme centroid or cylinder axis).",
                },
                "unit": {"type": "string", "enum": _UNIT_ENUM, "description": _UNIT_DESC},
                "limit": {"type": "integer", "minimum": 1},
                "offset": {"type": "integer", "minimum": 0},
            }
        ),
        handler=get_faces,
        timeout_class="fast",
    ),
    ToolSpec(
        name="get_vertices",
        toolset="selection",
        description=(
            "List solid-body vertices (index + position + ref_id). "
            "Use index with extrude direction=up_to_vertex."
        ),
        input_schema=make_schema(
            {
                "unit": {"type": "string", "enum": _UNIT_ENUM, "description": _UNIT_DESC},
                "limit": {"type": "integer", "minimum": 1},
                "offset": {"type": "integer", "minimum": 0},
            }
        ),
        handler=get_vertices,
        timeout_class="fast",
    ),
    ToolSpec(
        name="get_edges",
        toolset="selection",
        description="List all edges with index, midpoint, ref_id; limit/offset paginate.",
        input_schema=make_schema(
            {
                "limit": {"type": "integer", "minimum": 1},
                "offset": {"type": "integer", "minimum": 0},
            }
        ),
        handler=get_edges,
        timeout_class="fast",
    ),
    ToolSpec(
        name="get_selection",
        toolset="selection",
        description="Read entities the user manually picked in the SolidWorks GUI as selector handles.",
        input_schema=make_schema({}),
        handler=get_selection,
    ),
]
