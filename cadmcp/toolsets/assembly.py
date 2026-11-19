"""Assembly toolset: assembly document, insert components, mates (including screw mate).

Same unit rules as core: lengths via UnitContext to meters; backend uses SI.
"""
from __future__ import annotations

import math

from cadmcp.assembly_dof import assess, not_applicable_payload
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
        "suppressed": bool(getattr(ref, "suppressed", False)),
        "flexible": bool(getattr(ref, "flexible", False)),
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


def list_components_lite(ctx: OpContext, unit: str = "mm", children: bool = False) -> dict:
    """Fast list: name/path/origin; bbox only when IComponent2.GetBox succeeds (no face walk)."""
    uc = _unit_ctx(ctx, unit)
    items = []
    for ref in ctx.backend.list_components_lite(children=children):
        origin = ref.origin_m or (0.0, 0.0, 0.0)
        item = {
            "name": ref.name,
            "path": ref.path,
            "origin": list(uc.tuple_from_m(origin)),
        }
        if ref.bbox_m is not None:
            item["bbox"] = list(uc.tuple_from_m(ref.bbox_m))
        items.append(item)
    return {
        "count": len(items),
        "unit": uc.external_unit,
        "components": items,
        "lite": True,
    }


def get_component(ctx: OpContext, component: str, unit: str = "mm") -> dict:
    uc = _unit_ctx(ctx, unit)
    return _pose_payload(ctx.backend.get_component(component), uc)


def set_lightweight(ctx: OpContext, component: str, lightweight: bool) -> dict:
    name = ctx.backend.set_lightweight(component, lightweight)
    return {"component": name, "lightweight": bool(lightweight)}


def set_suppressed(ctx: OpContext, component: str, suppressed: bool) -> dict:
    name = ctx.backend.set_suppressed(component, suppressed)
    return {"component": name, "suppressed": bool(suppressed)}


def set_flexible(ctx: OpContext, component: str, flexible: bool) -> dict:
    name = ctx.backend.set_flexible(component, flexible)
    return {"component": name, "flexible": bool(flexible)}


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
    unit: str = "mm",
) -> dict:
    uc = _unit_ctx(ctx, unit)
    volume_unit = f"{uc.external_unit}3"
    pairs, method = ctx.backend.check_interference(
        component1, component2, coincident_as_interference
    )
    out_pairs: list[dict] = []
    for p in pairs:
        row: dict = {
            "a": p.a,
            "b": p.b,
            "status": p.status,
            "volume": None,
            "volume_unit": volume_unit,
        }
        if p.volume_m3 is not None:
            row["volume"] = uc.volume_from_m3(p.volume_m3)
        out_pairs.append(row)
    return {
        "count": len(out_pairs),
        "pairs": out_pairs,
        "method": method,
        "coincident_as_interference": coincident_as_interference,
        "unit": uc.external_unit,
    }


MATE_TYPES = (
    "concentric",
    "coincident",
    "distance",
    "angle",
    "tangent",
    "screw",
    "gear",
    "width",
    "cam",
)


def mate(
    ctx: OpContext,
    type: str,
    entity1: str,
    entity2: str,
    distance: float | None = None,
    angle_deg: float | None = None,
    pitch: float | None = None,
    ratio_num: int | None = None,
    ratio_den: int | None = None,
    entity3: str | None = None,
    align: str | None = None,
    unit: str = "mm",
) -> dict:
    if type not in MATE_TYPES:
        raise fail(
            "INVALID_ARGUMENT",
            f"Unknown mate type: {type}",
            f"Use: {', '.join(MATE_TYPES)}",
        )
    allowed = {
        "distance": {"distance"},
        "angle": {"angle_deg"},
        "screw": {"pitch"},
        "gear": {"ratio_num", "ratio_den"},
        "width": {"entity3"},
    }
    keep = allowed.get(type, set())
    for name, value in (
        ("distance", distance),
        ("angle_deg", angle_deg),
        ("pitch", pitch),
        ("ratio_num", ratio_num),
        ("ratio_den", ratio_den),
        ("entity3", entity3),
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
    elif type == "screw":
        if pitch is None:
            raise fail("INVALID_ARGUMENT", "screw mate requires pitch", "Pass pitch > 0")
        if pitch <= 0:
            raise fail("INVALID_ARGUMENT", "Pitch must be positive", "Pass pitch > 0")
        info = ctx.backend.mate_screw(e1, e2, uc.to_m(pitch), align)
    elif type == "gear":
        if ratio_num is None or ratio_den is None:
            raise fail(
                "INVALID_ARGUMENT",
                "gear mate requires ratio_num and ratio_den",
                "Pass positive integers for the tooth ratio",
            )
        info = ctx.backend.mate_gear(e1, e2, int(ratio_num), int(ratio_den), align)
    elif type == "width":
        if not entity3:
            raise fail(
                "INVALID_ARGUMENT",
                "width mate requires entity3",
                "Pass two width faces (entity1/2) and the tab face/edge (entity3)",
            )
        e3 = _si_entity(ctx, entity3, unit)
        info = ctx.backend.mate_width(e1, e2, e3, align)
    else:  # cam
        info = ctx.backend.mate_cam(e1, e2, align)

    payload = _mate_payload(info)
    if type in {"distance", "screw"}:
        payload["unit"] = uc.external_unit
    elif type == "angle":
        payload["angle_deg"] = angle_deg
    elif type == "gear":
        payload["ratio_num"] = int(ratio_num)
        payload["ratio_den"] = int(ratio_den)
    return payload


def replace_component(
    ctx: OpContext, component: str, path: str, config: str = ""
) -> dict:
    resolved = ensure_input_path(path, roots=ctx.workspace, extensions=_COMP_EXTS)
    ref = ctx.backend.replace_component(component, resolved, config=config or "")
    return {
        "name": ref.name,
        "path": ref.path,
        "replaced": True,
        "config": config or "",
    }


_CHECK_DOF_DESCRIPTION = (
    "Heuristic assembly DOF estimate from component count and mate-type weights "
    "(lower bound; not a SolidWorks DOF solver). Read-only; does not call "
    "verify_model or bump state_version. Non-assembly documents return "
    "status=not_applicable without listing mates/components. "
    "Returns verification, dof_estimate, assembly_order, mates, "
    "unknown_mate_types, assumptions, risk. "
    "Read cadmcp://help/assembly_dof before interpreting the estimate."
)


def _dispatch_payload(ctx: OpContext, name: str, args: dict | None = None) -> dict | None:
    if ctx.dispatch is None:
        return None
    result = ctx.dispatch(name, args or {})
    if not result.ok or result.result is None:
        return None
    return result.result


# Datum plane name → unit normal in the component's local frame.
_FIX_PLANE_LOCAL_N = {
    "Front Plane": (0.0, 0.0, 1.0),
    "Top Plane": (0.0, 1.0, 0.0),
    "Right Plane": (1.0, 0.0, 0.0),
}


def _origin_m(ref) -> tuple[float, float, float]:
    return tuple(ref.origin_m or (0.0, 0.0, 0.0))  # type: ignore[return-value]


def _bbox_m(ref) -> tuple[float, ...] | None:
    box = getattr(ref, "bbox_m", None)
    return tuple(box) if box is not None and len(box) == 6 else None


def _xf_origin_R(array16: list[float]) -> tuple[tuple[float, float, float], tuple[tuple[float, float, float], ...]]:
    """SolidWorks Transform2 ArrayData → origin + rows of rotation."""
    a = list(array16) + [0.0] * max(0, 16 - len(array16))
    R = (
        (a[0], a[1], a[2]),
        (a[3], a[4], a[5]),
        (a[6], a[7], a[8]),
    )
    origin = (a[9], a[10], a[11])
    return origin, R


def _apply_R(R: tuple[tuple[float, float, float], ...], v: tuple[float, float, float]) -> tuple[float, float, float]:
    return (
        R[0][0] * v[0] + R[0][1] * v[1] + R[0][2] * v[2],
        R[1][0] * v[0] + R[1][1] * v[1] + R[1][2] * v[2],
        R[2][0] * v[0] + R[2][1] * v[1] + R[2][2] * v[2],
    )


def _plane_plane_distance_m(
    origin_a: tuple[float, float, float],
    R_a: tuple[tuple[float, float, float], ...],
    origin_b: tuple[float, float, float],
    local_n: tuple[float, float, float],
) -> float:
    """Distance between parallel datum planes (both share the same local normal kind)."""
    n = _apply_R(R_a, local_n)
    nn = math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2])
    if nn <= 1e-15:
        return 0.0
    n = (n[0] / nn, n[1] / nn, n[2] / nn)
    d = (
        (origin_b[0] - origin_a[0]) * n[0]
        + (origin_b[1] - origin_a[1]) * n[1]
        + (origin_b[2] - origin_a[2]) * n[2]
    )
    return abs(d)


def _pose_shift_mm(
    before_origin: tuple[float, float, float],
    after_origin: tuple[float, float, float],
    before_bbox: tuple[float, ...] | None,
    after_bbox: tuple[float, ...] | None,
) -> float:
    """Max origin / bbox-corner shift in millimetres."""
    dx = math.sqrt(
        (after_origin[0] - before_origin[0]) ** 2
        + (after_origin[1] - before_origin[1]) ** 2
        + (after_origin[2] - before_origin[2]) ** 2
    )
    best = dx
    if before_bbox is not None and after_bbox is not None:
        for i in range(6):
            best = max(best, abs(after_bbox[i] - before_bbox[i]))
    return best * 1000.0


def fix_components(
    ctx: OpContext,
    components: list[str],
    preview_only: bool = True,
    verify_pose: bool = True,
    tolerance_mm: float = 0.01,
) -> dict:
    """Task-layer helper: plan/apply distance mates that lock current poses (does not change ``mate``)."""
    names = [str(c).strip() for c in (components or []) if str(c).strip()]
    if len(names) < 2:
        raise fail(
            "INVALID_ARGUMENT",
            "fix_components needs at least two component instance names",
            "Pass components from list_components_lite",
        )
    if tolerance_mm < 0:
        raise fail("INVALID_ARGUMENT", "tolerance_mm must be >= 0", "Pass a non-negative tolerance")

    # Snapshot poses + transforms up front.
    snapshots: dict[str, dict] = {}
    for name in names:
        ref = ctx.backend.get_component(name)
        xf = ctx.backend.get_component_transform(name)
        origin, R = _xf_origin_R(list(xf))
        snapshots[name] = {
            "origin_m": _origin_m(ref),
            "bbox_m": _bbox_m(ref),
            "xf": list(xf),
            "R": R,
            "xf_origin": origin,
        }

    anchor = names[0]
    a = snapshots[anchor]
    plan: list[dict] = []
    for name in names[1:]:
        b = snapshots[name]
        for plane, local_n in _FIX_PLANE_LOCAL_N.items():
            dist_m = _plane_plane_distance_m(a["xf_origin"], a["R"], b["xf_origin"], local_n)
            plan.append(
                {
                    "component": name,
                    "anchor": anchor,
                    "type": "distance",
                    "entity1": f"{plane}@{anchor}",
                    "entity2": f"{plane}@{name}",
                    "distance_m": dist_m,
                    "distance_mm": dist_m * 1000.0,
                    "plane": plane,
                }
            )

    if preview_only:
        return {
            "ok": True,
            "preview_only": True,
            "anchor": anchor,
            "components": names,
            "planned_mates": plan,
            "mate_count": len(plan),
            "applied": [],
            "verify_pose": bool(verify_pose),
            "tolerance_mm": float(tolerance_mm),
        }

    applied: list[dict] = []
    created_names: list[str] = []
    skipped: list[dict] = []
    # Distance mate defaults to "aligned" which often jumps to the far side of the plane.
    # Prefer "closest" (matches current pose); fall back to anti_aligned / aligned.
    _ALIGN_TRIALS = ("closest", "anti_aligned", "aligned")

    def _restore(*comp_names: str) -> None:
        for name in comp_names:
            snap = snapshots.get(name)
            if snap is None:
                continue
            try:
                ctx.backend.set_component_transform(name, snap["xf"])
            except Exception:
                pass

    def _restore_all() -> None:
        _restore(*names)

    def _shift_of(name: str) -> float:
        after = ctx.backend.get_component(name)
        before = snapshots[name]
        return _pose_shift_mm(
            before["origin_m"],
            _origin_m(after),
            before["bbox_m"],
            _bbox_m(after),
        )

    def _annotate_row(row: dict, name: str, shift: float) -> None:
        before = snapshots[name]
        after = ctx.backend.get_component(name)
        row["shift_mm"] = shift
        row["origin_before_mm"] = [c * 1000.0 for c in before["origin_m"]]
        row["origin_after_mm"] = [c * 1000.0 for c in _origin_m(after)]
        row["bbox_before_mm"] = (
            [c * 1000.0 for c in before["bbox_m"]] if before["bbox_m"] else None
        )
        row["bbox_after_mm"] = (
            [c * 1000.0 for c in (_bbox_m(after) or ())] if _bbox_m(after) else None
        )

    # Apply largest-gap plane first per component (more stable lock); keep at most one
    # successful mate per floating instance to avoid over-constraint / solver fights.
    by_comp: dict[str, list[dict]] = {}
    for step in plan:
        by_comp.setdefault(step["component"], []).append(step)
    for steps in by_comp.values():
        steps.sort(key=lambda s: float(s["distance_m"]), reverse=True)

    try:
        for steps in by_comp.values():
            kept_for_comp = False
            for step in steps:
                if kept_for_comp:
                    skipped.append(
                        {
                            "component": step["component"],
                            "plane": step["plane"],
                            "distance_mm": step["distance_mm"],
                            "reason": "skipped: one pose-lock mate already kept for component",
                        }
                    )
                    continue
                kept = False
                last_err: Exception | None = None
                for align in _ALIGN_TRIALS:
                    try:
                        info = ctx.backend.mate_distance(
                            step["entity1"],
                            step["entity2"],
                            float(step["distance_m"]),
                            align,
                        )
                    except Exception as exc:  # noqa: BLE001 — try next align
                        last_err = exc
                        continue
                    shift = max(_shift_of(step["component"]), _shift_of(anchor))
                    if verify_pose and shift > float(tolerance_mm):
                        try:
                            ctx.backend.delete_mate(info.name)
                        except Exception:
                            pass
                        _restore(step["component"], anchor)
                        last_err = None
                        continue
                    row = {
                        "component": step["component"],
                        "mate": info.name,
                        "plane": step["plane"],
                        "distance_mm": step["distance_mm"],
                        "entity1": step["entity1"],
                        "entity2": step["entity2"],
                        "align": align,
                    }
                    if verify_pose:
                        _annotate_row(row, step["component"], shift)
                    created_names.append(info.name)
                    applied.append(row)
                    kept = True
                    kept_for_comp = True
                    break
                if not kept:
                    skipped.append(
                        {
                            "component": step["component"],
                            "plane": step["plane"],
                            "distance_mm": step["distance_mm"],
                            "reason": (
                                "pose shift above tolerance for all align trials"
                                if last_err is None
                                else f"mate failed: {last_err}"
                            ),
                        }
                    )
        if not applied:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "fix_components could not create any pose-preserving distance mate",
                "Check component datum planes / poses; try preview_only then adjust placement",
                skipped=skipped,
                tolerance_mm=float(tolerance_mm),
            )
        if verify_pose:
            offenders: list[dict] = []
            for name in names:
                shift = _shift_of(name)
                for row in applied:
                    if row["component"] == name:
                        _annotate_row(row, name, shift)
                if name != anchor and shift > float(tolerance_mm):
                    offenders.append({"component": name, "shift_mm": shift})
            if offenders:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    (
                        f"fix_components left {len(offenders)} instance(s) shifted above "
                        f"tolerance_mm={tolerance_mm}"
                    ),
                    "Delete mates / re-place components, or raise tolerance_mm only if intentional",
                    offenders=offenders,
                    tolerance_mm=float(tolerance_mm),
                )
    except Exception:
        for mate_name in reversed(created_names):
            try:
                ctx.backend.delete_mate(mate_name)
            except Exception:
                pass
        _restore_all()
        raise

    return {
        "ok": True,
        "preview_only": False,
        "anchor": anchor,
        "components": names,
        "planned_mates": plan,
        "mate_count": len(applied),
        "applied": applied,
        "skipped": skipped,
        "verify_pose": bool(verify_pose),
        "tolerance_mm": float(tolerance_mm),
    }


def check_assembly_dof(ctx: OpContext) -> dict:
    """Readonly heuristic DOF report for the active assembly."""
    active = _dispatch_payload(ctx, "get_active_document", {})
    if active is None or active.get("doc_type") != "assembly":
        return not_applicable_payload(
            reason="active document is missing or not an assembly",
        )

    components_payload = _dispatch_payload(ctx, "list_components", {})
    mates_payload = _dispatch_payload(ctx, "list_mates", {})
    if components_payload is None or mates_payload is None:
        return not_applicable_payload(
            reason="list_components or list_mates fact unavailable",
        )

    names = [
        str(item.get("name") or "")
        for item in (components_payload.get("components") or [])
        if item.get("name")
    ]
    mates = list(mates_payload.get("mates") or [])
    if not names:
        payload = not_applicable_payload(reason="assembly has no components")
        # Empty assembly: keep not_applicable; verification stays unverified.
        return payload

    return assess(names, mates)


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
            "Move component origin to x,y,z (asm coords); relative=true adds offset. "
            "Mated → force=true; grounded instances are unfixed."
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
            "Rotate component about axis (deg). relative default; absolute resets 3x3. "
            "about=origin|world; pivot=[x,y,z] overrides. Mated → force=true."
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
        name="list_components_lite",
        toolset="assembly",
        description=(
            "Fast component list: name/path/origin; bbox only via GetBox (no face walk). "
            "Prefer this for large assemblies; use list_components for flags/full pose."
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
        handler=list_components_lite,
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
        description="Lightweight or fully resolve a component (not suppress).",
        input_schema=make_schema(
            {
                "component": {"type": "string"},
                "lightweight": {"type": "boolean"},
            },
            ["component", "lightweight"],
        ),
        handler=set_lightweight,
        mutating=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="set_suppressed",
        toolset="assembly",
        description="Suppress or fully resolve a component (not lightweight).",
        input_schema=make_schema(
            {
                "component": {"type": "string"},
                "suppressed": {"type": "boolean"},
            },
            ["component", "suppressed"],
        ),
        handler=set_suppressed,
        mutating=True,
        timeout_class="slow",
    ),
    ToolSpec(
        name="set_flexible",
        toolset="assembly",
        description="Set subassembly flexible/rigid; parts rejected.",
        input_schema=make_schema(
            {
                "component": {"type": "string"},
                "flexible": {"type": "boolean"},
            },
            ["component", "flexible"],
        ),
        handler=set_flexible,
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
            "Mate: concentric|coincident|distance|angle|tangent|screw|gear|width|cam. "
            "Refs '#face:N'/'#cylinder:N'. gear:ratio_*; width:entity3; "
            "cam=BLOCKED on SW2025 COM (may FEATURE_CREATE_FAILED)."
        ),
        input_schema=make_schema(
            {
                "type": {"type": "string", "enum": list(MATE_TYPES)},
                "entity1": {"type": "string"},
                "entity2": {"type": "string"},
                "entity3": {"type": "string", "description": "Width tab face/edge."},
                "distance": {"type": "number", "exclusiveMinimum": 0},
                "angle_deg": {"type": "number"},
                "pitch": {"type": "number", "exclusiveMinimum": 0},
                "ratio_num": {"type": "integer", "exclusiveMinimum": 0},
                "ratio_den": {"type": "integer", "exclusiveMinimum": 0},
                "align": {"type": "string", "enum": _ALIGN_ENUM, "description": _ALIGN_DESC},
                "unit": {"type": "string", "enum": _UNIT_ENUM, "description": _UNIT_DESC},
            },
            ["type", "entity1", "entity2"],
        ),
        handler=mate,
        mutating=True,
    ),
    ToolSpec(
        name="replace_component",
        toolset="assembly",
        description="Replace instance with another .sldprt/.sldasm; name becomes <stem>-N.",
        input_schema=make_schema(
            {
                "component": {"type": "string"},
                "path": {"type": "string"},
                "config": {"type": "string"},
            },
            ["component", "path"],
        ),
        handler=replace_component,
        mutating=True,
        timeout_class="slow",
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
            "pairs[].volume is in call unit with pairs[].volume_unit (e.g. mm3); "
            "backend volume_m3 unchanged. AABB fallback; live uses InterferenceDetectionManager."
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
                "unit": {
                    "type": "string",
                    "enum": _UNIT_ENUM,
                    "description": "Unit for pairs[].volume (default mm → volume_unit=mm3).",
                },
            }
        ),
        handler=check_interference,
        mutating=False,
        timeout_class="slow",
    ),
    ToolSpec(
        name="check_assembly_dof",
        toolset="assembly",
        description=_CHECK_DOF_DESCRIPTION,
        input_schema=make_schema({}),
        handler=check_assembly_dof,
        mutating=False,
        bypass_queue=True,
        timeout_class="fast",
        layer="domain",
    ),
    ToolSpec(
        name="fix_components",
        toolset="assembly",
        description=(
            "Task-layer mate helper: plan/apply distance mates between an anchor "
            "component and others on Front/Top/Right planes to lock the current pose "
            "(does not change mate schema). preview_only=true (default) returns the "
            "plan only; verify_pose rolls back if any instance shifts > tolerance_mm."
        ),
        input_schema=make_schema(
            {
                "components": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 2,
                    "description": "Instance names; first is the pose anchor.",
                },
                "preview_only": {
                    "type": "boolean",
                    "default": True,
                    "description": "If true (default), return plan without creating mates.",
                },
                "verify_pose": {
                    "type": "boolean",
                    "default": True,
                    "description": "Keep only pose-preserving mates (align trials); abort+rollback if final shift > tolerance.",
                },
                "tolerance_mm": {
                    "type": "number",
                    "default": 0.01,
                    "description": "Max allowed origin/bbox shift in mm when verify_pose=true.",
                },
            },
            ["components"],
        ),
        handler=fix_components,
        mutating=True,
        timeout_class="slow",
        layer="task",
    ),
]
