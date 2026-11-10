"""COM backend · business infrastructure (business-side facade for sta).

Contains:
- COMConnectionMixin: ``sw`` state (COM connection state owner)
- InfrastructureMixin: template lookup, doc_info, active-document switching, etc.

Constraints (v1.2.2 §2.1 / §4.5):
- This module is the **sole** business-side wrapper around sta.py
- Must not depend backward on business mixins or backend.py
"""
from __future__ import annotations

import logging
import traceback
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from cadmcp.backend.protocol.models import DocInfo
from cadmcp.errors import SideEffect, fail

from ._constants import (
    _DONT_REBUILD_ON_ACTIVATION,
    SW_DOC_ASSEMBLY,
    SW_DOC_DRAWING,
    SW_DOC_PART,
    SW_DOC_TYPE_NAMES,
    SW_PREF_TEMPLATE_FOLDER,
)
from ._helpers import _get, _is_server_gone

log = logging.getLogger(__name__)

# BOM standard table: prefer Chinese locale then English; other lang/* sorted by name (no hardcoded PF paths)
_BOM_LANG_PREF: tuple[str, ...] = (
    "chinese-simplified",
    "english",
    "chinese",
    "french",
    "german",
    "japanese",
    "korean",
)


def discover_solidworks_install_roots() -> list[Path]:
    """Read ``SolidWorks Folder`` per version from registry (portable; no COM)."""
    roots: list[Path] = []
    seen: set[str] = set()
    try:
        import winreg
    except ImportError:
        return roots

    key_paths = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\SolidWorks"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\SolidWorks"),
    )
    for hive, base in key_paths:
        try:
            sw_key = winreg.OpenKey(hive, base)
        except OSError:
            continue
        try:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(sw_key, i)
                except OSError:
                    break
                i += 1
                if not sub.upper().startswith("SOLIDWORKS"):
                    continue
                try:
                    with winreg.OpenKey(sw_key, rf"{sub}\Setup") as setup:
                        folder, _typ = winreg.QueryValueEx(setup, "SolidWorks Folder")
                except OSError:
                    continue
                path = Path(str(folder))
                try:
                    key = str(path.resolve())
                except OSError:
                    key = str(path)
                if key in seen or not path.is_dir():
                    continue
                seen.add(key)
                roots.append(path)
        finally:
            winreg.CloseKey(sw_key)
    return roots


def bom_templates_under_install(root: Path) -> list[Path]:
    """``{install}/lang/<locale>/bom-standard.sldbomtbt``, ordered by language preference."""
    lang_root = root / "lang"
    if not lang_root.is_dir():
        return []
    found: dict[str, Path] = {}
    try:
        children = list(lang_root.iterdir())
    except OSError:
        return []
    for child in children:
        if not child.is_dir():
            continue
        candidate = child / "bom-standard.sldbomtbt"
        if candidate.is_file():
            found[child.name.lower()] = candidate
    ordered: list[Path] = []
    for pref in _BOM_LANG_PREF:
        hit = found.pop(pref, None)
        if hit is not None:
            ordered.append(hit)
    ordered.extend(found[k] for k in sorted(found))
    return ordered


def discover_bom_standard_templates(*, extra_roots: Sequence[Path] = ()) -> list[Path]:
    """Merge extra_roots (e.g. GetExecutablePath parent) with registry install roots; dedupe template paths."""
    roots: list[Path] = []
    seen_roots: set[str] = set()
    for root in (*extra_roots, *discover_solidworks_install_roots()):
        try:
            key = str(root.resolve())
        except OSError:
            key = str(root)
        if key in seen_roots or not root.is_dir():
            continue
        seen_roots.add(key)
        roots.append(root)

    out: list[Path] = []
    seen_tpl: set[str] = set()
    for root in roots:
        for tpl in bom_templates_under_install(root):
            try:
                key = str(tpl.resolve())
            except OSError:
                key = str(tpl)
            if key in seen_tpl:
                continue
            seen_tpl.add(key)
            out.append(tpl)
    return out


class COMConnectionMixin:
    """COM connection state (owner of ``sw``)."""

    def _init_state(self) -> None:
        self.sw: Any = None


class InfrastructureMixin:
    """Business infrastructure: template resolution, doc_info, active document switching.

    These methods use ``self.sw`` but **do not depend on any business mixin**.
    """

    def _init_state(self) -> None:
        pass  # stateless

    def _template_folder(self) -> Path | None:
        try:
            raw = self.sw.GetUserPreferenceStringValue(SW_PREF_TEMPLATE_FOLDER) or ""
        except Exception:
            return None
        folder = Path(raw) if raw else None
        return folder if folder is not None and folder.is_dir() else None

    def _resolve_template(self, template: str | None) -> str:
        if template:
            candidate = Path(template)
            if candidate.is_file():
                return str(candidate)
            folder = self._template_folder()
            if folder is not None:
                local = folder / template
                if local.is_file():
                    return str(local)
            return template  # let SolidWorks resolve by name

        try:
            tpl = self.sw.GetDocumentTemplate(SW_DOC_PART, "", 0, 0, 0)
            if tpl and Path(tpl).is_file():
                return str(tpl)
        except Exception:
            pass

        folder = self._template_folder()
        if folder is not None:
            for name in ("gb_part.prtdot", "Part.prtdot", "\u96f6\u4ef6.prtdot"):
                candidate = folder / name
                if candidate.is_file():
                    return str(candidate)
            try:
                for candidate in sorted(folder.glob("*.prtdot")):
                    if candidate.is_file():
                        return str(candidate)
            except OSError:
                pass
        raise fail(
            "OPEN_FAILED",
            "No usable part template found",
            "Check SolidWorks template paths (User Preferences) or pass template= explicitly (.prtdot)",
            side_effect=SideEffect.NONE,
        )

    def _doc_info(self, doc: Any, doc_type: str | None = None) -> DocInfo:
        title = str(_get(doc, "GetTitle"))
        try:
            path = _get(doc, "GetPathName") or None
        except Exception as exc:
            if _is_server_gone(exc):
                raise
            path = None
        try:
            modified = bool(_get(doc, "GetSaveFlag"))
        except Exception as exc:
            if _is_server_gone(exc):
                raise
            # modified = False
            modified = True  # if unreadable, assume modified — prefer extra save prompt over data loss

        if doc_type is None:
            try:
                doc_type = SW_DOC_TYPE_NAMES.get(int(_get(doc, "GetType")), "part")
            except Exception:
                doc_type = "part"
        return DocInfo(title=title, path=path, doc_type=doc_type, modified=modified)

    def _resolve_drawing_template(self, template: str | None) -> str:
        if template:
            candidate = Path(template)
            if candidate.is_file():
                return str(candidate)
            folder = self._template_folder()
            if folder is not None:
                local = folder / template
                if local.is_file():
                    return str(local)
            return template
        try:
            tpl = self.sw.GetDocumentTemplate(SW_DOC_DRAWING, "", 0, 0, 0)
            if tpl and Path(tpl).is_file():
                return str(tpl)
        except Exception:
            pass
        folder = self._template_folder()
        names = ("\u5de5\u7a0b\u56fe.drwdot", "gb_drawing.drwdot", "Drawing.drwdot", "drawing.drwdot")
        search: list[Path] = []
        if folder is not None:
            search.append(folder)
        search.extend(
            Path(p)
            for p in (
                r"C:\ProgramData\SolidWorks\SOLIDWORKS 2025\templates",
                r"C:\ProgramData\SolidWorks\SOLIDWORKS 2024\templates",
            )
        )
        seen: set[Path] = set()
        for directory in search:
            if directory in seen or not directory.is_dir():
                continue
            seen.add(directory)
            for name in names:
                candidate = directory / name
                if candidate.is_file():
                    return str(candidate)
            try:
                for candidate in sorted(directory.glob("*.drwdot")):
                    if candidate.is_file():
                        return str(candidate)
            except OSError:
                pass
        raise fail(
            "OPEN_FAILED",
            "No usable drawing template found",
            "Check SolidWorks template paths or pass template= (.drwdot)",
            side_effect=SideEffect.NONE,
        )

    def _resolve_bom_template(self) -> str:
        """Resolve ``bom-standard.sldbomtbt``: GetExecutablePath install root → registry SolidWorks Folder → lang/*."""
        extra: list[Path] = []
        try:
            exe = str(_get(self.sw, "GetExecutablePath") or "").strip()
            if exe:
                extra.append(Path(exe).resolve().parent)
        except Exception:
            log.debug("GetExecutablePath failed: %s", traceback.format_exc())
        templates = discover_bom_standard_templates(extra_roots=extra)
        if templates:
            return str(templates[0])
        raise fail(
            "INVALID_ARGUMENT",
            "BOM table template not found (bom-standard.sldbomtbt)",
            "Confirm SolidWorks install has lang/<locale>/bom-standard.sldbomtbt",
        )

    def _ensure_active(self, doc: Any, title: str) -> None:
        """Ensure doc is active (OpenDoc when inserting components steals focus to the part window)."""
        try:
            active = self.sw.ActiveDoc
            if active is not None and str(_get(active, "GetTitle")) == title:
                return
        except Exception:
            log.debug("Read active document failed: %s", traceback.format_exc())
        import pythoncom
        from win32com.client import VARIANT

        err = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        attempts = (
            lambda: self.sw.ActivateDoc3(title, False, _DONT_REBUILD_ON_ACTIVATION, err),
            lambda: self.sw.ActivateDoc2(title, True, err),
        )
        for activate in attempts:
            try:
                activate()
            except Exception:
                log.debug("Activate document %r failed: %s", title, traceback.format_exc())
                continue
            active = self.sw.ActiveDoc
            if active is not None and str(_get(active, "GetTitle")) == title:
                return
        raise self._com_failed(
            f"Component inserted but could not restore focus to assembly {title}",
            "Manually switch back to the assembly window in SolidWorks, then continue",
            side_effect=SideEffect.APPLIED,
        )

    def _model_doc(self, *, part_only: bool = False) -> Any:
        doc = self.sw.ActiveDoc
        if doc is None:
            raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a document first")
        try:
            doc_type = int(_get(doc, "GetType"))
        except Exception:
            doc_type = 0
        if doc_type == SW_DOC_DRAWING:
            raise fail(
                "INVALID_ARGUMENT",
                "Drawings have no model configuration or material",
                "Operate on a part or assembly",
            )
        if part_only and doc_type != SW_DOC_PART:
            raise fail("INVALID_ARGUMENT", "Material can only be set or read on a part", "Open or create a part first")
        return doc

    def _require_assembly_doc(self, doc: Any, hint: str) -> None:
        if doc is None:
            raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create an assembly first")
        try:
            doc_type = int(_get(doc, "GetType"))
        except Exception:
            doc_type = 0
        if doc_type != SW_DOC_ASSEMBLY:
            raise fail("INVALID_ARGUMENT", "Active document is not an assembly", hint)

    def _require_part_doc(self, doc: Any, hint: str) -> None:
        if doc is None:
            raise fail("NO_ACTIVE_DOCUMENT", "No active document", "Create or open a part first")
        try:
            doc_type = int(_get(doc, "GetType"))
        except Exception:
            doc_type = 0
        if doc_type != SW_DOC_PART:
            raise fail("INVALID_ARGUMENT", "Active document is not a part", hint)
