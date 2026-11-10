"""Consistency sequence registry, grouped by modeling domain."""

from __future__ import annotations

from cadmcp.consistency._types import SequenceStep
from cadmcp.consistency.sequences.assembly import SEQUENCES as ASSEMBLY_SEQUENCES
from cadmcp.consistency.sequences.drawing import SEQUENCES as DRAWING_SEQUENCES
from cadmcp.consistency.sequences.errors import SEQUENCES as ERROR_SEQUENCES
from cadmcp.consistency.sequences.features import SEQUENCES as FEATURE_SEQUENCES
from cadmcp.consistency.sequences.part_advanced import (
    SEQUENCES as PART_ADVANCED_SEQUENCES,
)
from cadmcp.consistency.sequences.part_basic import SEQUENCES as PART_BASIC_SEQUENCES
from cadmcp.consistency.sequences.reference import SEQUENCES as REFERENCE_SEQUENCES
from cadmcp.consistency.sequences.sheetmetal import SEQUENCES as SHEETMETAL_SEQUENCES
from cadmcp.consistency.sequences.sketch import SEQUENCES as SKETCH_SEQUENCES


def _merge(*parts: dict[str, list[SequenceStep]]) -> dict[str, list[SequenceStep]]:
    merged: dict[str, list[SequenceStep]] = {}
    for part in parts:
        duplicates = set(merged) & set(part)
        if duplicates:
            raise RuntimeError(f"Duplicate consistency sequence ids: {sorted(duplicates)}")
        merged.update(part)
    return merged


SEQUENCES = _merge(
    PART_BASIC_SEQUENCES,
    PART_ADVANCED_SEQUENCES,
    SKETCH_SEQUENCES,
    FEATURE_SEQUENCES,
    SHEETMETAL_SEQUENCES,
    ASSEMBLY_SEQUENCES,
    REFERENCE_SEQUENCES,
    DRAWING_SEQUENCES,
    ERROR_SEQUENCES,
)

__all__ = ["SEQUENCES"]
