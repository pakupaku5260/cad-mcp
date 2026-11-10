"""Assembly toolset: assembly document, insert components, mates (including screw mate).

Same unit rules as core: lengths via UnitContext to meters; backend uses SI.
"""
from __future__ import annotations

import math

from cadmcp.backend.protocol.constants import POSE_PIVOTS, REVOLVE_AXES
from cadmcp.backend.protocol.parsers import linear_pattern_offset_m, mate_entity_to_si
from cadmcp.errors import fail
from cadmcp.kernel import OpContext
from cadmcp.registry import ToolSpec, make_schema
from cadmcp.safety import ensure_input_path
from cadmcp.units import SUPPORTED_UNITS, UnitContext

_COMP_EXTS = frozenset({"sldprt", "sldasm"})
_UNIT_DESC = "Unit; default mm."
_UNIT_ENUM = sorted(SUPPORTED_UNITS)
_ALIGN_ENUM = ["aligned", "anti_aligned", "closest"]
_ALIGN_DESC = "Mate alignment; omit for the SolidWorks default (closest for coincident/concentric/tangent)."


def _unit_ctx(ctx: OpContext, unit: str) -> UnitContext:
    return ctx.units if unit == ctx.units.external_unit else UnitContext(unit)


def _si_entity(ctx: OpContext, entity: str, unit: str = "mm") -> str:
    return mate_entity_to_si(entity, _unit_ctx(ctx, unit).to_m)


def new_assembly(ctx: OpContext, template: str | None = None) -> dict:
    info = ctx.backend.new_assembly(template)
    return {
        "title": info.title,
        "path": info.path,
        "doc_type": info.doc_type,
        "modified": info.modified,
        "units": info.units,
    }


def insert_component(
    ctx: OpContext,
    path: str,
    x: float = 0.0,
    y: float = 0.0,
    z: float = 0.0,
    unit: str = "mm",
) -> dict:
    uc = _unit_ctx(ctx, unit)
    resolved = ensure_input_path(path, roots=ctx.workspace, extensions=_COMP_EXTS)
    ref = ctx.backend.insert_component(
        resolved, uc.to_m(x), uc.to_m(y), uc.to_m(z)
    )
    origin = ref.origin_m or (uc.to_m(x), uc.to_m(y), uc.to_m(z))
    bbox = ref.bbox_m or (*origin, *origin)
    return {
        "name": ref.name,
        "path": ref.path,
        "unit": uc.external_unit,
        "origin": list(uc.tuple_from_m(origin)),
        "bbox": list(uc.tuple_from_m(bbox)),
    }


def _pose_payload(ref, uc: UnitContext) -> dict:
    origin = ref.origin_m or (0.0, 0.0, 0.0)
    bbox = ref.bbox_m or (*origin, *origin)
    return {
        "name": ref.name,
        "path": ref.path,
        "unit": uc.external_unit,
        "origin": list(uc.tuple_from_m(origin)),
        "bbox": list(uc.tuple_from_m(bbox)),
        "lightweight": bool(getattr(ref, "lightweight", False)),
    }


def move_component(
    ctx: OpContext,
    component: str,
    x: float,
    y: float,
    z: float,
    unit: str = "mm",
    relative: bool = False,
    force: bool = False,
) -> dict:
    uc = _unit_ctx(ctx, unit)
    ref = ctx.backend.move_component(
        component, uc.to_m(x), uc.to_m(y), uc.to_m(z), relative=relative, force=force
    )
    return {**_pose_payload(ref, uc), "relative": relative, "force": force}


def rotate_component(
    ctx: OpContext,
    component: str,
    axis: str,
    angle_deg: float,
    unit: str = "mm",
    about: str = "origin",
    absolute: bool = False,
    force: bool = False,
    pivot: list[float] | None = None,
) -> dict:
    import math

    uc = _unit_ctx(ctx, unit)
    pivot_m = None
    if pivot is not None:
        if len(pivot) != 3:
            raise fail("INVALID_ARGUMENT", "pivot must be [x,y,z] with length 3", "Pass three coordinates")
        pivot_m = (uc.to_m(pivot[0]), uc.to_m(pivot[1]), uc.to_m(pivot[2]))
    ref = ctx.backend.rotate_component(
        component,
        axis,
        math.radians(angle_deg),
        about=about,
        absolute=absolute,
        force=force,
        pivot_m=pivot_m,
    )
    out = {
        **_pose_payload(ref, uc),
        "axis": axis,
        "angle_deg": angle_deg,
        "about": about,
        "absolute": absolute,
        "force": force,
    }
    if pivot is not None:
        out["pivot"] = [float(v) for v in pivot]
    return out


def list_components(ctx: OpContext, unit: str = "mm", children: bool = False) -> dict:
    uc = _unit_ctx(ctx, unit)
    items = [_pose_payload(ref, uc) for ref in ctx.backend.list_components(children=children)]
    return {"count": len(items), "unit": uc.external_unit, "components": items}


def get_component(ctx: OpContext, component: str, unit: str = "mm") -> dict:
    uc = _unit_ctx(ctx, unit)
    return _pose_payload(ctx.backend.get_component(component), uc)


def set_lightweight(ctx: OpContext, component: str, lightweight: bool) -> dict:
    name = ctx.backend.set_lightweight(component, lightweight)
    return {"component": name, "lightweight": bool(lightweight)}


def _explode_payload(name: str | None, names: list[str], exploded: bool) -> dict:
    return {"name": name, "names": names, "count": len(names), "exploded": exploded}


def explode_view(ctx: OpContext) -> dict:
    name, names = ctx.backend.explode_view()
    return _explode_payload(name, names, True)


def show_exploded(ctx: OpContext, show: bool = True, name: str | None = None) -> dict:
    chosen, names, exploded = ctx.backend.show_exploded(show, name)
    return _explode_payload(chosen, names, exploded)


def list_exploded_views(ctx: OpContext) -> dict:
    names, exploded = ctx.backend.list_exploded_views()
    return _explode_payload(None, names, exploded)


def edit_component(ctx: OpContext, component: str) -> dict:
    name = ctx.backend.edit_component(component)
    return {"component": name, "editing": True}


def end_edit(ctx: OpContext) -> dict:
    ctx.backend.end_edit()
    return {"editing": False}


def get_edit_target(ctx: OpContext) -> dict:
    name = ctx.backend.get_edit_target()
    return {"component": name, "editing": name is not None}


def pattern_component(
    ctx: OpContext,
    component: str,
    count: int,
    axis: str | None = None,
    unit: str = "mm",
    about: str = "world",
    dx: float | None = None,
    dy: float | None = None,
    dz: float | None = None,
) -> dict:
    uc = _unit_ctx(ctx, unit)
    dx_m = None if dx is None else uc.to_m(dx)
    dy_m = None if dy is None else uc.to_m(dy)
    dz_m = None if dz is None else uc.to_m(dz)
    linear_pattern_offset_m(dx_m, dy_m, dz_m)
    feat, refs = ctx.backend.pattern_component(
        component, int(count), axis, about=about, dx_m=dx_m, dy_m=dy_m, dz_m=dz_m,
    )
    out = {
        "name": feat.name,
        "kind": feat.kind,
        "count": len(refs),
        "about": about,
        "unit": uc.external_unit,
        "components": [_pose_payload(ref, uc) for ref in refs],
    }
    if axis is not None:
        out["axis"] = axis
    if dx is not None:
        out["dx"] = dx
    if dy is not None:
        out["dy"] = dy
    if dz is not None:
        out["dz"] = dz
    return out


def get_component_faces(ctx: OpContext, component: str, kind: str | None = None) -> dict:
    u = ctx.units
    faces = [
        {
            "index": f.index,
            "kind": f.kind,
            "centroid": list(u.tuple_from_m(f.centroid_m)),
            **({"normal": [float(v) for v in f.normal_m]} if f.normal_m is not None else {}),
        }
        for f in ctx.backend.list_component_faces(component, kind)
    ]
    return {"component": component, "faces": faces, "length_unit": u.external_unit}


def get_component_edges(ctx: OpContext, component: str, kind: str | None = None) -> dict:
    u = ctx.units
    edges = [
        {
            "index": e.index,
            "kind": e.kind,
            "midpoint": list(u.tuple_from_m(e.midpoint_m)),
        }
        for e in ctx.backend.list_component_edges(component, kind)
    ]
    return {"component": component, "edges": edges, "length_unit": u.external_unit}


def _mate_payload(mate) -> dict:
    out = {"name": mate.name, "mate_type": mate.mate_type}
    if mate.sw_error is not None and mate.sw_error != 1:
        out["mate_status"] = mate.sw_error
        out["warning"] = (
            "Mate was created but SolidWorks reported over-defined or other non-success; "
            "use list_mates and delete_mate if needed"
        )
    return out


def list_mates(ctx: OpContext) -> dict:
    mates = [{"name": m.name, "mate_type": m.mate_type} for m in ctx.backend.list_mates()]
    return {"mates": mates}


def delete_mate(ctx: OpContext, name: str) -> dict:
    ctx.backend.delete_mate(name)
    return {"deleted": name}


def check_interference(
    ctx: OpContext,
    component1: str | None = None,
    component2: str | None = None,
    coincident_as_interference: bool = False,
) -> dict:
    pairs, method = ctx.backend.check_interference(
        component1, component2, coincident_as_interference
    )
    return {
        "count": len(pairs),
        "pairs": [
            {
                "a": p.a,
                "b": p.b,
                "status": p.status,
                **({"volume": p.volume_m3} if p.volume_m3 is not None else {}),
            }
            for p in pairs
        ],
        "method": method,
        "coincident_as_interference": coincident_as_interference,
    }


MATE_TYPES = ("concentric", "coincident", "distance", "angle", "tangent", "screw")


def mate(
    ctx: OpContext,
    type: str,
    entity1: str,
    entity2: str,
    distance: float | None = None,
    angle_deg: float | None = None,
    pitch: float | None = None,
    align: str | None = None,
    unit: str = "mm",
) -> dict:
    if type not in MATE_TYPES:
        raise fail(
            "INVALID_ARGUMENT",
            f"Unknown mate type: {type}",
            f"Use: {', '.join(MATE_TYPES)}",
        )
    allowed = {"distance": {"distance"}, "angle": {"angle_deg"}, "screw": {"pitch"}}
    keep = allowed.get(type, set())
    for name, value in (
        ("distance", distance), ("angle_deg", angle_deg), ("pitch", pitch)
    ):
        if name not in keep and value is not None:
            raise fail(
                "INVALID_ARGUMENT",
                f"{type} mate does not accept {name}",
                "Remove the parameter or choose a matching type",
            )

    uc = _unit_ctx(ctx, unit)
    e1 = _si_entity(ctx, entity1, unit)
    e2 = _si_entity(ctx, entity2, unit)
    if type == "concentric":
        info = ctx.backend.mate_concentric(e1, e2, align)
    elif type == "coincident":
        info = ctx.backend.mate_coincident(e1, e2, align)
    elif type == "distance":
        if distance is None:
            raise fail("INVALID_ARGUMENT", "distance mate requires distance", "Pass distance > 0")
        info = ctx.backend.mate_distance(e1, e2, uc.to_m(distance), align)
    elif type == "angle":
        if angle_deg is None:
            raise fail("INVALID_ARGUMENT", "angle mate requires angle_deg", "Pass angle_deg")
        info = ctx.backend.mate_angle(e1, e2, math.radians(angle_deg), align)
    elif type == "tangent":
        info = ctx.backend.mate_tangent(e1, e2, align)
    else:  # screw
        if pitch is None:
            raise fail("INVALID_ARGUMENT", "screw mate requires pitch", "Pass pitch > 0")
        if pitch <= 0:
            raise fail("INVALID_ARGUMENT", "Pitch must be positive", "Pass pitch > 0")
        info = ctx.backend.mate_screw(e1, e2, uc.to_m(pitch), align)

    payload = _mate_payload(info)
    if type in {"distance", "screw"}:
        payload["unit"] = uc.external_unit
    elif type == "angle":
        payload["angle_deg"] = angle_deg
    return payload


ASSEMBLY_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="new_assembly",
        toolset="assembly",
        description="Create a new assembly (.SLDASM) and make it active.",
        input_schema=make_schema(
            {"template": {"type": "string", "description": "Optional .asmdot template path."}}
        ),
        handler=new_assembly,
        mutating=True,
    ),
    ToolSpec(
        name="insert_component",
        toolset="assembly",
        description=(
            "Insert a part (.sldprt) or subassembly (.sldasm). x,y,z is the component "
            "origin in assembly coordinates (not the bounding-box center). "
            "Returns origin and bbox in the call unit."
        ),
        input_schema=make_schema(
            {
                "path": {"type": "string", "description": "Part or assembly path relative to workspace."},
                "x": {"type": "number", "default": 0.0, "description": "Part-origin X."},
                "y": {"type": "number", "default": 0.0, "description": "Part-origin Y."},
                "z": {"type": "number", "default": 0.0, "description": "Part-origin Z."},
                "unit": {"type": "string", "enum": _UNIT_ENUM, "description": _UNIT_DESC},
            },
            ["path"],
        ),
        handler=insert_component,
        mutating=True,
    ),
    ToolSpec(
        name="move_component",
        toolset="assembly",
        description=(
            "Move an assembly component so its part origin sits at x,y,z "
            "(assembly coordinates). relative=true adds x,y,z to the current origin. "
            "Fails with FEATURE_CREATE_FAILED if the instance already has mates; "
            "delete_mate first, or pass force=true to write the transform anyway. "
            "Fixed (grounded) instances are unfixed."
        ),
        input_schema=make_schema(
            {
                "component": {"type": "string", "description": "Instance name from insert_component."},
                "x": {"type": "number", "description": "Part-origin X (absolute, or delta if relative)."},
                "y": {"type": "number", "description": "Part-origin Y."},
                "z": {"type": "number", "description": "Part-origin Z."},
                "unit": {"type": "string", "enum": _UNIT_ENUM, "description": _UNIT_DESC},
                "relative": {
                    "type": "boolean",
                    "default": False,
                    "description": "If true, x,y,z is added to the current origin.",
                },
                "force": {
                    "type": "boolean",
                    "default": False,
                    "description": "Write the transform even if the instance has mates.",
                },
            },
            ["component", "x", "y", "z"],
        ),
        handler=move_component,
        mutating=True,
    ),
    ToolSpec(
        name="rotate_component",
        toolset="assembly",
        description=(
            "Rotate an assembly component about a model axis (degrees). "
            "Relative by default; absolute=true replaces the 3x3 from identity and keeps translation. "
            "about=origin (default) through the part origin; about=world through (0,0,0). "
            "pivot=[x,y,z] overrides about. Fails if the instance has mates unless force=true."
        ),
        input_schema=make_schema(
            {
                "component": {"type": "string", "description": "Instance name from insert_component."},
                "axis": {
                    "type": "string",
                    "enum": list(REVOLVE_AXES),
                    "description": "Model axis: +x/-x/+y/-y/+z/-z.",
                },
                "angle_deg": {"type": "number", "description": "Rotation in degrees."},
                "unit": {"type": "string", "enum": _UNIT_ENUM, "description": _UNIT_DESC},
                "about": {
                    "type": "string",
                    "enum": list(POSE_PIVOTS),
                    "default": "origin",
                    "description": "Pivot: part origin, or assembly origin.",
                },
                "absolute": {
                    "type": "boolean",
                    "default": False,
                    "description": "Replace orientation from identity; keep origin.",
                },
                "force": {
                    "type": "boolean",
                    "default": False,
                    "description": "Write the transform even if the instance has mates.",
                },
                "pivot": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                    "description": "Custom pivot [x,y,z] in the call unit; overrides about.",
                },
            },
            ["component", "axis", "angle_deg"],
        ),
        handler=rotate_component,
        mutating=True,
    ),
    ToolSpec(
        name="list_components",
        toolset="assembly",
        description=(
            "List components in the active assembly (name, path, origin, bbox). "
            "Default is top-level only; children=true flattens nested names like p1-1@sub-1."
        ),
        input_schema=make_schema(
            {
                "unit": {"type": "string", "enum": _UNIT_ENUM, "description": _UNIT_DESC},
                "children": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include instances inside subassemblies (p1-1@sub-1).",
                },
            }
        ),
        handler=list_components,
        mutating=False,
        timeout_class="fast",
    ),
    ToolSpec(
        name="get_component",
        toolset="assembly",
        description="Read one assembly component by instance name (origin and bbox).",
        input_schema=make_schema(
            {
                "component": {"type": "string", "description": "Instance name from insert_component."},
                "unit": {"type": "string", "enum": _UNIT_ENUM, "description": _UNIT_DESC},
            },
            ["component"],
        ),
        handler=get_component,
        mutating=False,
        timeout_class="fast",
    ),
    ToolSpec(
        name="set_lightweight",
        toolset="assembly",
        description="Set a component lightweight or fully resolved (SetSuppression2). Does not suppress.",
        input_schema=make_schema(
            {
                "component": {"type": "string", "description": "Instance name from list_components."},
                "lightweight": {"type": "boolean", "description": "true=lightweight, false=fully resolved."},
            },
            ["component", "lightweight"],
        ),
        handler=set_lightweight,
        mutating=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="explode_view",
        toolset="assembly",
        description="Create an exploded view (CreateExplodedView). Axial feed / screw-in is not supported.",
        input_schema=make_schema({}),
        handler=explode_view,
        mutating=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="show_exploded",
        toolset="assembly",
        description="Show or collapse an exploded view. Omit name to use the latest view.",
        input_schema=make_schema(
            {
                "show": {"type": "boolean", "default": True, "description": "true=exploded, false=collapsed."},
                "name": {"type": "string", "description": "Exploded view name from list_exploded_views."},
            }
        ),
        handler=show_exploded,
        mutating=True,
    ),
    ToolSpec(
        name="list_exploded_views",
        toolset="assembly",
        description="List exploded view names and whether the assembly is currently exploded.",
        input_schema=make_schema({}),
        handler=list_exploded_views,
        mutating=False,
        timeout_class="fast",
    ),
    ToolSpec(
        name="edit_component",
        toolset="assembly",
        description="Edit a subassembly in the context of the parent (Edit Assembly). Part in-context edit is not supported.",
        input_schema=make_schema(
            {"component": {"type": "string", "description": "Subassembly instance name (e.g. sub-1)."}},
            ["component"],
        ),
        handler=edit_component,
        mutating=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="end_edit",
        toolset="assembly",
        description="Exit in-context subassembly edit and return to the top assembly.",
        input_schema=make_schema({}),
        handler=end_edit,
        mutating=True,
    ),
    ToolSpec(
        name="get_edit_target",
        toolset="assembly",
        description="Return the component currently being edited in-context, or editing=false at the top assembly.",
        input_schema=make_schema({}),
        handler=get_edit_target,
        mutating=False,
        timeout_class="fast",
    ),
    ToolSpec(
        name="pattern_component",
        toolset="assembly",
        description=(
            "Component pattern: axis for circular (LocalCirPattern) or dx/dy/dz for linear "
            "(LocalLPattern). count includes the seed (>= 2). Delete the feature to drop copies."
        ),
        input_schema=make_schema(
            {
                "component": {"type": "string", "description": "Seed instance name."},
                "count": {"type": "integer", "description": "Total instances including the seed (>= 2)."},
                "axis": {
                    "type": "string",
                    "enum": list(REVOLVE_AXES),
                    "description": "Circular axis +x/-x/+y/-y/+z/-z.",
                },
                "about": {
                    "type": "string",
                    "enum": list(POSE_PIVOTS),
                    "default": "world",
                    "description": "Circular pivot: world or origin.",
                },
                "unit": {"type": "string", "enum": _UNIT_ENUM, "description": _UNIT_DESC},
                "dx": {"type": "number"},
                "dy": {"type": "number"},
                "dz": {"type": "number"},
            },
            ["component", "count"],
        ),
        handler=pattern_component,
        mutating=True,
    ),
    ToolSpec(
        name="get_component_faces",
        toolset="assembly",
        description=(
            "List faces of an assembly component (index + kind + centroid + unit normal). "
            "Optional kind=plane|cylinder|cone keeps global index. Mate refs: "
            "'<instance>#face:<index>' or '#cylinder:0' / '#plane:0' / '#cone:0'."
        ),
        input_schema=make_schema(
            {
                "component": {"type": "string", "description": "Instance name from insert_component."},
                "kind": {
                    "type": "string",
                    "enum": ["plane", "cylinder", "cone"],
                    "description": "If set, only faces of this kind; index stays global.",
                },
            },
            ["component"],
        ),
        handler=get_component_faces,
        mutating=False,
        timeout_class="fast",
    ),
    ToolSpec(
        name="get_component_edges",
        toolset="assembly",
        description=(
            "List edges of an assembly component (index + kind + midpoint). "
            "Optional kind=line|circle keeps global index. Mate refs: "
            "'<instance>#edge:<index>' or '#circle:0'."
        ),
        input_schema=make_schema(
            {
                "component": {"type": "string", "description": "Instance name from insert_component."},
                "kind": {
                    "type": "string",
                    "enum": ["line", "circle"],
                    "description": "If set, only edges of this kind; index stays global.",
                },
            },
            ["component"],
        ),
        handler=get_component_edges,
        mutating=False,
        timeout_class="fast",
    ),
    ToolSpec(
        name="mate",
        toolset="assembly",
        description=(
            "Create a mate between two entities. type=concentric|coincident|distance|"
            "angle|tangent|screw. Entities: '#face:N', '#edge:N', '#cylinder:N', "
            "'#cone:N', '#circle:N' (optional ':x,y,z'), or 'Top Plane@component'. "
            "distance (length) only for distance, angle_deg only for angle, "
            "pitch (length per revolution) only for screw."
        ),
        input_schema=make_schema(
            {
                "type": {"type": "string", "enum": list(MATE_TYPES)},
                "entity1": {"type": "string"},
                "entity2": {"type": "string"},
                "distance": {"type": "number", "exclusiveMinimum": 0},
                "angle_deg": {"type": "number"},
                "pitch": {"type": "number", "exclusiveMinimum": 0},
                "align": {"type": "string", "enum": _ALIGN_ENUM, "description": _ALIGN_DESC},
                "unit": {"type": "string", "enum": _UNIT_ENUM, "description": _UNIT_DESC},
            },
            ["type", "entity1", "entity2"],
        ),
        handler=mate,
        mutating=True,
    ),
    ToolSpec(
        name="list_mates",
        toolset="assembly",
        description="List mates in the active assembly (name + mate_type).",
        input_schema=make_schema({}),
        handler=list_mates,
        mutating=False,
        timeout_class="fast",
    ),
    ToolSpec(
        name="delete_mate",
        toolset="assembly",
        description="Delete a mate by name from list_mates. Missing name is FEATURE_NOT_FOUND.",
        input_schema=make_schema(
            {"name": {"type": "string", "description": "Mate feature name."}},
            ["name"],
        ),
        handler=delete_mate,
        mutating=True,
    ),
    ToolSpec(
        name="check_interference",
        toolset="assembly",
        description=(
            "Check component interference in the active assembly. "
            "Omitting component1/component2 checks all pairs. "
            "Returns non-clear pairs with status interfere|contact|unknown. "
            "AABB overlap is the fallback; live SolidWorks uses InterferenceDetectionManager."
        ),
        input_schema=make_schema(
            {
                "component1": {"type": "string", "description": "Optional instance name."},
                "component2": {"type": "string", "description": "Optional second instance name."},
                "coincident_as_interference": {
                    "type": "boolean",
                    "default": False,
                    "description": "Treat coincident (zero-volume contact) as interference.",
                },
            }
        ),
        handler=check_interference,
        mutating=False,
        timeout_class="slow",
    ),
]
