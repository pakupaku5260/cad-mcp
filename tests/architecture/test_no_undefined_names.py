"""Backend undefined-name gate (F821).

After the S10 split, `com/assembly/component.py` missed an import: COM
`pattern_component` only triggers `NameError` on the real path; offline tests all use
fake and miss it. Ruff F821 catches “name used but not imported” at the architecture layer.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "cadmcp" / "backend"


def test_backend_has_no_undefined_names() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--select",
            "F821",
            "--output-format",
            "concise",
            "--no-cache",
            str(BACKEND),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode == 0, (
        "Backend has undefined names (F821):\n"
        f"{proc.stdout}{proc.stderr}"
    )
