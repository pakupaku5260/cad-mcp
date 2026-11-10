"""Paginate list results: trim only when limit/offset are set (keeps golden outputs stable)."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def paginate(
    rows: Sequence[Any], limit: int | None, offset: int | None
) -> tuple[list[Any], int | None]:
    """Return (page rows, start index). If neither limit nor offset, return all rows and None."""
    if limit is None and offset is None:
        return list(rows), None
    start = offset or 0
    end = None if limit is None else start + limit
    return list(rows[start:end]), start
