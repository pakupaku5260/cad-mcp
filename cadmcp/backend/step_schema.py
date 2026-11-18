"""Detect STEP application protocol from an exported file (ring-3 verification)."""
from __future__ import annotations

import re
from pathlib import Path

# Fake export markers carry ":ap=NNN"; real STEP uses FILE_SCHEMA / AP tokens.
_FAKE_AP_RE = re.compile(r":ap=(\d+)\b")
_AP_TOKEN_RE = re.compile(r"\bAP[_\s-]?(\d{3})\b", re.IGNORECASE)


def detect_step_ap(path: Path | str) -> int | None:
    """Return 203/214/242 if detectable, else None.

    Prefer explicit AP tokens; fall back to common schema names used by SolidWorks.
    """
    p = Path(path)
    try:
        raw = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    head = raw[:16000]
    fake = _FAKE_AP_RE.search(head)
    if fake and ("FAKE-EXPORT" in head or head.lstrip().startswith("ISO-10303")):
        # Prefer FAKE marker when present (offline FakeBackend).
        if "FAKE-EXPORT" in head:
            try:
                return int(fake.group(1))
            except ValueError:
                pass
    upper = head.upper()
    # Strongest: explicit AP242 / managed model based engineering
    if "AP242" in upper or "MANAGED_MODEL_BASED_3D_ENGINEERING" in upper:
        return 242
    if "AP214" in upper or "AUTOMOTIVE_DESIGN" in upper:
        return 214
    if "AP203" in upper or "CONFIG_CONTROL_DESIGN" in upper:
        return 203
    token = _AP_TOKEN_RE.search(head)
    if token:
        try:
            n = int(token.group(1))
        except ValueError:
            return None
        if n in (203, 214, 242):
            return n
    if fake:
        try:
            n = int(fake.group(1))
            if n in (203, 214, 242):
                return n
        except ValueError:
            pass
    return None


def step_schema_line(ap: int) -> str:
    """Minimal FILE_SCHEMA line for Fake STEP exports (ring-3 detectable)."""
    if int(ap) == 242:
        return "FILE_SCHEMA(('MANAGED_MODEL_BASED_3D_ENGINEERING_AP242'));"
    if int(ap) == 214:
        return "FILE_SCHEMA(('AUTOMOTIVE_DESIGN'));"
    return "FILE_SCHEMA(('CONFIG_CONTROL_DESIGN'));"
