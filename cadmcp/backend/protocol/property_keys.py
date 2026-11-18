"""Canonical custom property keys for CADMCP (PART_PROP_* / THREAD_*).

SolidWorks custom properties are free-form; these constants define the
contract for tools/recipes and for STEP sidecar meta (``properties``).
"""
from __future__ import annotations

from cadmcp.backend.protocol.constants import (
    THREAD_PROP_KEYS,
    THREAD_PROP_SIDE,
    THREAD_PROP_SIZE,
    THREAD_PROP_SPEC,
)

PART_PROP_PART_NO = "PartNo"
PART_PROP_DESCRIPTION = "Description"
PART_PROP_MATERIAL = "Material"
PART_PROP_REVISION = "Revision"

# Default keys returned by get_properties when keys omitted (empty string if unset).
PART_PROP_DEFAULT_KEYS: tuple[str, ...] = (
    PART_PROP_PART_NO,
    PART_PROP_DESCRIPTION,
    PART_PROP_MATERIAL,
    PART_PROP_REVISION,
    THREAD_PROP_SPEC,
    THREAD_PROP_SIDE,
    THREAD_PROP_SIZE,
)

PART_PROP_KEYS: frozenset[str] = frozenset(PART_PROP_DEFAULT_KEYS)

# Aliases accepted on input → canonical key
PART_PROP_ALIASES: dict[str, str] = {
    "part_no": PART_PROP_PART_NO,
    "partno": PART_PROP_PART_NO,
    "part_number": PART_PROP_PART_NO,
    "partnumber": PART_PROP_PART_NO,
    "pn": PART_PROP_PART_NO,
    "description": PART_PROP_DESCRIPTION,
    "desc": PART_PROP_DESCRIPTION,
    "material": PART_PROP_MATERIAL,
    "mat": PART_PROP_MATERIAL,
    "revision": PART_PROP_REVISION,
    "rev": PART_PROP_REVISION,
    "thread_spec": THREAD_PROP_SPEC,
    "threadspec": THREAD_PROP_SPEC,
    "thread_side": THREAD_PROP_SIDE,
    "threadside": THREAD_PROP_SIDE,
    "thread_size": THREAD_PROP_SIZE,
    "threadsize": THREAD_PROP_SIZE,
}


def normalize_property_key(key: str) -> str:
    """Map alias / case variants to a canonical key when known."""
    raw = str(key or "").strip()
    if not raw:
        return raw
    if raw in PART_PROP_KEYS or raw in THREAD_PROP_KEYS:
        return raw
    mapped = PART_PROP_ALIASES.get(raw.lower())
    if mapped:
        return mapped
    # Preserve unknown keys as given (SolidWorks allows arbitrary names)
    return raw
