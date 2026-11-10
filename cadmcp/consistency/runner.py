"""Execute a consistency sequence on a fresh Kernel."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from cadmcp.backend.protocol.protocol import CADBackend
from cadmcp.consistency._types import SequenceStep
from cadmcp.kernel import Kernel
from cadmcp.result import OpResult
from cadmcp.toolsets.core import core_registry


def run_sequence(
    backend_factory: Callable[[], CADBackend],
    steps: Sequence[SequenceStep],
    *,
    workspace: Path,
) -> list[tuple[str, OpResult]]:
    """Run steps on a fresh Kernel (state_version=0); return (tool_name, result) pairs.

    Each call builds a new backend — no shared state across sequences; COM factory reset
    hooks live there (see package docstring).
    """
    kernel = Kernel(core_registry(), backend_factory(), workspace=workspace)
    return [(name, kernel.dispatch(name, args)) for name, args in steps]
