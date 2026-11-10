""" COM backend · Underlying helper function (pure function + COM dual path read). """
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ._constants import (
    _FEATURE_KINDS,
    _SERVER_GONE_HRESULTS,
    SW_DOC_ASSEMBLY,
    SW_DOC_DRAWING,
    SW_DOC_PART,
)

log = logging.getLogger(__name__)


def _pid_of(hwnd, gui_mod, proc_mod=None) -> int | None:
    """ Window PID: proc_mod first, gui_mod bottom (both historically exported this function).

    Parameter renaming: gui_mod/proc_mod (the original module name no longer appears, avoiding white list false positives).
    """
    for mod in (proc_mod, gui_mod):
        fn = getattr(mod, "GetWindowThreadProcessId", None)
        if fn is None:
            continue
        try:
            res = fn(hwnd)
        except Exception:
            continue
        if isinstance(res, (tuple, list)) and len(res) >= 2 and res[1]:
            return int(res[1])
    return None


def _derive_modal(owner: int | None, owner_enabled: bool | None) -> bool | None:
    if owner is None:
        return False
    if owner_enabled is None:
        return None
    return not owner_enabled


def _is_server_gone(exc: BaseException) -> bool:
    return getattr(exc, "hresult", None) in _SERVER_GONE_HRESULTS


def _as_bbox6(box: Any) -> tuple[float, float, float, float, float, float] | None:
    if box is None:
        return None
    if isinstance(box, (tuple, list)) and len(box) == 2 and isinstance(box[0], (bool, int)):
        box = box[1]
    if box is None:
        return None
    try:
        seq = list(box)
    except TypeError:
        return None
    flat: list[float] = []
    for item in seq:
        if isinstance(item, (tuple, list)):
            try:
                flat.extend(float(x) for x in item)
            except (TypeError, ValueError):
                return None
        else:
            try:
                flat.append(float(item))
            except (TypeError, ValueError):
                return None
    if len(flat) == 6:
        return (flat[0], flat[1], flat[2], flat[3], flat[4], flat[5])
    if len(flat) == 24:
        xs, ys, zs = flat[0::3], flat[1::3], flat[2::3]
        return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))
    return None


def _union_bbox6(
    boxes: list[tuple[float, float, float, float, float, float]],
) -> tuple[float, float, float, float, float, float]:
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        min(b[2] for b in boxes),
        max(b[3] for b in boxes),
        max(b[4] for b in boxes),
        max(b[5] for b in boxes),
    )


def _get(obj: Any, name: str, *args: Any) -> Any:
    """ Attribute/Method Dual Path Read (SW2025 partial members behave as attributes under pywin32).

    Note: The COM object (CDispatch) returned by the property read is also callable (default member) itself,
    Must be returned as is and cannot be called again as a method.
    """
    value = getattr(obj, name)
    if hasattr(value, "_oleobj_"):
        if args:
            raise TypeError(f"{name} is a property, parameters are not accepted")
        return value
    if callable(value):
        return value(*args)
    if args:
        raise TypeError(f"{name} is a property, parameters are not accepted")
    return value


def _scrub(exc: BaseException | None) -> None:
    """ Cut exception references to stack frames to avoid COM objects being recycled in non-STA threads. """
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        nxt = exc.__cause__ or exc.__context__
        exc.__traceback__ = None
        exc.__cause__ = None
        exc.__context__ = None
        exc = nxt


def _doc_type_for(path: Path) -> tuple[str, int]:
    suffix = path.suffix.lower()
    if suffix == ".sldasm":
        return "assembly", SW_DOC_ASSEMBLY
    if suffix == ".slddrw":
        return "drawing", SW_DOC_DRAWING
    return "part", SW_DOC_PART


def feature_kind_from_sw(tname: str) -> str:
    key = str(tname or "")
    if key in _FEATURE_KINDS:
        return _FEATURE_KINDS[key]
    low = key.lower()
    if low in {"ice", "cut"}:
        return "extrude_cut"
    return low or "unknown"
