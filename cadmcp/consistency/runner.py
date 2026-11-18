"""Execute a consistency sequence on a fresh Kernel."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from cadmcp.backend.protocol.protocol import CADBackend
from cadmcp.consistency._types import SequenceStep
from cadmcp.consistency.sequences import SEQUENCE_SEEDS
from cadmcp.kernel import Kernel
from cadmcp.result import OpResult
from cadmcp.toolsets.core import core_registry


def run_sequence(
    backend_factory: Callable[[], CADBackend],
    steps: Sequence[SequenceStep],
    *,
    workspace: Path,
    sequence_name: str | None = None,
) -> list[tuple[str, OpResult]]:
    """Run steps on a fresh Kernel (state_version=0); return (tool_name, result) pairs.

    Each call builds a new backend — no shared state across sequences; COM factory reset
    hooks live there (see package docstring).

    F4: when a tx_* tool omits tx_id, inject the last successful tx_begin's tx_id so
    sequences stay declarative.

    F10: when ``sequence_name`` is set and registered in SEQUENCE_SEEDS, seed the
    workspace (e.g. write DesignSpec JSON) before dispatching steps.
    """
    if sequence_name is not None:
        seeder = SEQUENCE_SEEDS.get(sequence_name)
        if seeder is not None:
            seeder(workspace)
    kernel = Kernel(core_registry(), backend_factory(), workspace=workspace)
    out: list[tuple[str, OpResult]] = []
    last_tx_id: str | None = None
    for name, args in steps:
        call_args = dict(args)
        if name in {"tx_status", "tx_commit", "tx_rollback"} and "tx_id" not in call_args:
            if last_tx_id is None:
                raise RuntimeError(f"{name} requires tx_id but no prior tx_begin in sequence")
            call_args["tx_id"] = last_tx_id
        result = kernel.dispatch(name, call_args)
        if name == "tx_begin" and result.ok and isinstance(result.result, dict):
            last_tx_id = str(result.result.get("tx_id") or "") or last_tx_id
        out.append((name, result))
    return out
