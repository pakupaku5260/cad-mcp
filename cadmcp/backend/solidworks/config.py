"""COM backend · configurations / material.

Dependencies (self, MRO):
- ``_call`` / ``_map_error`` (STAThreadMixin)
- ``_model_doc`` (InfrastructureMixin)
- ``_get`` (_helpers)

imports:
- ``cadmcp.errors`` (CadMcpError / fail)
- ``._helpers`` (_get)
"""
from __future__ import annotations

import logging
import traceback
from typing import Any

from cadmcp.errors import CadMcpError, fail

from ._helpers import _get

log = logging.getLogger(__name__)


class ConfigMixin:
    """Configurations / material (S4-4a-2: 5 methods)."""

    def _init_state(self) -> None:
        pass  # stateless

    def list_configurations(self) -> tuple[str, list[str]]:
        def _fn() -> tuple[str, list[str]]:
            doc = self._model_doc()
            raw = _get(doc, "GetConfigurationNames") or ()
            names = [str(n) for n in raw if n]
            active = names[0] if names else "Default"
            try:
                mgr = _get(doc, "ConfigurationManager")
                cfg = _get(mgr, "ActiveConfiguration") if mgr is not None else None
                if cfg is not None:
                    active = str(_get(cfg, "Name") or active)
            except Exception:
                log.debug("Read active configuration failed: %s", traceback.format_exc())
            return active, names

        return self._call(_fn)

    def set_configuration(self, name: str, create: bool = False) -> tuple[str, bool]:
        def _fn() -> tuple[str, bool]:
            doc = self._model_doc()
            raw = str(name).strip()
            if not raw:
                raise fail("INVALID_ARGUMENT", "Configuration name cannot be empty", "Pass name")
            names = [str(n) for n in (_get(doc, "GetConfigurationNames") or ()) if n]
            created = False
            if raw not in names:
                if not create:
                    raise fail(
                        "FEATURE_NOT_FOUND",
                        f"Configuration not found: {raw!r}",
                        "Call list_configurations first, or set_configuration(..., create=true)",
                        name=raw,
                    )
                parent = names[0] if names else ""
                try:
                    mgr = _get(doc, "ConfigurationManager")
                    act = _get(mgr, "ActiveConfiguration") if mgr is not None else None
                    if act is not None:
                        parent = str(_get(act, "Name") or parent)
                    # AddConfiguration2 is often CDispatch under pywin32; cannot use _get(..., args)
                    cfg = mgr.AddConfiguration2(raw, "", "", 0, parent, "", True)
                    if cfg is None:
                        cfg = doc.AddConfiguration2(raw, "", "", False, False, True, True, 0)
                    if cfg is None:
                        raise fail(
                            "FEATURE_CREATE_FAILED",
                            f"Failed to create configuration: {raw}",
                            "Use an unused configuration name, or check for open dialogs",
                        )
                    created = True
                except CadMcpError:
                    raise
                except Exception as exc:
                    raise fail(
                        "FEATURE_CREATE_FAILED",
                        f"Failed to create configuration: {raw}",
                        "Use an unused configuration name, or check for open dialogs",
                    ) from exc
            try:
                # On localized SW, ShowConfiguration2 often returns False but active config already switched.
                doc.ShowConfiguration2(raw)
            except Exception:
                log.debug("ShowConfiguration2 exception: %s", traceback.format_exc())
            active = raw
            try:
                mgr = _get(doc, "ConfigurationManager")
                cfg = _get(mgr, "ActiveConfiguration") if mgr is not None else None
                if cfg is not None:
                    active = str(_get(cfg, "Name") or "")
            except Exception:
                log.debug("Read active configuration failed: %s", traceback.format_exc())
            if active != raw:
                raise self._com_failed(
                    f"Failed to switch configuration: {raw}", "Verify the name with list_configurations"
                )
            return raw, created

        return self._call(_fn)

    def _read_material(self, doc: Any) -> tuple[str, str]:
        import pythoncom
        from win32com.client import VARIANT

        db = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BSTR, "")
        try:
            name = doc.GetMaterialPropertyName2("", db)
        except Exception:
            try:
                name = _get(doc, "GetMaterialPropertyName2", "", db)
            except Exception:
                log.debug("GetMaterialPropertyName2 failed: %s", traceback.format_exc())
                return "", ""
        return str(name or ""), str(getattr(db, "value", "") or "")

    def get_material(self) -> tuple[str, str]:
        def _fn() -> tuple[str, str]:
            return self._read_material(self._model_doc(part_only=True))

        return self._call(_fn)

    def set_material(self, name: str) -> tuple[str, str]:
        def _fn() -> tuple[str, str]:
            doc = self._model_doc(part_only=True)
            raw = str(name).strip()
            if not raw:
                raise fail("INVALID_ARGUMENT", "Material designation cannot be empty", "e.g. AISI 1020")
            try:
                doc.SetMaterialPropertyName2("", "", raw)
            except Exception as exc:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    f"Failed to set material: {raw}",
                    "Use a grade from the material library (e.g. AISI 1020)",
                ) from exc
            return self._read_material(doc)

        return self._call(_fn)
