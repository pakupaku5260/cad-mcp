"""COM backend · views / screenshots.

Dependencies (self, MRO):
- ``_call`` / ``_map_error`` (STAThreadMixin)
- ``_get`` (_helpers)

imports:
- ``cadmcp.errors`` (CadMcpError / fail)
- ``._constants`` (_VIEW_IDS / _SW_*)
- ``._helpers`` (_get)
"""
from __future__ import annotations

import logging
import traceback
from pathlib import Path
from typing import Any

from cadmcp.errors import CadMcpError, fail

from ._constants import (
    _SW_DISPLAY_CURVES,
    _SW_DISPLAY_SKETCHES,
    _SW_PREF_NO_OPTION,
    _SW_VIEW_HIDE_ALL_TYPES,
    _VIEW_IDS,
)
from ._helpers import _get

log = logging.getLogger(__name__)


class ViewMixin:
    """Views / screenshots (S4-4b: 5 methods)."""

    def _init_state(self) -> None:
        pass  # stateless

    def _show_view(self, doc: Any, view: str) -> None:
        vid = _VIEW_IDS.get(view)
        if vid is None:
            raise fail("INVALID_ARGUMENT", f"Unknown view: {view!r}",
                       f"Valid views: {', '.join(_VIEW_IDS)}", requested=view)
        doc.ShowNamedView2("", vid)
        doc.ViewZoomtofit2()

    def set_view(self, view: str) -> None:
        def _fn() -> None:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            try:
                mv = _get(doc, "ActiveView") or _get(doc, "GetFirstView")
            except Exception:
                mv = None
            if mv is None:
                raise self._com_failed("Failed to get view", "Ensure the document is active")
            try:
                self._show_view(doc, view)
            except CadMcpError:
                raise
            except Exception as exc:
                raise self._map_error(exc) from exc

        return self._call(_fn)

    def _screenshot_hide_construction(self, doc: Any) -> list[tuple]:
        """Hide sketches/3D curves/ref geometry before screenshot; return items to restore."""
        restores: list[tuple] = []
        ext = None
        try:
            ext = _get(doc, "Extension")
        except Exception:
            ext = None
        # HideAllTypes=True hides non-solid display; Sketches/Curves=False turns off sketches and curves
        jobs = (
            (_SW_VIEW_HIDE_ALL_TYPES, True),
            (_SW_DISPLAY_SKETCHES, False),
            (_SW_DISPLAY_CURVES, False),
        )
        for pref, hide_val in jobs:
            applied = False
            if ext is not None:
                try:
                    old = bool(_get(ext, "GetUserPreferenceToggle", pref, _SW_PREF_NO_OPTION))
                    _get(ext, "SetUserPreferenceToggle", pref, _SW_PREF_NO_OPTION, hide_val)
                    restores.append(("ext", ext, pref, old))
                    applied = True
                except Exception:
                    log.debug("Extension display toggle %s failed: %s", pref, traceback.format_exc())
            if not applied:
                try:
                    old = bool(_get(self.sw, "GetUserPreferenceToggle", pref))
                    _get(self.sw, "SetUserPreferenceToggle", pref, hide_val)
                    restores.append(("app", self.sw, pref, old))
                except Exception:
                    log.debug("Application display toggle %s failed: %s", pref, traceback.format_exc())
        try:
            _get(doc, "ClearSelection2", True)
        except Exception:
            pass
        try:
            _get(doc, "GraphicsRedraw2")
        except Exception:
            pass
        return restores

    @staticmethod
    def _screenshot_restore(doc: Any, restores: list[tuple]) -> None:
        for item in reversed(restores):
            kind = item[0]
            try:
                if kind == "ext":
                    _, ext, pref, old = item
                    _get(ext, "SetUserPreferenceToggle", pref, _SW_PREF_NO_OPTION, old)
                elif kind == "app":
                    _, app, pref, old = item
                    _get(app, "SetUserPreferenceToggle", pref, old)
            except Exception:
                log.debug("Restore screenshot display toggles failed: %s", traceback.format_exc())
        try:
            _get(doc, "GraphicsRedraw2")
        except Exception:
            pass

    def screenshot(self, path: Path, view: str = "isometric") -> None:
        def _fn() -> None:
            doc = self.sw.ActiveDoc
            if doc is None:
                raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
            restores: list[tuple] = []
            try:
                self._show_view(doc, view)
                restores = self._screenshot_hide_construction(doc)
                self._show_view(doc, view)
                try:
                    _get(doc, "SaveBitmapFile", str(path), 0, 0, 1920, 1080, False, True, False, False)
                except Exception:
                    try:
                        doc.SaveAs3(str(path), 0, 2)
                    except Exception as exc:
                        raise self._map_error(exc) from exc
            except CadMcpError:
                raise
            except Exception as exc:
                raise self._map_error(exc) from exc
            finally:
                if restores:
                    self._screenshot_restore(doc, restores)

        return self._call(_fn)
