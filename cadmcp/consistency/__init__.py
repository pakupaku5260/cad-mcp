"""Fake vs real SolidWorks consistency harness (v4 §17.1 risk §17.6 calibration).

Same op sequence (tool name + args) runs on fake and COM backends through the full Kernel
dispatch path; each run yields a **structural fingerprint** compared to one golden JSON file:

- Fingerprints are structural only: per-step ok, error codes, side-effect level, result/delta/
  rebuild key sets, state_version trail, warning count — **not numeric**. Volumes belong in
  golden-value tests; structural drift signals fake mismatch.
- Golden files are a contract both backends must satisfy; COM mismatch is resolved per sequence
  (fix fake or golden) — never silently waived. Regenerating goldens requires human review
  (`scripts/gen_consistency_golden.py` is a maintainer tool, not routine CI).
- Sequences include error paths: matching error semantics is a CADBackend protocol requirement
  (see `backend/base.py`); fake and COM must align on errors.
- COM tests are marked `sw` (`-m sw` to enable); skip when com backend is unavailable. The COM
  factory resets pre-sequence state (close open documents); initial state differs across hosts
  until reset.
"""

from __future__ import annotations

from cadmcp.consistency._types import SequenceStep
from cadmcp.consistency.fingerprint import diff_fingerprints, structural_fingerprint
from cadmcp.consistency.runner import run_sequence
from cadmcp.consistency.sequences import SEQUENCES

__all__ = [
    "SEQUENCES",
    "SequenceStep",
    "diff_fingerprints",
    "run_sequence",
    "structural_fingerprint",
]
