"""COM backend · part/assembly custom properties (CustomPropertyManager)."""
from __future__ import annotations

import logging
import traceback
from typing import Any

from cadmcp.backend.protocol.property_keys import (
    PART_PROP_DEFAULT_KEYS,
    normalize_property_key,
)
from cadmcp.errors import fail

from ._constants import SW_DOC_ASSEMBLY, SW_DOC_PART
from ._helpers import _get

log = logging.getLogger(__name__)


class PropertiesMixin:
    """Part/assembly custom property read/write (configuration ``\"\"`` = active)."""

    def _init_state(self) -> None:
        pass  # stateless

    def _require_part_or_assembly(self, doc: Any, hint: str) -> None:
        if doc is None:
            raise fail("NO_ACTIVE_DOCUMENT", "No active document", hint)
        try:
            doc_type = int(_get(doc, "GetType"))
        except Exception:
            doc_type = 0
        if doc_type not in (SW_DOC_PART, SW_DOC_ASSEMBLY):
            raise fail(
                "INVALID_ARGUMENT",
                "Custom properties require a part or assembly",
                hint,
            )

    def _cpm_doc(self, doc: Any) -> Any:
        try:
            return doc.Extension.CustomPropertyManager("")
        except Exception as exc:
            raise fail(
                "FEATURE_CREATE_FAILED",
                "Cannot get CustomPropertyManager",
                "Confirm active document is a part or assembly",
            ) from exc

    def _read_custom_props(self, doc: Any, keys: list[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        cpm = self._cpm_doc(doc)
        for key in keys:
            val = ""
            try:
                got = _get(cpm, "Get", key)
                if isinstance(got, (list, tuple)) and got:
                    val = str(got[0] if not isinstance(got[0], (list, tuple)) else got[-1] or "")
                elif got is not None:
                    val = str(got)
            except Exception:
                try:
                    res = cpm.Get5(key, False, "", "")
                    if isinstance(res, (list, tuple)) and len(res) >= 3:
                        val = str(res[2] or res[1] or "")
                except Exception:
                    log.debug("Read property %s failed: %s", key, traceback.format_exc())
            out[key] = val
        return out

    def set_properties(self, props: dict[str, str]) -> dict:
        def _fn() -> dict:
            doc = self.sw.ActiveDoc
            self._require_part_or_assembly(doc, "Open or create a part/assembly first")
            cpm = self._cpm_doc(doc)
            written: dict[str, str] = {}
            for k, v in props.items():
                key = normalize_property_key(str(k))
                if not key:
                    continue
                text = str(v)
                ok = False
                try:
                    # Add3(FieldName, FieldType=swCustomInfoText=30, FieldValue, DeleteExisting)
                    cpm.Add3(key, 30, text, 1)
                    ok = True
                except Exception:
                    log.debug("Add3 %s failed: %s", key, traceback.format_exc())
                if not ok:
                    try:
                        cpm.Set2(key, text)
                        ok = True
                    except Exception:
                        try:
                            cpm.Set(key, text)
                            ok = True
                        except Exception:
                            log.debug("Set property %s failed: %s", key, traceback.format_exc())
                if ok:
                    written[key] = text
            if not written and props:
                raise fail(
                    "FEATURE_CREATE_FAILED",
                    "Failed to write any custom properties",
                    "Confirm part/assembly custom properties are writable",
                )
            return written

        return self._call(_fn)

    def get_properties(self, keys: list[str] | None = None) -> dict:
        def _fn() -> dict:
            doc = self.sw.ActiveDoc
            self._require_part_or_assembly(doc, "Open or create a part/assembly first")
            if keys:
                want = [normalize_property_key(str(k)) for k in keys if str(k).strip()]
            else:
                want = list(PART_PROP_DEFAULT_KEYS)
            return self._read_custom_props(doc, want)

        return self._call(_fn)
