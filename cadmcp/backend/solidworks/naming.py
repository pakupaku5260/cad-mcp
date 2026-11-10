"""COM backend: feature naming map (logical name <-> real name).

Ownership:
- `_aliases`: logical name -> real name
- `_kind_counts`: logical name prefix -> count created

Used by sketch / features / assembly / query (via MRO).
Does not depend on `_sketch_*` state (owned by `SketchMixin`, moved in S4).

Depends on (self):
- none (only reads doc in `_features_of`)
"""
from __future__ import annotations

import logging
from typing import Any

from cadmcp.errors import fail

from ._helpers import _get

log = logging.getLogger(__name__)


class NamingMixin:
    """Feature naming map."""

    def _init_state(self) -> None:
        self._aliases: dict[str, str] = {}      # logical name -> real name
        self._kind_counts: dict[str, int] = {}  # logical prefix -> count created

    def _reset_naming_state(self) -> None:
        """Clear logical name map (NamingMixin is the sole state owner)."""
        self._aliases.clear()
        self._kind_counts.clear()

    def _features_of(self, doc: Any) -> list[Any]:
        """Return feature objects in tree order (call on STA thread)."""
        out: list[Any] = []
        feat = _get(doc, "FirstFeature")
        while feat is not None:
            out.append(feat)
            feat = _get(feat, "GetNextFeature")
        return out

    def _real_name(self, name: str) -> str:
        """Logical name (Sketch1 / Helix1) -> tree real name; pass through if unregistered."""
        return self._aliases.get(name, name)

    def _find_feature(self, doc: Any, name: str) -> Any:
        real = self._real_name(name)
        for feat in self._features_of(doc):
            try:
                n = str(_get(feat, "Name"))
            except Exception:
                continue
            if n == name or n == real:
                return feat
        return None

    def _register(self, prefix: str, real_name: str) -> str:
        """Register a feature; return fake-style logical name (Boss-Extrude1, Fillet1, ...)."""
        n = self._kind_counts.get(prefix, 0) + 1
        self._kind_counts[prefix] = n
        logical = f"{prefix}{n}"
        self._aliases[logical] = real_name
        return logical

    def _resolve_feature(self, doc: Any, target: str) -> Any:
        real = self._aliases.get(target, target)
        feat = self._find_feature(doc, real)
        if feat is None:
            raise fail(
                "FEATURE_NOT_FOUND",
                f"Solid feature not found: {target!r}",
                "Use list_features; fillet/chamfer target solid features only",
                requested=target,
            )
        return feat

    def _feature_real_name(self, feat: Any, default: str) -> str:
        try:
            return str(_get(feat, "Name"))
        except Exception:
            return default
