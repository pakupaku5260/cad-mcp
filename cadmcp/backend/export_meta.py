"""STEP sidecar meta (*.step.meta.json) — properties live here, not in STEP bytes."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def meta_path_for(step_path: Path | str) -> Path:
    """``foo.step`` → ``foo.step.meta.json``."""
    p = Path(step_path)
    return p.with_name(p.name + ".meta.json")


def write_step_meta(
    step_path: Path | str,
    *,
    step_ap: int,
    step_ap_requested: int,
    export_path: str,
    properties: dict[str, str] | None = None,
    source_path: str | None = None,
    source_title: str | None = None,
    configuration: str | None = None,
    doc_type: str | None = None,
    extra: dict[str, Any] | None = None,
) -> Path:
    """Write sibling ``<file>.step.meta.json`` next to the STEP export."""
    target = Path(step_path)
    out = meta_path_for(target)
    verified = int(step_ap) == int(step_ap_requested)
    payload: dict[str, Any] = {
        "schema": "cadmcp.step_meta/v1",
        "format": "step",
        "step_file": target.name,
        "step_ap": int(step_ap),
        "step_ap_requested": int(step_ap_requested),
        "step_ap_verified": verified,
        "export_path": str(export_path),
        "source_path": source_path or "",
        "source_title": source_title or "",
        "configuration": configuration or "",
        "doc_type": doc_type or "",
        "properties": dict(properties or {}),
        "exported_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": (
            "Custom properties are mirrored here; AP203/AP214 STEP files do not "
            "embed them. AP242 uses PublishSTEP242File (MBD); protocol is ring-3 verified."
        ),
    }
    if extra:
        payload.update(extra)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out
