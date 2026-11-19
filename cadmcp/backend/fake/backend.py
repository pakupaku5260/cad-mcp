"""Fake backend · composition class（S8i）。

`FakeBackend` = MRO of 18 domain Mixins + cross-cutting methods (`__init__` / `_enter` /
`calls_named` / `call_names` / `_require_doc` / `_doc_info` / `revision`）。

Dependencies:
- `_state` / `protocol.models` / `errors`
- 18 domain Mixins (document / sketch / plane_axis / query / selection / view /
  features.* / assembly.*）

State ownership (S8i unchanged, all in `FakeBackend.__init__`):
- Infra: `_fail_on` / `_rebuild_errors` / `_revision` / `calls` / `_counts`
- Documents: `_doc` / `_part_seq` / `_asm_seq` / `_draw_seq`
- Part libraries: `_part_library` / `_assembly_library`
- Selection: `gui_selection`
- In-context edit: `_edit_component`

`_init_state` chain calls each Mixin in §4.3.1 order (all `pass` for now; S8i wires order only).
"""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from cadmcp.backend.protocol.models import DocInfo, EdgeRef, FaceRef
from cadmcp.errors import SideEffect, fail

from ._engine import (
    _ray_hit_t,
    _reflect_point,
    _reflect_xy,
    _reflected_bbox,
    _rodrigues,
    _rotate_point,
    _rotated_bbox,
    _rotation_aligning,
    _vec_cross,
    _vec_dot,
    _vec_len,
    _vec_unit,
)
from ._state import _Doc
from .assembly.component import FakeAssemblyComponentMixin
from .assembly.explode import FakeAssemblyExplodeMixin
from .assembly.mate import FakeAssemblyMateMixin
from .assembly.query import FakeAssemblyQueryMixin
from .document import FakeDocumentMixin
from .features.extrude import FakeExtrudeMixin
from .features.helix import FakeHelixMixin
from .features.loft import FakeLoftMixin
from .features.manage import FakeFeatureManageMixin
from .features.modify import FakeModifyMixin
from .features.revolve import FakeRevolveMixin
from .features.sheetmetal import FakeSheetMetalMixin
from .features.surface import FakeSurfaceMixin
from .plane_axis import FakePlaneAxisMixin
from .query import FakeQueryMixin
from .selection import FakeSelectionMixin
from .sketch import FakeSketchMixin
from .view import FakeViewMixin


class FakeBackend(
    FakeDocumentMixin,
    FakeAssemblyComponentMixin,
    FakeAssemblyMateMixin,
    FakeAssemblyExplodeMixin,
    FakeAssemblyQueryMixin,
    FakeSketchMixin,
    FakePlaneAxisMixin,
    FakeExtrudeMixin,
    FakeRevolveMixin,
    FakeFeatureManageMixin,
    FakeModifyMixin,
    FakeLoftMixin,
    FakeHelixMixin,
    FakeSurfaceMixin,
    FakeSheetMetalMixin,
    FakeSelectionMixin,
    FakeQueryMixin,
    FakeViewMixin,
):
    """In-memory CADBackend implementation. Constructor: fail_on fault injection, rebuild_errors simulate failed rebuild."""

    # S8b: pure geometry in fake/_engine.py, exposed as class attrs for self._xxx
    _reflect_xy = staticmethod(_reflect_xy)
    _ray_hit_t = staticmethod(_ray_hit_t)
    _reflect_point = staticmethod(_reflect_point)
    _reflected_bbox = staticmethod(_reflected_bbox)
    _rotate_point = staticmethod(_rotate_point)
    _rotated_bbox = staticmethod(_rotated_bbox)
    _vec_len = staticmethod(_vec_len)
    _vec_unit = staticmethod(_vec_unit)
    _vec_dot = staticmethod(_vec_dot)
    _vec_cross = staticmethod(_vec_cross)
    _rodrigues = staticmethod(_rodrigues)
    _rotation_aligning = staticmethod(_rotation_aligning)

    def __init__(
        self,
        *,
        fail_on: Sequence[tuple[str, int]] | None = None,
        rebuild_errors: Sequence[str] | None = None,
        revision: str = "33.0",
        interference_volume_m3: float | None = None,
    ) -> None:
        # Infra state (FakeBackend itself, not Mixin)
        self._fail_on: set[tuple[str, int]] = set(fail_on or ())
        self._rebuild_errors: list[str] = list(rebuild_errors or ())
        self._revision = revision
        self.calls: list[tuple[str, dict]] = []
        self._counts: dict[str, int] = {}
        self._doc: _Doc | None = None
        self._docs: list[_Doc] = []
        self._part_seq = 0
        self._asm_seq = 0
        self._draw_seq = 0
        self._part_library: dict[str, tuple] = {}
        self._assembly_library: dict[str, list[dict]] = {}
        self.gui_selection: list[FaceRef | EdgeRef] = []
        self._edit_component: str | None = None
        self._tx_checkpoints: dict[str, _Doc] = {}
        # F5 COM_LOST / reattach simulation
        self._com_lost = False
        self._had_session = True
        self._unsaved_at_disconnect = False
        self._sw_available = True
        self._disconnect_mid_call = False
        self._last_doc_snapshot: dict | None = None
        # AP242 / MBD: default True so offline tests can exercise PublishSTEP242File path
        self._mbd_step242 = True
        # P5: optional SI volume attached to every non-clear interference pair
        self._interference_volume_m3 = interference_volume_m3
        # P5: STEP readback fixtures keyed by resolved path
        self._step_imports: dict[str, dict] = {}

        # Each Mixin _init_state (all pass for now; S8i wires order only)
        for mixin in (
            FakeDocumentMixin,
            FakeAssemblyComponentMixin,
            FakeAssemblyMateMixin,
            FakeAssemblyExplodeMixin,
            FakeAssemblyQueryMixin,
            FakeSketchMixin,
            FakePlaneAxisMixin,
            FakeExtrudeMixin,
            FakeRevolveMixin,
            FakeFeatureManageMixin,
            FakeModifyMixin,
            FakeLoftMixin,
            FakeHelixMixin,
            FakeSurfaceMixin,
            FakeSheetMetalMixin,
            FakeSelectionMixin,
            FakeQueryMixin,
            FakeViewMixin,
        ):
            mixin._init_state(self)

    # ---------- Test helpers ----------

    def calls_named(self, name: str) -> list[dict]:
        return [args for (meth, args) in self.calls if meth == name]

    def call_names(self) -> list[str]:
        return [meth for (meth, _) in self.calls]

    # ---------- Call entry ----------

    def _enter(self, tool: str, **args) -> None:
        if self._com_lost:
            raise self._com_lost_error(mid_call=False)
        clean = {k: (str(v) if isinstance(v, Path) else v) for k, v in args.items()}
        self.calls.append((tool, clean))
        self._counts[tool] = self._counts.get(tool, 0) + 1
        if (tool, self._counts[tool]) in self._fail_on:
            raise fail(
                "COM_CALL_FAILED",
                f"Injected fault: {tool} call #{self._counts[tool]} blocked by fail_on (not executed)",
                "Read model state (e.g. get_mass_properties) to confirm no side effects, then decide whether to retry",
                side_effect=SideEffect.APPLIED,
                injected=True,
                method=tool,
            )

    def _require_doc(self) -> _Doc:
        if self._com_lost:
            raise self._com_lost_error(mid_call=False)
        if self._doc is None:
            raise fail(
                "NO_ACTIVE_DOCUMENT",
                "No active document",
                "Call new_part to create a part, or open_document to open a file",
            )
        return self._doc

    def _doc_info(self, doc: _Doc | None = None) -> DocInfo:
        target = doc if doc is not None else self._require_doc()
        configuration = "" if target.doc_type == "drawing" else str(target.active_config or "")
        info = DocInfo(
            title=target.title,
            path=target.path,
            doc_type=target.doc_type,
            modified=target.modified,
            configuration=configuration,
            epoch=str(target.generation),
            saved=target.path is not None,
        )
        if doc is None or doc is self._doc:
            self._last_doc_snapshot = {
                "title": info.title,
                "path": info.path,
                "modified": info.modified,
            }
        return info

    def _register_open_doc(self, doc: _Doc) -> None:
        """Append and activate (multi-doc); keeps prior opens unless closed."""
        self._docs.append(doc)
        self._doc = doc
        self._edit_component = None

    def list_open_documents(self) -> list[DocInfo]:
        self._enter("list_open_documents")
        return [self._doc_info(d) for d in list(self._docs)]

    def _com_lost_error(self, *, mid_call: bool):
        hint = (
            "Restart SolidWorks if it has exited, then retry the same call "
            "(do not restart the cadmcp server; it will reattach)."
        )
        if self._unsaved_at_disconnect:
            hint += (
                " Unsaved document changes were likely lost; use open_document or new_part—"
                "nothing is auto-reopened."
            )
        if mid_call:
            hint += " Do not blindly retry a write: verify model/document state first."
        return fail(
            "COM_LOST",
            "SolidWorks COM connection was lost (process exited or RPC disconnected)",
            hint,
            side_effect=SideEffect.UNKNOWN if mid_call else SideEffect.NONE,
            recoverable=True,
            unsaved_at_disconnect=self._unsaved_at_disconnect,
            mid_call=mid_call,
        )

    def simulate_disconnect(self, *, mid_call: bool = False, lose_document: bool = True) -> None:
        """Test helper: mark COM lost. Optionally drop in-memory doc (process exit)."""
        snap = self._last_doc_snapshot
        if self._doc is not None:
            snap = {
                "title": self._doc.title,
                "path": self._doc.path,
                "modified": self._doc.modified,
            }
            self._last_doc_snapshot = snap
        if snap and (snap.get("modified") or not snap.get("path")):
            self._unsaved_at_disconnect = True
        self._com_lost = True
        if lose_document:
            self._doc = None
            self._edit_component = None
        if mid_call:
            # Surface as mid-call style error when next accessed via raise helper
            self._disconnect_mid_call = True
        else:
            self._disconnect_mid_call = False

    def reattach(self) -> dict:
        """Rebuild connection after simulate_disconnect. Does not restore lost documents."""
        self.calls.append(("reattach", {}))
        if not self._sw_available:
            raise fail(
                "SW_NOT_RUNNING",
                "Cannot reattach: SolidWorks is not running",
                "Start SolidWorks, then retry the tool call (server need not restart)",
                side_effect=SideEffect.NONE,
                unsaved_at_disconnect=self._unsaved_at_disconnect,
            )
        self._com_lost = False
        self._had_session = True
        self._disconnect_mid_call = False
        return {
            "reattached": True,
            "unsaved_at_disconnect": self._unsaved_at_disconnect,
            "sta_restarted": False,
        }

    # ---------- Connection / version ----------

    def revision(self) -> str:
        if getattr(self, "_disconnect_mid_call", False) and self._com_lost:
            raise self._com_lost_error(mid_call=True)
        self._enter("revision")
        return self._revision
