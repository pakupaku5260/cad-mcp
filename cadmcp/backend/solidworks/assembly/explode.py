"""Assembly domain · exploded views (S6-3c).

S6-3c: _exploded_view_names / _is_exploded / explode_view / show_exploded / list_exploded_views

Dependencies (self, MRO):
- `sw` (COMConnectionMixin)
- `_require_assembly_doc` (InfrastructureMixin)
- `_call` / `_map_error` (STAThreadMixin)
- `_get` (_helpers)

imports:
- `cadmcp.errors` (fail)
- `.._helpers` (_get)
"""
from __future__ import annotations

import logging
import traceback
from typing import Any

from cadmcp.errors import fail

from .._helpers import _get

log = logging.getLogger(__name__)


class ExplodeMixin:
    """Exploded views (S6-3c: 5 methods)."""

    def _init_state(self) -> None:
        pass  # stateless

    # ---------- internal helpers ----------

    def _exploded_view_names(self, doc: Any) -> list[str]:
        raw = None
        try:
            raw = _get(doc, "GetExplodedViewNames")
        except Exception:
            log.debug("GetExplodedViewNames failed: %s", traceback.format_exc())
            raw = None
        if raw is None:
            try:
                raw = _get(doc, "GetExplodedViewNames2", "")
            except Exception:
                log.debug("GetExplodedViewNames2 failed: %s", traceback.format_exc())
                return []
        if raw is None:
            return []
        if isinstance(raw, str):
            return [raw] if raw.strip() else []
        try:
            return [str(x) for x in raw if x]
        except TypeError:
            return [str(raw)] if str(raw).strip() else []

    def _is_exploded(self, doc: Any) -> bool:
        try:
            return bool(_get(doc, "IsExploded"))
        except Exception:
            return False

    # ---------- public API ----------

    def explode_view(self) -> tuple[str, list[str]]:
        def _fn() -> tuple[str, list[str]]:
            doc = self.sw.ActiveDoc
            self._require_assembly_doc(doc, "Use new_assembly to create an assembly before exploding")
            before = set(self._exploded_view_names(doc))
            try:
                ok = bool(_get(doc, "CreateExplodedView"))
            except Exception as exc:
                log.debug("CreateExplodedView failed: %s", traceback.format_exc())
                raise self._map_error(exc) from exc
            names = self._exploded_view_names(doc)
            added = [n for n in names if n not in before]
            name = added[-1] if added else (names[-1] if names else "")
            if not ok or not name:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Failed to create exploded view",
                    "Confirm the active document is an assembly and no modal dialog is blocking",
                )
            return name, names

        return self._call(_fn)

    def show_exploded(
        self, show: bool, name: str | None = None
    ) -> tuple[str | None, list[str], bool]:
        def _fn() -> tuple[str | None, list[str], bool]:
            doc = self.sw.ActiveDoc
            self._require_assembly_doc(doc, "Use new_assembly to create an assembly before toggling exploded view")
            names = self._exploded_view_names(doc)
            if not names:
                raise fail("FEATURE_NOT_FOUND", "No explode view", "Call explode_view first")
            raw = str(name or "").strip()
            if raw:
                if raw not in names:
                    raise fail(
                        "FEATURE_NOT_FOUND",
                        f"Exploded view not found: {raw!r}",
                        "Use list_exploded_views to see names",
                        name=raw,
                    )
                chosen: str | None = raw
                try:
                    ok = bool(_get(doc, "ShowExploded2", bool(show), raw))
                except Exception as exc:
                    log.debug("ShowExploded2 failed: %s", traceback.format_exc())
                    raise self._map_error(exc) from exc
            else:
                chosen = names[-1]
                try:
                    ok = bool(_get(doc, "ShowExploded", bool(show)))
                except Exception as exc:
                    log.debug("ShowExploded failed: %s", traceback.format_exc())
                    raise self._map_error(exc) from exc
            if not ok:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Failed to toggle exploded view display",
                    "Confirm the exploded view exists and no modal dialog is blocking",
                )
            return chosen, self._exploded_view_names(doc), self._is_exploded(doc)

        return self._call(_fn)

    def list_exploded_views(self) -> tuple[list[str], bool]:
        def _fn() -> tuple[list[str], bool]:
            doc = self.sw.ActiveDoc
            self._require_assembly_doc(doc, "Use new_assembly to create an assembly before listing exploded views")
            return self._exploded_view_names(doc), self._is_exploded(doc)

        return self._call(_fn)
