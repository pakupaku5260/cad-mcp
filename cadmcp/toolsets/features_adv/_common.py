"""Shared unit helpers for features_adv."""
from __future__ import annotations

from cadmcp.kernel import OpContext
from cadmcp.units import SUPPORTED_UNITS, UnitContext

_UNIT_DESC = "Unit; default mm."
_UNIT_ENUM = sorted(SUPPORTED_UNITS)


def _unit_ctx(ctx: OpContext, unit: str) -> UnitContext:
    return ctx.units if unit == ctx.units.external_unit else UnitContext(unit)
