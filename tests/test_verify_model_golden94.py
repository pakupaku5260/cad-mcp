"""F2: verify_model on Fake end-states of consistency sequences (no false fails).

Scope: geometry/features/mass_bbox only. Assembly interference and drawing incompleteness
are intentional in several sequences and are covered by dedicated verify_model unit tests,
not this regression sweep.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from cadmcp.backend.fake.backend import FakeBackend
from cadmcp.consistency import SEQUENCES
from cadmcp.kernel import Kernel
from cadmcp.toolsets.core import core_registry

_INTENTIONAL = frozenset(
    {"verify_empty_body", "verify_hole_position", "verify_healthy_part"}
)
_SOLID_GROUPS = ["geometry", "features", "mass_bbox"]


def test_verify_model_on_consistency_end_states():
    """Replay each sequence without trailing close_document, then verify solid groups.

    Intentional verify_* counterexample sequences are excluded.
    Allowed failure on leftover empty shells: VERIFY_EMPTY_BODY only.
    Drawing-only end states → skipped_groups / unverified (no solid groups) is OK.
    """
    summary: list[dict] = []
    for name, steps in sorted(SEQUENCES.items()):
        if name in _INTENTIONAL:
            summary.append({"sequence": name, "status": "skipped_intentional"})
            continue
        play = list(steps)
        if play and play[-1][0] == "close_document":
            play = play[:-1]
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            backend = FakeBackend()
            kernel = Kernel(core_registry(), backend, workspace=work)
            for tool, args in play:
                kernel.dispatch(tool, args)
            info = backend.active_document()
            if info is None:
                summary.append({"sequence": name, "status": "no_active_doc"})
                continue
            vr = kernel.dispatch("verify_model", {"groups": _SOLID_GROUPS})
            assert vr.ok, f"{name}: verify_model tool error {vr.error}"
            status = vr.result["verification"]["status"]
            if status == "failed":
                codes = [
                    c.get("code")
                    for c in vr.result["verification"]["checks"]
                    if not c["ok"]
                ]
                summary.append({"sequence": name, "status": "failed", "codes": codes})
                assert set(codes) <= {"VERIFY_EMPTY_BODY"}, (
                    f"{name}: unexpected verify failure codes={codes} "
                    f"checks={vr.result['verification']['checks']}"
                )
            else:
                summary.append(
                    {
                        "sequence": name,
                        "status": status,
                        "doc_type": info.doc_type,
                    }
                )

    exercised = [s for s in summary if s["status"] != "skipped_intentional"]
    assert len(exercised) >= 90
    counts: dict[str, int] = {}
    for row in summary:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    print(f"verify94_summary={counts} total={len(summary)}")
