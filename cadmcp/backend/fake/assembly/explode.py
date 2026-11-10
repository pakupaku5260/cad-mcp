"""Fake backend · assembly domain · explode view（S8h）。

S8h: explode_view / show_exploded / list_exploded_views (3 methods).

Dependencies (self, MRO):
- `_enter` / `_require_doc` / `_doc`（FakeBackend）
- `_require_assembly`（FakeAssemblyComponentMixin，S8f）

Imports:
- `cadmcp.errors`（fail）
"""
from __future__ import annotations

from cadmcp.errors import fail


class FakeAssemblyExplodeMixin:
    """explode view (S8h: 3 methods)."""

    def _init_state(self) -> None:
        pass  # State owned by FakeBackend._init_state

    def explode_view(self) -> tuple[str, list[str]]:
        self._enter("explode_view")
        doc = self._require_assembly("Create an assembly with new_assembly, then explode")
        n = len(doc.exploded_views) + 1
        name = f"ExplodedView{n}"
        doc.exploded_views.append(name)
        doc.exploded = True
        doc.modified = True
        return name, list(doc.exploded_views)

    def show_exploded(
        self, show: bool, name: str | None = None
    ) -> tuple[str | None, list[str], bool]:
        self._enter("show_exploded", show=show, name=name)
        doc = self._require_assembly("Create an assembly with new_assembly, then toggle explode view")
        if not doc.exploded_views:
            raise fail("FEATURE_NOT_FOUND", "No explode view", "Call explode_view first")
        raw = str(name or "").strip()
        if raw:
            if raw not in doc.exploded_views:
                raise fail(
                    "FEATURE_NOT_FOUND",
                    f"Explode view not found: {raw!r}",
                    "Use list_exploded_views for names",
                    name=raw,
                )
            chosen = raw
        else:
            chosen = doc.exploded_views[-1]
        doc.exploded = bool(show)
        return chosen, list(doc.exploded_views), doc.exploded

    def list_exploded_views(self) -> tuple[list[str], bool]:
        self._enter("list_exploded_views")
        doc = self._require_assembly("Create an assembly with new_assembly, then list explode views")
        return list(doc.exploded_views), bool(doc.exploded)

        