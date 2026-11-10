"""Single unit entry point: conversion correctness and error paths (W1-2)."""

import math

import pytest

from cadmcp.errors import CadMcpError
from cadmcp.units import METERS_PER_UNIT, SUPPORTED_UNITS, UnitContext


@pytest.fixture()
def ctx() -> UnitContext:
    return UnitContext()  # default mm


# ---- conversion correctness ----


def test_default_unit_is_mm_roundtrip(ctx):
    assert ctx.to_m(50) == pytest.approx(0.05)
    assert ctx.from_m(0.05) == pytest.approx(50.0)


def test_all_supported_units_roundtrip(ctx):
    for unit in SUPPORTED_UNITS:
        v = 12.5
        assert ctx.from_m(ctx.to_m(v, unit), unit) == pytest.approx(v)


def test_factors_table_consistency():
    assert METERS_PER_UNIT["mm"] == 1e-3
    assert METERS_PER_UNIT["in"] == 0.0254
    assert METERS_PER_UNIT["ft"] == 0.3048


def test_golden_volume_conversion(ctx):
    """50mm cube = 1.25e-4 m³ → 125000 mm³ (M0 golden-value chain)."""
    assert ctx.volume_from_m3(1.25e-4) == pytest.approx(125000.0)
    assert ctx.area_from_m2(6 * 0.05 * 0.05) == pytest.approx(15000.0)


def test_area_volume_scale_with_length_factor(ctx):
    assert ctx.volume_to_m3(1.0, "cm") == pytest.approx(1e-6)
    assert ctx.area_to_m2(1.0, "cm") == pytest.approx(1e-4)


def test_tuples(ctx):
    assert ctx.tuple_from_m((0.05, -0.025, 0.0)) == (50.0, -25.0, 0.0)
    assert ctx.tuple_to_m((10.0,), "cm") == (0.1,)


def test_parse_length(ctx):
    assert ctx.parse_length("12.5") == pytest.approx(0.0125)
    assert ctx.parse_length("12.5mm") == pytest.approx(0.0125)
    assert ctx.parse_length("1in") == pytest.approx(0.0254)
    assert ctx.parse_length("-3cm") == pytest.approx(-0.03)


# ---- error paths ----


def test_unsupported_unit(ctx):
    with pytest.raises(CadMcpError) as ei:
        ctx.to_m(1, "furlong")
    assert ei.value.code == "UNIT_UNSUPPORTED"
    assert "mm" in ei.value.hint  # hint lists legal values


def test_constructor_rejects_bad_default():
    with pytest.raises(CadMcpError) as ei:
        UnitContext("inch")
    assert ei.value.code == "UNIT_UNSUPPORTED"


def test_non_numeric_rejected(ctx):
    with pytest.raises(CadMcpError) as ei:
        ctx.to_m("abc")  # type: ignore[arg-type]
    assert ei.value.code == "UNIT_PARSE_FAILED"


def test_nan_inf_rejected(ctx):
    for bad in (math.nan, math.inf):
        with pytest.raises(CadMcpError) as ei:
            ctx.to_m(bad)
        assert ei.value.code == "UNIT_PARSE_FAILED"


def test_unknown_unit_suffix_rejected(ctx):
    """Suffix present but not a legal unit → UNIT_UNSUPPORTED (hint lists legal units)."""
    with pytest.raises(CadMcpError) as ei:
        ctx.parse_length("12.5 smoot")
    assert ei.value.code == "UNIT_UNSUPPORTED"
    assert "mm" in ei.value.hint


def test_unparseable_string_rejected(ctx):
    with pytest.raises(CadMcpError) as ei:
        ctx.parse_length("abc")
    assert ei.value.code == "UNIT_PARSE_FAILED"
    assert "12.5mm" in ei.value.hint
