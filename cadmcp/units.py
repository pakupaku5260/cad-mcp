"""Single entry point for unit conversion (v4 §12 W1-2).

Rules:
- SolidWorks COM uses meters (length), m², m³, kg internally; default external unit is mm.
- Conversion factors live only in METERS_PER_UNIT here; literal factors like 0.001/1e6/1e9
  elsewhere fail tests/test_static_scan.py (allow with `# unit-allow: reason` on that line).
- Tool args → COM must go through UnitContext (binder), not ad-hoc math.
"""
from __future__ import annotations

import math
import re
from collections.abc import Sequence

from cadmcp.errors import fail

SUPPORTED_UNITS: frozenset[str] = frozenset({"mm", "cm", "m", "in", "ft"})

# Sole source of conversion factors (meters per unit). No other module may hardcode these.
METERS_PER_UNIT: dict[str, float] = {
    "mm": 1e-3,
    "cm": 1e-2,
    "m": 1.0,
    "in": 0.0254,
    "ft": 0.3048,
}

_NUM_WITH_UNIT_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*([A-Za-z]+)?\s*$")


class UnitContext:
    """Binder: one external unit (default mm) for inbound/outbound of a single call."""

    __slots__ = ("external_unit",)

    def __init__(self, external_unit: str = "mm") -> None:
        if external_unit not in SUPPORTED_UNITS:
            raise fail(
                "UNIT_UNSUPPORTED",
                f"Unsupported unit {external_unit!r}",
                f"Use one of: {', '.join(sorted(SUPPORTED_UNITS))}",
                requested=external_unit,
            )
        self.external_unit = external_unit

    # ---- factors only from table in this class ----
    def _factor(self, unit: str | None) -> float:
        u = unit or self.external_unit
        if u not in SUPPORTED_UNITS:
            raise fail(
                "UNIT_UNSUPPORTED",
                f"Unsupported unit {u!r}",
                f"Use one of: {', '.join(sorted(SUPPORTED_UNITS))}",
                requested=u,
            )
        return METERS_PER_UNIT[u]

    @staticmethod
    def _finite(value: float, what: str) -> float:
        try:
            v = float(value)
        except (TypeError, ValueError) as exc:
            raise fail(
                "UNIT_PARSE_FAILED",
                f"{what} is not a number: {value!r}",
                "Pass a numeric value, e.g. 12.5 (unit from unit field or default mm)",
                value=repr(value),
            ) from exc
        if not math.isfinite(v):
            raise fail(
                "UNIT_PARSE_FAILED",
                f"{what} is not finite: {value!r}",
                "Check upstream math; NaN/Infinity cannot reach COM",
                value=repr(value),
            )
        return v

    # ---- length ----
    def to_m(self, value: float, unit: str | None = None) -> float:
        """External unit → meters (last step before COM)."""
        return self._finite(value, "length") * self._factor(unit)

    def from_m(self, value_m: float, unit: str | None = None) -> float:
        """Meters → external unit (first step after COM)."""
        return self._finite(value_m, "length") / self._factor(unit)

    # ---- area / volume (squared/cubed factors, still from table only) ----
    def area_to_m2(self, value: float, unit: str | None = None) -> float:
        return self._finite(value, "area") * self._factor(unit) ** 2

    def area_from_m2(self, value_m2: float, unit: str | None = None) -> float:
        return self._finite(value_m2, "area") / self._factor(unit) ** 2

    def volume_to_m3(self, value: float, unit: str | None = None) -> float:
        return self._finite(value, "volume") * self._factor(unit) ** 3

    def volume_from_m3(self, value_m3: float, unit: str | None = None) -> float:
        return self._finite(value_m3, "volume") / self._factor(unit) ** 3

    # ---- coordinate tuples (bbox, points) ----
    def tuple_from_m(
        self, values: Sequence[float], unit: str | None = None
    ) -> tuple[float, ...]:
        return tuple(self.from_m(v, unit) for v in values)

    def tuple_to_m(
        self, values: Sequence[float], unit: str | None = None
    ) -> tuple[float, ...]:
        return tuple(self.to_m(v, unit) for v in values)

    # ---- string parse (spec layer and "12.5mm" style input) ----
    def parse_length(self, text: str) -> float:
        """'12.5' / '12.5mm' / '-3in' → meters; suffix overrides default unit when present."""
        if not isinstance(text, str):
            raise fail(
                "UNIT_PARSE_FAILED",
                f"Expected string length, got {type(text).__name__}",
                "Pass a string like '12.5' or '12.5mm'",
                value=repr(text),
            )
        m = _NUM_WITH_UNIT_RE.match(text)
        if not m:
            raise fail(
                "UNIT_PARSE_FAILED",
                f"Cannot parse length {text!r}",
                "Format: number plus optional unit, e.g. '12.5', '12.5mm', '-3in'",
                value=text,
            )
        value, suffix = float(m.group(1)), m.group(2)
        return self.to_m(value, suffix.lower() if suffix else None)
