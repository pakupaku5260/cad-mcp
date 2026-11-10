"""KiCAD-style dynamic toolbox: tools always registered; visibility via open/close.

No execute_tool dispatcher—after open, tools/list exposes real schemas; models call by name.
core is always open; closing core is rejected. --profile/--toolsets only set initial visibility
(for clients without tools/list_changed).
"""
from __future__ import annotations

import threading
from collections.abc import Iterable

from cadmcp.errors import fail
from cadmcp.registry import TOOLSET_DEFS, ToolRegistry, ToolSpec

# core cannot be closed; toolbox control tools live in core
ALWAYS_OPEN: frozenset[str] = frozenset({"core"})

# server bridge sends notifications/tools/list_changed after open/close
TOOLBOX_MUTATORS: frozenset[str] = frozenset({"open_toolbox", "close_toolbox"})


class ToolVisibility:
    """Process-wide visible toolset set (same lifetime as the single SW executor)."""

    def __init__(self, initially_open: Iterable[str] | None = None) -> None:
        if initially_open is None:
            open_set = set(TOOLSET_DEFS)
        else:
            open_set = set(initially_open) | set(ALWAYS_OPEN)
            unknown = open_set - set(TOOLSET_DEFS)
            if unknown:
                known = ", ".join(sorted(TOOLSET_DEFS))
                raise ValueError(f"Unknown toolset {sorted(unknown)!r}; choose {known}")
        self._open = open_set
        self._lock = threading.Lock()

    def open_names(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._open))

    def is_open(self, toolset: str) -> bool:
        with self._lock:
            return toolset in self._open

    def is_visible(self, spec: ToolSpec) -> bool:
        return self.is_open(spec.toolset)

    def visible_specs(self, registry: ToolRegistry) -> list[ToolSpec]:
        return [s for s in registry.all() if self.is_visible(s)]

    def open(self, names: Iterable[str]) -> dict:
        requested = _normalize_names(names)
        with self._lock:
            added = sorted(n for n in requested if n not in self._open)
            self._open.update(requested)
            return {
                "opened": added,
                "already_open": sorted(n for n in requested if n not in added),
                "open_toolsets": sorted(self._open),
            }

    def close(self, names: Iterable[str]) -> dict:
        requested = _normalize_names(names)
        blocked = sorted(n for n in requested if n in ALWAYS_OPEN)
        if blocked:
            raise fail(
                "INVALID_ARGUMENT",
                f"Cannot close toolset(s): {', '.join(blocked)}",
                "core stays visible (includes list_toolboxes / open_toolbox / search_tools)",
                blocked=blocked,
            )
        with self._lock:
            removed = sorted(n for n in requested if n in self._open)
            self._open.difference_update(requested)
            return {
                "closed": removed,
                "already_closed": sorted(n for n in requested if n not in removed),
                "open_toolsets": sorted(self._open),
            }

    def list_toolboxes(self, registry: ToolRegistry) -> dict:
        by_set: dict[str, list[str]] = {name: [] for name in TOOLSET_DEFS}
        for spec in registry.all():
            by_set.setdefault(spec.toolset, []).append(spec.name)
        with self._lock:
            open_snap = set(self._open)
        boxes = [
            {
                "name": name,
                "description": TOOLSET_DEFS[name],
                "open": name in open_snap,
                "tools": sorted(by_set.get(name, [])),
                "count": len(by_set.get(name, [])),
            }
            for name in sorted(TOOLSET_DEFS)
        ]
        return {"toolboxes": boxes, "open_toolsets": sorted(open_snap)}

    def search_tools(self, registry: ToolRegistry, query: str, *, limit: int = 20) -> dict:
        q = (query or "").strip().lower()
        if not q:
            raise fail(
                "INVALID_ARGUMENT",
                "query must not be empty",
                "Pass a tool name or description fragment, e.g. flange / mate / export",
            )
        limit = max(1, min(int(limit), 50))
        hits: list[dict] = []
        with self._lock:
            open_snap = set(self._open)
        for spec in registry.all():
            hay = f"{spec.name} {spec.description}".lower()
            if q not in hay:
                continue
            hits.append(
                {
                    "name": spec.name,
                    "toolset": spec.toolset,
                    "open": spec.toolset in open_snap,
                    "description": spec.description,
                }
            )
            if len(hits) >= limit:
                break
        return {"query": query, "matches": hits, "count": len(hits)}


def _normalize_names(names: Iterable[str]) -> list[str]:
    resolved = list(dict.fromkeys(n.strip() for n in names if n and n.strip()))
    if not resolved:
        raise fail(
            "INVALID_ARGUMENT",
            "toolsets must not be empty",
            f"Choose: {', '.join(sorted(TOOLSET_DEFS))}",
        )
    unknown = [n for n in resolved if n not in TOOLSET_DEFS]
    if unknown:
        raise fail(
            "INVALID_ARGUMENT",
            f"Unknown toolset(s): {', '.join(unknown)}",
            f"Choose: {', '.join(sorted(TOOLSET_DEFS))}",
            unknown=unknown,
        )
    return resolved


__all__ = ["ALWAYS_OPEN", "TOOLBOX_MUTATORS", "ToolVisibility"]
