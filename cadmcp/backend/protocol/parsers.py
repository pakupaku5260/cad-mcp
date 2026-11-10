"""Protocol layer · input parsing and normalization."""
from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

from cadmcp.errors import fail

from .constants import (
    _3D_SKETCH_PLANE_KEYS,
    _CLOSEST_DEFAULT_MATES,
    _MATE_REF_HINT,
    DRAWING_VIEW_ALIASES,
    MATE_ALIGNS,
    PLANE_ALIASES,
    SKETCH_RELATION_HINT,
    SKETCH_RELATIONS,
)
from .models import BomRow, MateRef

_EQ_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def mate_entity_to_si(entity: str, to_m) -> str:
    raw = str(entity).strip()
    lower = raw.lower()
    for sep in ("#face:", "#edge:", "#cylinder:", "#plane:", "#cone:", "#circle:"):
        if sep not in lower:
            continue
        cut = lower.index(sep)
        head, rest = raw[:cut], raw[cut + len(sep):]
        if ":" not in rest:
            return raw
        idx_s, coord_s = rest.split(":", 1)
        if not idx_s.isdigit():
            return raw
        parts = [p.strip() for p in coord_s.split(",")]
        if len(parts) != 3:
            raise fail("INVALID_ARGUMENT", f"Invalid mate entity format: {entity!r}", _MATE_REF_HINT, entity=entity)
        try:
            xyz = ",".join(str(to_m(float(p))) for p in parts)
        except ValueError:
            raise fail("INVALID_ARGUMENT", f"Invalid mate entity format: {entity!r}", _MATE_REF_HINT, entity=entity) from None
        return f"{head}{sep}{idx_s}:{xyz}"
    return raw


def drawing_view_key(view: str) -> str:
    key = str(view).strip().lower()
    if key not in DRAWING_VIEW_ALIASES:
        raise fail(
            "INVALID_ARGUMENT",
            f"Unknown drawing view: {view!r}",
            f"view: {', '.join(DRAWING_VIEW_ALIASES)}",
            requested=view,
        )
    return key


def canonical_plane(name: str) -> str | None:
    for canon, aliases in PLANE_ALIASES.items():
        if name == canon or name in aliases:
            return canon
    return None


_INSTANCE_TAIL = re.compile(r".-\d+$")


def component_name_keys(name: str) -> set[str]:
    raw = str(name).strip()
    keys = {raw}
    if "/" in raw:
        parts = [p for p in raw.split("/") if p]
        if len(parts) >= 2:
            keys.add("@".join(reversed(parts)))
    if "@" in raw:
        parts = [p for p in raw.split("@") if p]
        if len(parts) >= 2:
            keys.add("/".join(reversed(parts)))
    return {k for k in keys if k}


def _parse_index_coord(rest: str, entity: str) -> tuple[int, tuple[float, float, float] | None]:
    idx_s, sep, coord_s = rest.partition(":")
    if not idx_s.isdigit():
        raise fail("INVALID_ARGUMENT", f"Invalid mate entity format: {entity!r}", _MATE_REF_HINT, entity=entity)
    idx = int(idx_s)
    if not sep:
        return idx, None
    parts = [p.strip() for p in coord_s.split(",")]
    if len(parts) != 3:
        raise fail("INVALID_ARGUMENT", f"Invalid mate entity format: {entity!r}", _MATE_REF_HINT, entity=entity)
    try:
        return idx, (float(parts[0]), float(parts[1]), float(parts[2]))
    except ValueError:
        raise fail("INVALID_ARGUMENT", f"Invalid mate entity format: {entity!r}", _MATE_REF_HINT, entity=entity) from None


def parse_mate_ref(entity: str) -> MateRef:
    raw = str(entity).strip()
    lower = raw.lower()
    for sep, kind, filter_kind in (
        ("#face:", "face", None),
        ("#edge:", "edge", None),
        ("#cylinder:", "face", "cylinder"),
        ("#plane:", "face", "plane"),
        ("#cone:", "face", "cone"),
        ("#circle:", "edge", "circle"),
    ):
        if sep in lower:
            cut = lower.index(sep)
            comp, rest = raw[:cut].strip(), raw[cut + len(sep):].strip()
            idx, coord = _parse_index_coord(rest, entity)
            if not comp:
                raise fail("INVALID_ARGUMENT", f"Invalid mate entity format: {entity!r}", _MATE_REF_HINT, entity=entity)
            if kind == "face":
                return MateRef(kind="face", component=comp, face_index=idx, coord_m=coord, filter_kind=filter_kind)
            return MateRef(kind="edge", component=comp, edge_index=idx, coord_m=coord, filter_kind=filter_kind)

    parts = [p.strip() for p in raw.split("@")]
    if len(parts) not in (2, 3, 4) or not all(parts):
        raise fail("INVALID_ARGUMENT", f"Invalid mate entity format: {entity!r}", _MATE_REF_HINT, entity=entity)
    plane = canonical_plane(parts[0])
    if plane is None:
        raise fail(
            "INVALID_ARGUMENT",
            f"Mate entity {entity!r} is not a reference plane, component face, or edge",
            _MATE_REF_HINT,
            entity=entity,
        )
    if len(parts) == 2:
        component = parts[1]
    elif len(parts) == 4:
        component = f"{parts[1]}@{parts[2]}"
    elif _INSTANCE_TAIL.search(parts[2]):
        component = f"{parts[1]}@{parts[2]}"
    else:
        component = parts[1]
    return MateRef(kind="plane", component=component, plane=plane)


def parse_mate_pair(entity1: str, entity2: str) -> tuple[MateRef, MateRef]:
    ref1, ref2 = parse_mate_ref(entity1), parse_mate_ref(entity2)
    if ref1.component == ref2.component:
        raise fail(
            "INVALID_ARGUMENT",
            f"Both mate entities belong to the same component {ref1.component!r}",
            "A mate must be created between two different components",
            entity1=entity1,
            entity2=entity2,
        )
    return ref1, ref2


def resolve_mate_align(align: str | None, mate_type: str) -> int:
    if align is None or str(align).strip() == "":
        return MATE_ALIGNS["closest"] if mate_type in _CLOSEST_DEFAULT_MATES else MATE_ALIGNS["aligned"]
    key = str(align).strip().lower()
    hit = MATE_ALIGNS.get(key)
    if hit is None:
        raise fail(
            "INVALID_ARGUMENT",
            f"Unsupported mate alignment: {align!r}",
            "Use aligned / anti_aligned / closest",
            align=align,
        )
    return hit


def resolve_sketch_relation(relation: str) -> tuple[str, int]:
    key = str(relation).strip().lower()
    hit = SKETCH_RELATIONS.get(key)
    if hit is None:
        raise fail(
            "INVALID_ARGUMENT",
            f"Unsupported sketch relation: {relation!r}",
            f"Use {SKETCH_RELATION_HINT}",
            relation=relation,
        )
    return hit


def equation_lhs_ok(name: str) -> bool:
    raw = str(name).strip()
    if not raw or '"' in raw or "=" in raw:
        return False
    if "@" in raw:
        tag, _, owner = raw.partition("@")
        return bool(tag and owner and " " not in tag)
    return bool(_EQ_IDENT.match(raw))


def equation_name_keys(name: str) -> set[str]:
    raw = str(name).strip().strip('"')
    out = {raw}
    if "@" in raw:
        tag, _, owner = raw.partition("@")
        if tag:
            out.add(tag)
        if owner:
            out.add(f"{tag}@{owner}")
    return {k for k in out if k}


def linear_pattern_offset_m(
    dx_m: float | None, dy_m: float | None, dz_m: float | None
) -> tuple[float, float, float] | None:
    vals = (dx_m, dy_m, dz_m)
    if all(v is None for v in vals):
        return None
    nums = tuple(0.0 if v is None else float(v) for v in vals)
    if sum(abs(v) > 1e-12 for v in nums) != 1:
        raise fail(
            "INVALID_ARGUMENT",
            "Linear pattern spacing must lie on exactly one axis",
            "Provide only one non-zero value among dx, dy, dz",
        )
    return nums


def normalize_spline_points(
    points: list[tuple[float, ...]], closed: bool
) -> list[tuple[float, float, float]]:
    """Accept [x,y] or [x,y,z], normalize to (x,y,z); z defaults to 0."""
    if len(points) < 2:
        raise fail(
            "INVALID_ARGUMENT",
            "Spline needs at least 2 points",
            "Pass points=[[x,y],...] or [[x,y,z],...]",
        )
    norm: list[tuple[float, float, float]] = []
    for p in points:
        if len(p) == 2:
            norm.append((float(p[0]), float(p[1]), 0.0))
        elif len(p) == 3:
            norm.append((float(p[0]), float(p[1]), float(p[2])))
        else:
            raise fail(
                "INVALID_ARGUMENT",
                "Each spline point must be [x,y] or [x,y,z]",
                "Every item in points must have 2 or 3 numbers",
            )
    if closed:
        uniq = {(round(x, 12), round(y, 12), round(z, 12)) for x, y, z in norm}
        if len(uniq) < 3:
            raise fail("INVALID_ARGUMENT", "Closed spline needs at least 3 distinct points", "With closed=true, pass 3+ distinct points")
        x0, y0, z0 = norm[0]
        x1, y1, z1 = norm[-1]
        if (x0 - x1) ** 2 + (y0 - y1) ** 2 + (z0 - z1) ** 2 > 1e-24:
            norm = [*norm, norm[0]]
    return norm


def is_3d_sketch_plane(plane: str) -> bool:
    key = "".join(plane.strip().lower().split()).replace("_", "").replace("-", "")
    return key in _3D_SKETCH_PLANE_KEYS


def mate_need_hint(mate_type: str, kinds: list[str] | None = None) -> str:
    from .constants import _MATE_ENTITY_NEED
    need = _MATE_ENTITY_NEED.get(mate_type, "Mate type does not match selected entities")
    if kinds:
        return f"{need}; got {', '.join(kinds)}"
    return need


def interference_component_pairs(
    names: Sequence[str],
    component1: str | None,
    component2: str | None,
) -> list[tuple[str, str]]:
    have = list(names)
    if component1 is not None and component1 not in have:
        raise fail("INVALID_ARGUMENT", f"Component not found: {component1!r}", "Instance name comes from insert_component return value", component=component1)
    if component2 is not None and component2 not in have:
        raise fail("INVALID_ARGUMENT", f"Component not found: {component2!r}", "Instance name comes from insert_component return value", component=component2)
    if component1 is not None and component2 is not None:
        if component1 == component2:
            raise fail("INVALID_ARGUMENT", "Interference check needs two different components", "component1 and component2 must differ")
        a, b = sorted((component1, component2))
        return [(a, b)]
    if component1 is not None:
        others = [n for n in have if n != component1]
        return [tuple(sorted((component1, n))) for n in others]
    if component2 is not None:
        others = [n for n in have if n != component2]
        return [tuple(sorted((component2, n))) for n in others]
    out: list[tuple[str, str]] = []
    ordered = sorted(have)
    for i, a in enumerate(ordered):
        for b in ordered[i + 1:]:
            out.append((a, b))
    return out


def rollup_bom_rows(
    entries: Sequence[tuple[str, str, str, str]],
) -> list[BomRow]:
    groups: dict[tuple[str, str, str], BomRow] = {}
    order: list[tuple[str, str, str]] = []
    for name, path, material, config in entries:
        stem = Path(path).stem if path else name.rsplit("-", 1)[0]
        key = (stem, config, material)
        if key not in groups:
            groups[key] = BomRow(
                item=len(order) + 1, part_number=stem, qty=0,
                material=material, configuration=config,
                path=path or None, components=[],
            )
            order.append(key)
        row = groups[key]
        row.qty += 1
        row.components.append(name)
    return [groups[k] for k in order]
