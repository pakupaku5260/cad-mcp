"""Fake vs real consistency (v4 §17.6): same op sequence vs golden structure (CADMCP_REAL_SW=1)."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

import pytest

from cadmcp.backend.fake.backend import FakeBackend
from cadmcp.backend.protocol.protocol import CADBackend
from cadmcp.consistency import (
    SEQUENCES,
    diff_fingerprints,
    run_sequence,
    structural_fingerprint,
)
from cadmcp.errors import SideEffect, fail
from cadmcp.result import fail_result, ok_result
from cadmcp.toolsets.core import core_registry

GOLDEN_DIR = Path(__file__).parent / "data" / "consistency"


def _load_golden(name: str) -> dict:
    return json.loads((GOLDEN_DIR / f"{name}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", sorted(SEQUENCES))
def test_fake_matches_golden(name: str, tmp_path: Path):
    results = run_sequence(FakeBackend, SEQUENCES[name], workspace=tmp_path)
    diffs = diff_fingerprints(_load_golden(name), structural_fingerprint(results))
    assert not diffs, f"{name} mismatches golden structure:\n" + "\n".join(diffs)


@pytest.mark.sw
@pytest.mark.parametrize("name", sorted(SEQUENCES))
def test_real_matches_golden(name: str, tmp_path: Path):
    results = run_sequence(_com_factory_or_skip(), SEQUENCES[name], workspace=tmp_path)
    diffs = diff_fingerprints(_load_golden(name), structural_fingerprint(results))
    assert not diffs, f"Real {name} vs golden (fix fake or golden):\n" + "\n".join(diffs)


# def _com_factory_or_skip() -> Callable[[], CADBackend]:
#     try:
#         from cadmcp.backend.solidworks.backend import ComBackend
#     except (ImportError, AttributeError) as exc:
#         pytest.skip(f"com_backend unavailable (Windows + pywin32): {exc}")

#     if not getattr(ComBackend, "MODELING_DOMAIN_READY", False):
#         pytest.skip("com_backend document-only until W6 modeling")

#     def factory() -> CADBackend:
#         backend = ComBackend.attach()
#         # reset pre-sequence state
#         while backend.active_document() is not None:
#             backend.close_document(discard=True)
#         return backend

#     return factory


def _com_factory_or_skip() -> Callable[[], CADBackend]:
    if os.environ.get("CADMCP_REAL_SW") != "1":
        pytest.skip(
            "Real SW tests close all open documents without saving;"
            "Set CADMCP_REAL_SW=1 when OK to proceed"
        )
    try:
        from cadmcp.backend.solidworks.backend import ComBackend
    except (ImportError, AttributeError) as exc:
        pytest.skip(f"com_backend unavailable (Windows + pywin32): {exc}")

    if not getattr(ComBackend, "MODELING_DOMAIN_READY", False):
        pytest.skip("com_backend document-only until W6 modeling")

    def factory() -> CADBackend:
        backend = ComBackend.attach()
        # reset pre-sequence state
        for _ in range(20):
            if backend.active_document() is None:
                return backend
            backend.close_document(discard=True)
        pytest.fail("Could not close all SW documents (20 tries)")

    return factory


def test_diff_reports_structural_mismatch():
    good = structural_fingerprint([("extrude", ok_result({"name": "Boss"}, state_version=1))])
    bad = structural_fingerprint(
        [
            (
                "extrude",
                fail_result(
                    fail("SKETCH_NOT_FOUND", "没有可拉伸的草图", "先 end_sketch"),
                    state_version=1,
                ),
            )
        ]
    )
    diffs = diff_fingerprints(good, bad)
    assert any("ok" in d for d in diffs)
    assert any("error_code" in d for d in diffs)
    assert not diff_fingerprints(good, good)


def test_error_codes_in_sequences_are_catalogued():
    """Golden error codes must be in CATALOG."""
    from cadmcp.errors import CATALOG

    for name in sorted(SEQUENCES):
        for step in _load_golden(name)["steps"]:
            code = step["error_code"]
            if code is not None:
                assert code in CATALOG, f"{name}: golden code {code} not in CATALOG"


def test_sequences_reference_registered_tools():
    registry = core_registry()
    for seq_name, steps in SEQUENCES.items():
        for tool, args in steps:
            assert registry.get(tool) is not None, f"{seq_name}: unregistered tool {tool}"
            assert isinstance(args, dict)


def test_side_effect_levels_only_known_values():
    for name in sorted(SEQUENCES):
        for step in _load_golden(name)["steps"]:
            se = step["error_side_effect"]
            if se is not None:
                assert se in set(SideEffect), f"{name}: unknown side_effect {se}"
