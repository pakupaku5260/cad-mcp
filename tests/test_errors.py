"""Error system contract: code table, unified constructor, side effect classification (W1-1)."""

import pytest
from pydantic import ValidationError

from cadmcp.errors import CATALOG, CadMcpError, ErrorInfo, SideEffect, fail, is_valid_code

# ---- Code catalog ----


def test_catalog_codes_are_screaming_snake():
    for code in CATALOG:
        assert is_valid_code(code), f"invalid error code: {code!r}"


def test_catalog_entries_have_descriptions():
    for code, desc in CATALOG.items():
        assert desc.strip(), f"{code} missing description"


# ---- Constructor ----


def test_unknown_code_rejected():
    with pytest.raises(ValueError, match="Unknown error code"):
        CadMcpError("made_up_code", "msg", "hint")


def test_empty_hint_rejected():
    with pytest.raises(ValueError, match="hint"):
        CadMcpError("INVALID_ARGUMENT", "msg", "")


def test_fail_builds_error_with_context():
    err = fail("INVALID_ARGUMENT", "半径必须为正数", "传 radius > 0", radius=-1)
    assert isinstance(err, CadMcpError)
    assert err.code == "INVALID_ARGUMENT"
    assert err.side_effect is SideEffect.NONE
    assert err.context == {"radius": -1}


def test_side_effect_applied_survives_to_info():
    err = fail(
        "COM_CALL_FAILED",
        "调用中途失败，特征可能已建出",
        "先 get_features 核对再决定是否重试",
        side_effect=SideEffect.APPLIED,
        partial={"feature": "Boss-Extrude1"},
    )
    info = err.to_info()
    assert info.side_effect is SideEffect.APPLIED
    assert info.context["partial"]["feature"] == "Boss-Extrude1"
    assert "COM_CALL_FAILED" in str(err)


# ---- ErrorInfo serialization contract ----


def test_hint_is_mandatory():
    with pytest.raises(ValidationError):
        ErrorInfo(code="INVALID_ARGUMENT", message="m", hint="", side_effect=SideEffect.NONE)


def test_code_pattern_enforced():
    with pytest.raises(ValidationError):
        ErrorInfo(code="bad_code", message="m", hint="h", side_effect=SideEffect.NONE)


def test_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        ErrorInfo(
            code="INVALID_ARGUMENT", message="m", hint="h",
            side_effect=SideEffect.NONE, sneaky=1,
        )


def test_valid_info_roundtrip():
    info = ErrorInfo(
        code="REF_AMBIGUOUS", message="3 个面满足条件",
        hint="补充法向或面积条件缩小范围",
        side_effect=SideEffect.NONE, context={"candidates": [1, 2, 3]},
    )
    assert ErrorInfo.model_validate_json(info.model_dump_json()) == info
