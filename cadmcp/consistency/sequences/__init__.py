"""Consistency sequence registry, grouped by modeling domain."""

from __future__ import annotations

from cadmcp.consistency._types import SequenceStep
from cadmcp.consistency.sequences.assembly import SEQUENCES as ASSEMBLY_SEQUENCES
from cadmcp.consistency.sequences.design import SEEDS as DESIGN_SEEDS
from cadmcp.consistency.sequences.design import SEQUENCES as DESIGN_SEQUENCES
from cadmcp.consistency.sequences.diagnostics import (
    SEQUENCES as DIAGNOSTICS_SEQUENCES,
)
from cadmcp.consistency.sequences.drawing import SEEDS as DRAWING_SEEDS
from cadmcp.consistency.sequences.drawing import SEQUENCES as DRAWING_SEQUENCES
from cadmcp.consistency.sequences.errors import SEQUENCES as ERROR_SEQUENCES
from cadmcp.consistency.sequences.features import SEQUENCES as FEATURE_SEQUENCES
from cadmcp.consistency.sequences.part_advanced import (
    SEQUENCES as PART_ADVANCED_SEQUENCES,
)
from cadmcp.consistency.sequences.part_basic import SEQUENCES as PART_BASIC_SEQUENCES
from cadmcp.consistency.sequences.reference import SEQUENCES as REFERENCE_SEQUENCES
from cadmcp.consistency.sequences.rules import SEQUENCES as RULES_SEQUENCES
from cadmcp.consistency.sequences.sheetmetal import SEQUENCES as SHEETMETAL_SEQUENCES
from cadmcp.consistency.sequences.sketch import SEQUENCES as SKETCH_SEQUENCES
from cadmcp.consistency.sequences.task import SEEDS as TASK_SEEDS
from cadmcp.consistency.sequences.task import SEQUENCES as TASK_SEQUENCES
from cadmcp.consistency.sequences.transaction import (
    SEQUENCES as TRANSACTION_SEQUENCES,
)
from cadmcp.consistency.sequences.verification import (
    SEQUENCES as VERIFICATION_SEQUENCES,
)

# Optional workspace seeders keyed by sequence name (e.g. write DesignSpec JSON).
SEQUENCE_SEEDS = {**DESIGN_SEEDS, **TASK_SEEDS, **DRAWING_SEEDS}


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
    VERIFICATION_SEQUENCES,
    TRANSACTION_SEQUENCES,
    DESIGN_SEQUENCES,
    TASK_SEQUENCES,
    RULES_SEQUENCES,
    DIAGNOSTICS_SEQUENCES,
)

__all__ = ["SEQUENCE_SEEDS", "SEQUENCES"]
