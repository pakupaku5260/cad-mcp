"""Fake backend · query domain（S8e-3）。

S8e-3: 18 methods (geometry summary / mass props / fingerprint / feature list + dimension register/refresh
       + equation eval/apply + dimension query/set).

Dependencies (self, MRO):
- `_enter` / `_require_doc` / `_doc` / `_part_library` / `_assembly_library`（FakeBackend）
- `_material_entities` (FakeSelectionMixin; on FakeBackend until S8e-4)
- `_sketch_bbox3d` (FakeLoftMixin; on FakeBackend until S8e-9)
- `_profile_of` / `_apply_extrude_geom`（FakeExtrudeMixin，S8e-1）

Imports:
- `cadmcp.backend.protocol.geometry_engine`（extrude_z_range_m）
- `cadmcp.backend.protocol.models`（DimensionRef / EquationRef / FeatureInfo /
  FingerprintSI / MassPropsSI）
- `cadmcp.backend.protocol.parsers`（equation_lhs_ok / validate_equation_rhs）
- `cadmcp.errors`（fail）
- `._state`（_Doc / DENSITY_KG_M3）
"""
from __future__ import annotations

import ast
import math
import re
from pathlib import Path

from cadmcp.backend.protocol.geometry_engine import extrude_z_range_m
from cadmcp.backend.protocol.models import (
    DimensionRef,
    EquationRef,
    FeatureInfo,
    FingerprintSI,
    MassPropsSI,
)
from cadmcp.backend.protocol.parsers import equation_lhs_ok
from cadmcp.backend.protocol.validators import validate_equation_rhs
from cadmcp.errors import fail

from ._state import DENSITY_KG_M3, _Doc, _Sketch


class FakeQueryMixin:
    """query domain (S8e-3: 18 methods)."""

    def _init_state(self) -> None:
        pass  # State owned by FakeBackend._init_state

    # ---------- Geometry / mass / fingerprint / features ----------

    def _geom(self) -> dict:
        """Resolve geometry summary: volume/area/centroid/bbox/face-edge counts.

        Cut features sign=-1 (subtract volume/area, clamp ≥0); bbox/centroid from material only
        features (cuts assumed inside body — canned simplification, see module doc).
        """
        doc = self._require_doc()
        volume = area = 0.0
        faces = edges = 0
        bbox: tuple[float, ...] | None = None
        weighted: list[tuple[float, tuple[float, float, float]]] = []

        def _union_bbox(b: tuple[float, ...]) -> None:
            nonlocal bbox
            bbox = b if bbox is None else (
                min(bbox[0], b[0]), min(bbox[1], b[1]), min(bbox[2], b[2]),
                max(bbox[3], b[3]), max(bbox[4], b[4]), max(bbox[5], b[5]),
            )

        if doc.doc_type == "assembly":
            for name, raw_path in doc.components.items():
                box = doc.component_bbox.get(name)
                if box is not None:
                    _union_bbox(tuple(box))
                stored = self._part_library.get(str(Path(raw_path).resolve()))
                if stored is None or len(stored) < 8:
                    continue
                volume += float(stored[4])
                area += float(stored[5])
                faces += int(stored[6])
                edges += int(stored[7])

        # Real GetPartBox includes sketch entities before solid (probed:
        # path+profile ended sketch bbox is sweep envelope); fake counts unconsumed sketches too,
        # so sketch absorbed by feature does not fake bbox change.
        sketches = [*doc.ended_sketches]
        if doc.open_sketch is not None:
            sketches.append(doc.open_sketch)
        for sk in sketches:
            b = self._sketch_bbox3d(sk)
            if b is not None:
                _union_bbox(b)

        for f in doc.features:
            # Curve features (helix) no volume but expand bbox — matches real delta
            if "vol" not in f:
                if "bbox3d" in f:
                    _union_bbox(f["bbox3d"])
                continue
            sign = f["sign"]
            volume += sign * f["vol"]
            area += sign * f["surf"]
            faces += f["faces"]
            edges += f["edges"]
            if sign > 0:
                _union_bbox(f["bbox3d"])
                weighted.append((f["vol"], f["com"]))
        volume = max(volume, 0.0)  # Over-cut clamped to 0 (canned conservative)
        area = max(area, 0.0)
        if weighted:
            total = sum(v for v, _ in weighted) or 1.0
            com = tuple(sum(v * c[i] for v, c in weighted) / total for i in range(3))
        else:
            com = (0.0, 0.0, 0.0)
        return {
            "volume": volume, "area": area, "mass": volume * DENSITY_KG_M3,
            "com": com, "faces": faces, "edges": edges,
            "bbox": bbox or (0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        }

    def mass_properties(self) -> MassPropsSI:
        self._enter("mass_properties")
        g = self._geom()
        return MassPropsSI(
            volume_m3=g["volume"], surface_area_m2=g["area"], mass_kg=g["mass"],
            center_of_mass_m=g["com"],
        )

    def fingerprint(self) -> FingerprintSI:
        self._enter("fingerprint")
        g = self._geom()
        return FingerprintSI(
            volume_m3=g["volume"], surface_area_m2=g["area"], mass_kg=g["mass"],
            face_count=g["faces"], edge_count=g["edges"], bbox_m=g["bbox"],
        )

    def list_features(self) -> list[FeatureInfo]:
        self._enter("list_features")
        doc = self._require_doc()
        return [FeatureInfo(name=f["name"], kind=f["kind"]) for f in doc.features]

    def _require_part(self, hint: str) -> _Doc:
        doc = self._require_doc()
        if doc.doc_type != "part":
            raise fail("INVALID_ARGUMENT", "Active document is not a part", hint)
        return doc

    # ---------- Dimension register / refresh ----------

    @staticmethod
    def _put_length_dim(doc: _Doc, name: str, value_m: float, feat: dict, key: str) -> None:
        doc.dimensions[name] = {
            "value": float(value_m),
            "kind": "length",
            "owner": feat["name"],
            "feature": feat,
            "key": key,
        }

    @staticmethod
    def _put_angle_dim(doc: _Doc, name: str, value_rad: float, feat: dict, key: str) -> None:
        doc.dimensions[name] = {
            "value": float(value_rad),
            "kind": "angle",
            "owner": feat["name"],
            "feature": feat,
            "key": key,
        }

    def _put_sketch_dim(self, sk, entity: dict, value_m: float) -> None:
        doc = self._doc
        if doc is None:
            return
        owner = sk.name or "Sketch"
        n = 1
        while f"D{n}@{owner}" in doc.dimensions:
            n += 1
        doc.dimensions[f"D{n}@{owner}"] = {
            "value": float(value_m),
            "kind": "length",
            "owner": owner,
            "sketch": sk,
            "entity": entity,
        }

    def _refresh_from_sketch(self, feat: dict) -> None:
        sk = feat.get("source_sketch")
        if not isinstance(sk, _Sketch):
            return
        prof = self._profile_of(sk)
        feat["area"] = prof["area"]
        feat["perimeter"] = prof["perimeter"]
        feat["bbox2d"] = prof["bbox2d"]

    def _refresh_revolve(self, feat: dict) -> None:
        angle = float(feat.get("angle") or 0.0)
        r_c = float(feat.get("r_c") or 0.0)
        full = angle >= math.tau - 1e-9
        feat["vol"] = feat["area"] * angle * r_c
        feat["surf"] = feat["perimeter"] * angle * r_c + (0.0 if full else 2 * feat["area"])
        feat["faces"] = 3 if full else 6
        feat["edges"] = 2 if full else 8

    def _refresh_extrude(self, feat: dict) -> None:
        z0, z1 = extrude_z_range_m(
            float(feat["depth"]),
            str(feat.get("direction") or "blind"),
            feat.get("depth2"),
            bool(feat.get("reverse")),
        )
        self._apply_extrude_geom(feat, z0, z1)

    # ---------- Equations ----------

    def _apply_dim_record(self, rec: dict, value_si: float) -> None:
        rec["value"] = float(value_si)
        feat = rec.get("feature")
        key = rec.get("key")
        if rec.get("kind") == "angle" and isinstance(feat, dict) and key:
            feat[key] = float(value_si)
            self._refresh_from_sketch(feat)
            self._refresh_revolve(feat)
            return
        entity = rec.get("entity")
        if isinstance(entity, dict):
            if entity.get("kind") == "circle":
                entity["r"] = float(value_si) / 2.0
            elif entity.get("kind") == "line":
                dx, dy = entity["x1"] - entity["x0"], entity["y1"] - entity["y0"]
                length = math.hypot(dx, dy)
                if length > 0:
                    scale = float(value_si) / length
                    entity["x1"] = entity["x0"] + dx * scale
                    entity["y1"] = entity["y0"] + dy * scale
            sk = rec.get("sketch")
            if isinstance(sk, _Sketch) and self._doc is not None:
                for f in self._doc.features:
                    if f.get("source_sketch") is sk:
                        self._refresh_from_sketch(f)
                        if f.get("kind") in {"extrude", "extrude_cut"}:
                            self._refresh_extrude(f)
                        elif f.get("kind") == "revolve":
                            self._refresh_revolve(f)
            return
        if isinstance(feat, dict) and key:
            feat[key] = float(value_si)
            if feat.get("kind") in {"extrude", "extrude_cut"}:
                self._refresh_extrude(feat)

    def _known_equation_names(self, doc: _Doc) -> set[str]:
        names = set(doc.dimensions)
        names.update(eq["name"] for eq in doc.equations)
        return names

    def _eval_equation_mm(self, rhs: str, env_mm: dict[str, float]) -> float:
        s = rhs.strip()
        for name, val in sorted(env_mm.items(), key=lambda kv: len(kv[0]), reverse=True):
            s = s.replace(f'"{name}"', f"({val})")
            if "@" not in name:
                s = re.sub(rf"\b{re.escape(name)}\b", f"({val})", s, flags=re.IGNORECASE)
        tree = ast.parse(s, mode="eval")

        def _eval(node: ast.AST) -> float:
            if isinstance(node, ast.Expression):
                return _eval(node.body)
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                return float(node.value)
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                v = _eval(node.operand)
                return v if isinstance(node.op, ast.UAdd) else -v
            if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
                a, b = _eval(node.left), _eval(node.right)
                if isinstance(node.op, ast.Add):
                    return a + b
                if isinstance(node.op, ast.Sub):
                    return a - b
                if isinstance(node.op, ast.Mult):
                    return a * b
                if abs(b) < 1e-18:
                    raise fail("INVALID_ARGUMENT", "Equation divides by zero", "Check the right-hand expression")
                return a / b
            raise fail("INVALID_ARGUMENT", "Equation right-hand side cannot be evaluated", "Only numbers and + - * / are allowed")

        return float(_eval(tree))

    def _apply_equations(self, doc: _Doc) -> None:
        env_mm: dict[str, float] = {}
        for name, rec in doc.dimensions.items():
            if rec.get("kind") == "angle":
                env_mm[name] = math.degrees(float(rec["value"]))
            else:
                env_mm[name] = float(rec["value"]) * 1000.0
        for eq in doc.equations:
            env_mm.setdefault(eq["name"], 0.0)
        for eq in doc.equations:
            value_mm = self._eval_equation_mm(eq["expression"], env_mm)
            env_mm[eq["name"]] = value_mm
            rec = doc.dimensions.get(eq["name"])
            if rec is None:
                continue
            if rec.get("kind") == "angle":
                self._apply_dim_record(rec, math.radians(value_mm))
            else:
                self._apply_dim_record(rec, value_mm / 1000.0)

    def list_equations(self) -> list[EquationRef]:
        self._enter("list_equations")
        doc = self._require_part("Use a part document to list equations")
        return [EquationRef(name=eq["name"], expression=eq["expression"]) for eq in doc.equations]

    def set_equation(self, name: str, expression: str) -> EquationRef:
        self._enter("set_equation", name=name, expression=expression)
        doc = self._require_part("Use a part document to write equations")
        raw_name = str(name).strip()
        rhs = str(expression).strip()
        if not equation_lhs_ok(raw_name):
            raise fail(
                "INVALID_ARGUMENT",
                f"Invalid equation name: {raw_name!r}",
                "Global variables start with a letter; dimensions use short names from list_dimensions",
            )
        known = self._known_equation_names(doc) | {raw_name}
        if "@" in raw_name and raw_name not in doc.dimensions:
            raise fail(
                "FEATURE_NOT_FOUND",
                f"Dimension not found: {raw_name!r}",
                "Use list_dimensions for short names",
                name=raw_name,
            )
        validate_equation_rhs(rhs, known)
        replaced = False
        for eq in doc.equations:
            if eq["name"] == raw_name:
                eq["expression"] = rhs
                replaced = True
                break
        if not replaced:
            doc.equations.append({"name": raw_name, "expression": rhs})
        self._apply_equations(doc)
        doc.modified = True
        return EquationRef(name=raw_name, expression=rhs)

    # ---------- Dimension query / set ----------

    def list_dimensions(self) -> list[DimensionRef]:
        self._enter("list_dimensions")
        doc = self._require_part("Use a part document to list dimensions")
        return [
            DimensionRef(name=n, value_si=float(rec["value"]), kind=str(rec.get("kind") or "length"))
            for n, rec in doc.dimensions.items()
        ]

    def set_dimension(self, name: str, value_si: float) -> DimensionRef:
        self._enter("set_dimension", name=name, value=value_si)
        doc = self._require_part("Use a part document to set dimensions")
        rec = doc.dimensions.get(name)
        if rec is None:
            raise fail(
                "FEATURE_NOT_FOUND",
                f"Dimension not found: {name!r}",
                "Use list_dimensions for short names, e.g. D1@Boss-Extrude1",
                name=name,
            )
        kind = str(rec.get("kind") or "length")
        if kind == "angle":
            if not 0.0 < value_si <= math.tau + 1e-9:
                raise fail("INVALID_ARGUMENT", "Angle must be in (0, 360] degrees", "Pass value in degrees")
        elif value_si <= 0:
            raise fail("INVALID_ARGUMENT", "Dimension value must be positive", "Pass value > 0")
        self._apply_dim_record(rec, float(value_si))
        doc.modified = True
        return DimensionRef(name=name, value_si=float(value_si), kind=kind)
        