"""COM backend · dimensions / equations.

S6-2a: 6 helpers (_resolve_dim_name / _dim_short_name / _logical_dim_name /
       _iter_display_dims / _dimension_from_disp / _dimension_names)
S6-2b: + list_dimensions / set_dimension
S6-2c: + _equation_mgr / _equation_count / _parse_equation_line /
       list_equations / set_equation / _add_equation

Dependencies (self, MRO):
- ``_call`` / ``_map_error`` (STAThreadMixin)
- ``_require_part_doc`` (InfrastructureMixin)
- ``_aliases`` (NamingMixin)
- ``_get`` (_helpers)

imports:
- ``cadmcp.backend.protocol.models`` (DimensionRef / EquationRef)
- ``cadmcp.errors`` (CadMcpError / fail)
- ``._constants`` (_DIM_KIND / _SW_SETVALUE_CURRENT_CFG)
- ``._helpers`` (_get)
"""
from __future__ import annotations

import logging
import math
import re
import traceback
from typing import Any

from cadmcp.backend.protocol.models import DimensionRef, EquationRef
from cadmcp.backend.protocol.parsers import equation_lhs_ok, equation_name_keys
from cadmcp.backend.protocol.validators import validate_equation_rhs
from cadmcp.errors import fail

from ._constants import _DIM_KIND, _SW_SETVALUE_CURRENT_CFG
from ._helpers import _get

log = logging.getLogger(__name__)


class DimensionMixin:
    """Dimensions / equations (S6-2a: 6 helpers)."""

    def _init_state(self) -> None:
        pass  # stateless

    def _resolve_dim_name(self, name: str) -> str:
        raw = str(name).strip()
        if "@" not in raw:
            return raw
        tag, owner = raw.split("@", 1)
        owner = owner.split("@")[0]
        return f"{tag}@{self._aliases.get(owner, owner)}"

    @staticmethod
    def _dim_short_name(dim: Any) -> str:
        full = ""
        for attr in ("GetNameForSelection", "FullName", "Name"):
            try:
                val = getattr(dim, attr)
                if callable(val) and not hasattr(val, "_oleobj_"):
                    val = val()
                full = str(val or "")
            except Exception:
                continue
            if full:
                break
        parts = full.split("@")
        if len(parts) >= 2:
            return f"{parts[0]}@{parts[1]}"
        return full

    def _logical_dim_name(self, short: str) -> str:
        if "@" not in short:
            return short
        tag, owner = short.split("@", 1)
        for logical, real in self._aliases.items():
            if owner == real or owner == logical:
                return f"{tag}@{logical}"
        return short

    def _iter_display_dims(self, feat: Any):
        disp = None
        try:
            disp = feat.GetFirstDisplayDimension()
        except TypeError:
            try:
                disp = feat.GetFirstDisplayDimension
            except Exception:
                disp = None
        except Exception:
            disp = None
        if disp is None:
            try:
                arr = feat.GetDisplayDimensions()
            except Exception:
                arr = None
            for item in arr or ():
                if item is not None:
                    yield item
            return
        while disp is not None:
            yield disp
            nxt = None
            try:
                nxt = feat.GetNextDisplayDimension(disp)
            except Exception:
                try:
                    nxt = _get(feat, "GetNextDisplayDimension", disp)
                except Exception:
                    nxt = None
            disp = nxt

    def _dimension_from_disp(self, disp: Any) -> DimensionRef | None:
        dim = None
        try:
            dim = disp.GetDimension2(0)
        except Exception:
            try:
                dim = _get(disp, "GetDimension")
            except Exception:
                dim = None
        if dim is None:
            return None
        kind = "length"
        try:
            kind = _DIM_KIND.get(int(_get(dim, "GetType")), "length")
        except Exception:
            pass
        try:
            value = float(_get(dim, "SystemValue"))
        except Exception:
            try:
                value = float(dim.SystemValue)
            except Exception:
                return None
        short = self._dim_short_name(dim)
        if not short:
            return None
        return DimensionRef(name=self._logical_dim_name(short), value_si=value, kind=kind)

    def _dimension_names(self, doc: Any) -> set[str]:
        names: set[str] = set()
        feat = _get(doc, "FirstFeature")
        while feat is not None:
            for disp in self._iter_display_dims(feat):
                ref = self._dimension_from_disp(disp)
                if ref is not None:
                    names.add(ref.name)
            feat = _get(feat, "GetNextFeature")
        return names

    def list_dimensions(self) -> list[DimensionRef]:
        def _fn() -> list[DimensionRef]:
            doc = self.sw.ActiveDoc
            self._require_part_doc(doc, "Use a part document to list dimensions")
            out: list[DimensionRef] = []
            seen: set[str] = set()
            feat = _get(doc, "FirstFeature")
            while feat is not None:
                for disp in self._iter_display_dims(feat):
                    ref = self._dimension_from_disp(disp)
                    if ref is None or ref.name in seen:
                        continue
                    seen.add(ref.name)
                    out.append(ref)
                feat = _get(feat, "GetNextFeature")
            return out

        return self._call(_fn)

    def set_dimension(self, name: str, value_si: float) -> DimensionRef:
        def _fn() -> DimensionRef:
            doc = self.sw.ActiveDoc
            self._require_part_doc(doc, "Use a part document to change dimensions")
            if value_si <= 0:
                raise fail("INVALID_ARGUMENT", "Dimension value must be positive", "Pass value > 0")
            resolved = self._resolve_dim_name(name)
            param = None
            last_exc: Exception | None = None
            for cand in (resolved, name):
                try:
                    param = doc.Parameter(cand)
                except Exception as exc:
                    last_exc = exc
                    param = None
                if param is not None:
                    break
            if param is None:
                raise fail(
                    "FEATURE_NOT_FOUND",
                    f"Dimension not found: {name!r}",
                    "Use list_dimensions for short names; localized tree names also work (e.g. D1@Boss-Extrude1)",
                    name=name,
                ) from last_exc
            kind = "length"
            try:
                kind = _DIM_KIND.get(int(_get(param, "GetType")), "length")
            except Exception:
                pass
            if kind == "angle":
                if not 0.0 < float(value_si) <= math.tau + 1e-9:
                    raise fail("INVALID_ARGUMENT", "Angle must be in (0, 360] deg", "Pass value in degrees")
            try:
                param.SystemValue = float(value_si)
            except Exception:
                try:
                    _get(param, "SetSystemValue3", float(value_si), _SW_SETVALUE_CURRENT_CFG, None)
                except Exception as exc:
                    raise self._map_error(exc) from exc
            try:
                _get(doc, "ForceRebuild3", True)
            except Exception:
                log.debug("Rebuild after dimension change failed: %s", traceback.format_exc())
            try:
                after = float(_get(param, "SystemValue"))
            except Exception:
                after = float(value_si)
            return DimensionRef(name=self._logical_dim_name(resolved), value_si=after, kind=kind)

        return self._call(_fn)

    def _equation_mgr(self, doc: Any) -> Any:
        mgr = _get(doc, "GetEquationMgr")
        if mgr is None:
            raise fail("FEATURE_CREATE_FAILED", "Cannot open equation manager", "Confirm the active document is a part")
        return mgr

    @staticmethod
    def _equation_count(mgr: Any) -> int:
        try:
            val = _get(mgr, "GetCount")
            return int(val() if callable(val) and not hasattr(val, "_oleobj_") else val)
        except Exception:
            return 0

    @staticmethod
    def _parse_equation_line(line: str) -> tuple[str, str] | None:
        raw = str(line).strip()
        if "=" not in raw:
            return None
        lhs, _, rhs = raw.partition("=")
        lhs, rhs = lhs.strip().strip('"'), rhs.strip()
        if not lhs:
            return None
        # Global variables may be stored as D@PartName; expose short name D externally
        if "@" in lhs:
            tag, _, owner = lhs.partition("@")
            if tag and not re.match(r"^[A-Z]*\d+$", tag):
                lhs = tag
            else:
                pass
        return lhs, rhs

    def list_equations(self) -> list[EquationRef]:
        def _fn() -> list[EquationRef]:
            doc = self.sw.ActiveDoc
            self._require_part_doc(doc, "Use a part document to list equations")
            mgr = self._equation_mgr(doc)
            out: list[EquationRef] = []
            for i in range(self._equation_count(mgr)):
                try:
                    line = str(mgr.Equation(i) or "")
                except Exception:
                    continue
                parsed = self._parse_equation_line(line)
                if parsed is None:
                    continue
                name, rhs = parsed
                out.append(EquationRef(name=self._logical_dim_name(name), expression=rhs))
            return out

        return self._call(_fn)

    def set_equation(self, name: str, expression: str) -> EquationRef:
        def _fn() -> EquationRef:
            doc = self.sw.ActiveDoc
            self._require_part_doc(doc, "Use a part document to write equations")
            raw_name = str(name).strip()
            rhs = str(expression).strip()
            if not equation_lhs_ok(raw_name):
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Invalid equation name: {raw_name!r}",
                    "Global variables start with a letter; dimensions use list_dimensions short names",
                )
            dim_names = self._dimension_names(doc)
            resolved = self._resolve_dim_name(raw_name) if "@" in raw_name else raw_name
            if "@" in raw_name:
                param = None
                for cand in (resolved, raw_name):
                    try:
                        param = doc.Parameter(cand)
                    except Exception:
                        param = None
                    if param is not None:
                        break
                if param is None:
                    raise fail(
                        "FEATURE_NOT_FOUND",
                        f"Dimension not found: {raw_name!r}",
                        "Use list_dimensions for short names; localized tree names also work",
                        name=raw_name,
                    )
            mgr = self._equation_mgr(doc)
            existing: set[str] = set()
            for i in range(self._equation_count(mgr)):
                try:
                    parsed = self._parse_equation_line(str(mgr.Equation(i) or ""))
                except Exception:
                    parsed = None
                if parsed is not None:
                    existing |= equation_name_keys(parsed[0])
            known: set[str] = set()
            for item in dim_names | existing | {raw_name, resolved}:
                known |= equation_name_keys(item)
            validate_equation_rhs(rhs, known)
            lhs = resolved if "@" in raw_name else raw_name
            rhs_sw = rhs
            if equation_lhs_ok(rhs) and "@" not in rhs and rhs in known:
                rhs_sw = f'"{rhs}"'
            line = f'"{lhs}" = {rhs_sw}'
            replaced = False
            for i in range(self._equation_count(mgr)):
                try:
                    parsed = self._parse_equation_line(str(mgr.Equation(i) or ""))
                except Exception:
                    parsed = None
                if parsed is None:
                    continue
                if parsed[0] in {raw_name, resolved, lhs}:
                    try:
                        mgr.Equation(i, line)
                    except Exception:
                        mgr.Equation(i)  # some versions: Equation index is read-only
                        try:
                            _get(mgr, "Delete", i)
                            self._add_equation(mgr, line)
                        except Exception as exc:
                            raise self._map_error(exc) from exc
                    replaced = True
                    break
            if not replaced:
                self._add_equation(mgr, line)
            try:
                _get(doc, "ForceRebuild3", True)
            except Exception:
                log.debug("Rebuild after equation change failed: %s", traceback.format_exc())
            return EquationRef(name=raw_name, expression=rhs)

        return self._call(_fn)

    def _add_equation(self, mgr: Any, line: str) -> None:
        last: Exception | None = None
        before = self._equation_count(mgr)
        for call in (
            lambda: mgr.Add2(-1, line, True),
            lambda: _get(mgr, "Add2", -1, line, True),
            lambda: mgr.Add3(-1, line, True, True, 1),
            lambda: mgr.Add3(-1, line, True, True, 2),
            lambda: _get(mgr, "Add3", -1, line, True, True, 1),
        ):
            try:
                ret = call()
            except Exception as exc:
                last = exc
                continue
            after = self._equation_count(mgr)
            if after > before:
                return
            if isinstance(ret, int) and ret >= 0:
                return
            last = RuntimeError(f"EquationMgr did not add entry (returned {ret!r})")
        raise fail(
            "FEATURE_CREATE_FAILED",
            "Failed to write equation",
            'Expression must be "Name" = value or reference an existing dimension',
        ) from last
