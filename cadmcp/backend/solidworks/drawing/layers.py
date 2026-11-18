"""Drawing layers: create, activate and list user layers.

Does not assign entities to layers or touch sheet setup.
Boundary: every COM call stays inside `self._call`; known layer names stay in the drawing state.
"""

from __future__ import annotations

import logging
import traceback

from cadmcp.errors import fail

from .._helpers import _get

log = logging.getLogger(__name__)

class DrawingLayersMixin:
    """Layer creation, activation and listing."""

    def add_drawing_layer(self, name: str, color: int = 255) -> dict:
        def _fn() -> dict:
            doc = self.sw.ActiveDoc
            self._require_drawing_doc(doc, "Call new_drawing first")
            raw = str(name).strip()
            if not raw:
                raise fail("INVALID_ARGUMENT", "Layer name cannot be empty", "Pass name, e.g.  VISIBLE")
            if not isinstance(color, int) or isinstance(color, bool):
                raise fail("INVALID_ARGUMENT", "color must be an integer color value", "e.g. 255 (red) or 65280 (green)")
            lm = _get(doc, "GetLayerManager")
            if lm is None:
                raise fail("FEATURE_CREATE_FAILED", "Cannot get layer manager", "Confirm active document is a drawing")
            try:
                existing = _get(lm, "GetLayer", raw)
            except Exception:
                existing = None
            if existing is not None:
                raise fail(
                    "INVALID_ARGUMENT",
                    f"Layer already exists: {raw}",
                    "Use another name, or set_drawing_layer for current layer",
                    requested=raw,
                )
            try:
                res = _get(lm, "AddLayer", raw, "", int(color), 0, 0)
            except Exception as exc:
                log.debug("AddLayer failed: %s", traceback.format_exc())
                raise self._map_error(exc) from exc
            if res in (0, False):
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    f"AddLayer failed：{raw}",
                    "Retry with a valid layer name",
                    requested=raw,
                )
            if raw not in self._drawing_layers_known:
                self._drawing_layers_known.append(raw)
            return {"name": raw, "color": int(color)}

        return self._call(_fn)

    def set_drawing_layer(self, name: str) -> str:
        def _fn() -> str:
            doc = self.sw.ActiveDoc
            self._require_drawing_doc(doc, "Call new_drawing first")
            raw = str(name).strip()
            if not raw:
                raise fail("INVALID_ARGUMENT", "Layer name cannot be empty", "Pass name, or add_drawing_layer first")
            lm = _get(doc, "GetLayerManager")
            if lm is None:
                raise fail("FEATURE_CREATE_FAILED", "Cannot get layer manager", "Confirm active document is a drawing")
            try:
                layer = _get(lm, "GetLayer", raw)
            except Exception:
                layer = None
            if layer is None:
                raise fail(
                    "FEATURE_NOT_FOUND",
                    f"Layer not found: {raw}",
                    "add_drawing_layer first, or check list_drawing_layers",
                    requested=raw,
                )
            try:
                ok = _get(lm, "SetCurrentLayer", raw)
            except Exception as exc:
                log.debug("SetCurrentLayer failed: %s", traceback.format_exc())
                raise self._map_error(exc) from exc
            if ok in (0, False):
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    f"Cannot switch to layer: {raw}",
                    "Confirm layer was not deleted",
                    requested=raw,
                )
            if raw not in self._drawing_layers_known:
                self._drawing_layers_known.append(raw)
            return raw

        return self._call(_fn)

    def list_drawing_layers(self) -> dict:
        def _fn() -> dict:
            doc = self.sw.ActiveDoc
            self._require_drawing_doc(doc, "Call new_drawing first")
            lm = _get(doc, "GetLayerManager")
            if lm is None:
                raise fail("FEATURE_CREATE_FAILED", "Cannot get layer manager", "Confirm active document is a drawing")
            try:
                count = int(_get(lm, "GetCount") or 0)
            except Exception:
                count = 0
            current = None
            try:
                cur = _get(lm, "GetCurrentLayer")
                current = None if cur is None else str(cur)
            except Exception:
                current = None
            known: list[str] = []
            for name in self._drawing_layers_known:
                try:
                    if _get(lm, "GetLayer", name) is not None:
                        known.append(name)
                except Exception:
                    continue
            if current and current not in known:
                known = [current, *known]
            return {"count": count, "current": current, "layers": known}

        return self._call(_fn)
