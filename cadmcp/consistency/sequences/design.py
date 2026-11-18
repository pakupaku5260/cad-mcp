"""F10/F11 DesignSpec sequences (+ workspace seeds for JSON fixtures)."""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from cadmcp.consistency._types import SequenceStep

VALID_PART_SPEC: dict = {
    "schema_version": 1,
    "kind": "part",
    "doc": {"title": "Base plate", "units": "mm"},
    "params": {"thickness": 8.0},
    "features": [
        {
            "name": "base",
            "tool": "extrude",
            "args": {"depth": 8},
            "assert": {"ok": True},
        },
        {
            "name": "holes",
            "tool": "hole_wizard",
            "args": {"diameter": 6.0},
            "depends_on": ["base"],
        },
    ],
    "checkpoints": ["base"],
    "verify": {"groups": ["geometry", "features"], "thresholds": {}},
    "outputs": [{"kind": "step", "path": "out/base.step"}],
}

# Runnable plate: sketch → extrude with $param (after new_part in the sequence).
RUN_PART_SPEC: dict = {
    "schema_version": 1,
    "kind": "part",
    "doc": {"title": "Run plate", "units": "mm"},
    "params": {"thickness": 10.0},
    "features": [
        {
            "name": "sk",
            "tool": "start_sketch",
            "args": {"plane": "Front Plane"},
            "assert": {"ok": True},
        },
        {
            "name": "rect",
            "tool": "sketch_rectangle",
            "args": {"x1": 0, "y1": 0, "x2": 40, "y2": 20},
            "depends_on": ["sk"],
            "assert": {"ok": True},
        },
        {
            "name": "end",
            "tool": "end_sketch",
            "args": {},
            "depends_on": ["rect"],
            "assert": {"ok": True},
        },
        {
            "name": "boss",
            "tool": "extrude",
            "args": {"depth": {"$param": "thickness"}},
            "depends_on": ["end"],
            "assert": {"ok": True},
        },
    ],
    "checkpoints": ["boss"],
    "verify": {"groups": ["geometry"], "thresholds": {}},
    "outputs": [{"kind": "step", "path": "out/run_plate.step"}],
}

# Resume sequence: checkpoint at end; first run fails on boom (no end before
# extrude is intentional — mid checkpoint then fail); second call resumes.
# Spec used by design_run_resume: capture at "end", first run completes all,
# second call resume_from=end re-runs boss only.
RESUME_PART_SPEC: dict = {
    "schema_version": 1,
    "kind": "part",
    "doc": {"title": "Resume plate", "units": "mm"},
    "params": {"thickness": 12.0},
    "features": [
        {
            "name": "sk",
            "tool": "start_sketch",
            "args": {"plane": "Front Plane"},
            "assert": {"ok": True},
        },
        {
            "name": "rect",
            "tool": "sketch_rectangle",
            "args": {"x1": 0, "y1": 0, "x2": 50, "y2": 25},
            "depends_on": ["sk"],
            "assert": {"ok": True},
        },
        {
            "name": "end",
            "tool": "end_sketch",
            "args": {},
            "depends_on": ["rect"],
            "assert": {"ok": True},
        },
        {
            "name": "boss",
            "tool": "extrude",
            "args": {"depth": {"$param": "thickness"}},
            "depends_on": ["end"],
            "assert": {"ok": True},
        },
    ],
    "checkpoints": ["end"],
    "verify": {"groups": ["geometry"], "thresholds": {}},
    "outputs": [],
}

# Fail-then-resume: mid checkpoint, boom fails (open sketch); resume re-runs boom.
RESUME_FAIL_SPEC: dict = {
    "schema_version": 1,
    "kind": "part",
    "doc": {"title": "Resume fail plate", "units": "mm"},
    "features": [
        {
            "name": "sk",
            "tool": "start_sketch",
            "args": {"plane": "Front Plane"},
            "assert": {"ok": True},
        },
        {
            "name": "mid",
            "tool": "sketch_rectangle",
            "args": {"x1": 0, "y1": 0, "x2": 30, "y2": 15},
            "depends_on": ["sk"],
            "assert": {"ok": True},
        },
        {
            "name": "boom",
            "tool": "extrude",
            "args": {"depth": 5},
            "depends_on": ["mid"],
            "assert": {"ok": True},
        },
    ],
    "checkpoints": ["mid"],
    "verify": {"groups": ["geometry"], "thresholds": {}},
    "outputs": [],
}

# Outputs sequence: step + stl after a successful plate run.
OUTPUTS_PART_SPEC: dict = {
    "schema_version": 1,
    "kind": "part",
    "doc": {"title": "Outputs plate", "units": "mm"},
    "params": {"thickness": 10.0},
    "features": [
        {
            "name": "sk",
            "tool": "start_sketch",
            "args": {"plane": "Front Plane"},
            "assert": {"ok": True},
        },
        {
            "name": "rect",
            "tool": "sketch_rectangle",
            "args": {"x1": 0, "y1": 0, "x2": 40, "y2": 20},
            "depends_on": ["sk"],
            "assert": {"ok": True},
        },
        {
            "name": "end",
            "tool": "end_sketch",
            "args": {},
            "depends_on": ["rect"],
            "assert": {"ok": True},
        },
        {
            "name": "boss",
            "tool": "extrude",
            "args": {"depth": {"$param": "thickness"}},
            "depends_on": ["end"],
            "assert": {"ok": True},
        },
    ],
    "checkpoints": [],
    "verify": {"groups": ["geometry"], "thresholds": {}},
    "outputs": [
        {"kind": "step", "path": "out/outputs_plate.step"},
        {"kind": "stl", "path": "out/outputs_plate.stl"},
    ],
}

SPEC_FILENAME = "valid_part.json"
RUN_SPEC_FILENAME = "run_plate.json"
RESUME_SPEC_FILENAME = "resume_plate.json"
RESUME_FAIL_SPEC_FILENAME = "resume_fail_plate.json"
OUTPUTS_SPEC_FILENAME = "outputs_plate.json"


def seed_design_spec(workspace: Path) -> None:
    """Write the canonical valid DesignSpec into the sequence workspace."""
    path = workspace / SPEC_FILENAME
    path.write_text(
        json.dumps(VALID_PART_SPEC, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def seed_design_run(workspace: Path) -> None:
    path = workspace / RUN_SPEC_FILENAME
    path.write_text(
        json.dumps(RUN_PART_SPEC, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def seed_design_run_resume(workspace: Path) -> None:
    (workspace / RESUME_FAIL_SPEC_FILENAME).write_text(
        json.dumps(RESUME_FAIL_SPEC, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def seed_design_run_outputs(workspace: Path) -> None:
    (workspace / OUTPUTS_SPEC_FILENAME).write_text(
        json.dumps(OUTPUTS_PART_SPEC, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


VARIANT_PART_SPEC: dict = {
    "schema_version": 1,
    "kind": "part",
    "doc": {"title": "Variant plate", "units": "mm"},
    "params": {"thickness": 10.0},
    "variants": {
        "thick": {"thickness": 20.0},
        "thin": {"thickness": 5.0},
    },
    "features": [
        {
            "name": "sk",
            "tool": "start_sketch",
            "args": {"plane": "Front Plane"},
            "assert": {"ok": True},
        },
        {
            "name": "rect",
            "tool": "sketch_rectangle",
            "args": {"x1": 0, "y1": 0, "x2": 40, "y2": 20},
            "depends_on": ["sk"],
            "assert": {"ok": True},
        },
        {
            "name": "end",
            "tool": "end_sketch",
            "args": {},
            "depends_on": ["rect"],
            "assert": {"ok": True},
        },
        {
            "name": "boss",
            "tool": "extrude",
            "args": {"depth": {"$param": "thickness"}},
            "depends_on": ["end"],
            "assert": {"ok": True},
        },
    ],
    "checkpoints": [],
    "verify": {"groups": ["geometry"], "thresholds": {}},
    "outputs": [],
}

VARIANT_SPEC_FILENAME = "variant_plate.json"


def seed_design_variant(workspace: Path) -> None:
    (workspace / VARIANT_SPEC_FILENAME).write_text(
        json.dumps(VARIANT_PART_SPEC, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


SEQUENCES: dict[str, list[SequenceStep]] = {
    # F21: readonly strategy catalog (default = all four).
    "list_part_strategies": [
        ("list_part_strategies", {}),
    ],
    "design_spec": [
        ("design_spec_validate", {"spec_path": SPEC_FILENAME}),
    ],

    "design_run": [
        ("new_part", {}),
        ("design_run", {"spec_path": RUN_SPEC_FILENAME, "stop_on_error": True}),
    ],
    "design_run_resume": [
        ("new_part", {}),
        ("design_run", {"spec_path": RESUME_FAIL_SPEC_FILENAME, "stop_on_error": True}),
        (
            "design_run",
            {
                "spec_path": RESUME_FAIL_SPEC_FILENAME,
                "stop_on_error": True,
                "resume_from": "mid",
            },
        ),
    ],
    "design_run_outputs": [
        ("new_part", {}),
        ("design_run", {"spec_path": OUTPUTS_SPEC_FILENAME, "stop_on_error": True}),
    ],
    "design_variant": [
        ("new_part", {}),
        (
            "design_run",
            {
                "spec_path": VARIANT_SPEC_FILENAME,
                "stop_on_error": True,
                "variant": "thick",
            },
        ),
    ],
}

SEEDS: dict[str, Callable[[Path], None]] = {
    "design_spec": seed_design_spec,
    "design_run": seed_design_run,
    "design_run_resume": seed_design_run_resume,
    "design_run_outputs": seed_design_run_outputs,
    "design_variant": seed_design_variant,
}

__all__ = [
    "OUTPUTS_PART_SPEC",
    "OUTPUTS_SPEC_FILENAME",
    "RESUME_FAIL_SPEC",
    "RESUME_FAIL_SPEC_FILENAME",
    "RESUME_PART_SPEC",
    "RESUME_SPEC_FILENAME",
    "RUN_PART_SPEC",
    "RUN_SPEC_FILENAME",
    "SEEDS",
    "SEQUENCES",
    "SPEC_FILENAME",
    "VALID_PART_SPEC",
    "VARIANT_PART_SPEC",
    "VARIANT_SPEC_FILENAME",
    "seed_design_run",
    "seed_design_run_outputs",
    "seed_design_run_resume",
    "seed_design_spec",
    "seed_design_variant",
]
