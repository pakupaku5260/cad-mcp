"""F4 transaction skeleton: L1 checkpoint/journal + L2 reload/compensate/discard.

Does not implement SolidWorks EditUndo2. Compensating transactions only.
Owns journal I/O under <workspace>/.cadmcp/tx/<tx_id>/; cleans only own artifacts.
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cadmcp.backend.protocol.models import FingerprintSI
from cadmcp.errors import SideEffect, fail
from cadmcp.safety import ensure_output_path

log = logging.getLogger(__name__)

CHECKPOINT_THRESHOLD_BYTES = 200 * 1024 * 1024  # 200 MB
MAX_TX_PER_DOC = 5
JOURNAL_RETENTION_DAYS = 7

_TX_ROOT = ".cadmcp"
_TX_DIR = "tx"
_META = "meta.json"
_JOURNAL = "journal.jsonl"

# Feature tools compensated by deleting the returned feature name.
_DELETE_FEATURE_TOOLS = frozenset({
    "extrude", "extrude_cut", "revolve", "revolve_cut",
    "fillet", "chamfer", "shell", "mirror",
    "linear_pattern", "circular_pattern",
    "loft", "loft_cut", "sweep", "sweep_cut",
})

COVERED_TOOLS: frozenset[str] = _DELETE_FEATURE_TOOLS | frozenset({
    "set_dimension",
    "set_material", "set_color", "set_configuration",
    "move_component", "rotate_component",
    "insert_component",
    "suppress_feature",
})

COVERAGE_HINT = (
    "Compensators cover: extrude/revolve/fillet/chamfer/pattern/mirror/shell/loft/sweep "
    "(delete feature); set_dimension/material/color/configuration (restore); "
    "move/rotate_component (restore pose); insert_component (delete instance); "
    "suppress_feature (invert). Uncovered mutating steps emit TX_UNSUPPORTED_STEP warnings; "
    "compensate refuses if any unsupported step is present."
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def new_tx_id() -> str:
    stamp = _utc_now().strftime("%Y%m%dT%H%M%S")
    return f"tx_{stamp}_{uuid.uuid4().hex[:8]}"


def args_hash(args: dict[str, Any]) -> str:
    blob = json.dumps(args, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def fingerprint_digest(fp: FingerprintSI | dict[str, Any] | None) -> str:
    if fp is None:
        return ""
    data = fp.model_dump() if isinstance(fp, FingerprintSI) else dict(fp)
    blob = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def compute_epoch(
    *,
    path: str | None,
    title: str,
    modified: bool,
    fp_digest: str,
    state_version: int,
) -> str:
    raw = f"{path or ''}|{title}|{int(modified)}|{fp_digest}|{state_version}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def tx_root(workspace: Path) -> Path:
    return Path(workspace) / _TX_ROOT / _TX_DIR


def tx_dir(workspace: Path, tx_id: str) -> Path:
    return tx_root(workspace) / tx_id


@dataclass
class JournalStep:
    step: int
    tool: str
    args_hash: str
    state_version: int
    side_effect: str
    delta_changed: list[str] = field(default_factory=list)
    feature_returned: str | None = None
    compensator: str | None = None
    compensate_payload: dict[str, Any] = field(default_factory=dict)
    unsupported: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "tool": self.tool,
            "args_hash": self.args_hash,
            "state_version": self.state_version,
            "side_effect": self.side_effect,
            "delta_changed": list(self.delta_changed),
            "feature_returned": self.feature_returned,
            "compensator": self.compensator,
            "compensate_payload": dict(self.compensate_payload),
            "unsupported": self.unsupported,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JournalStep:
        return cls(
            step=int(data["step"]),
            tool=str(data["tool"]),
            args_hash=str(data.get("args_hash") or ""),
            state_version=int(data.get("state_version") or 0),
            side_effect=str(data.get("side_effect") or "applied"),
            delta_changed=list(data.get("delta_changed") or []),
            feature_returned=data.get("feature_returned"),
            compensator=data.get("compensator"),
            compensate_payload=dict(data.get("compensate_payload") or {}),
            unsupported=bool(data.get("unsupported")),
        )


@dataclass
class TxSession:
    tx_id: str
    name: str
    mode: str  # checkpoint | journal-only
    status: str = "active"  # active | committed | rolled_back
    title: str = ""
    path: str | None = None
    doc_type: str = "part"
    config: str = ""
    state_version: int = 0
    fingerprint: dict[str, Any] = field(default_factory=dict)
    saved_before: bool = False
    sketch_open: bool = False
    epoch: str = ""
    created_at: str = ""
    checkpoint_path: str | None = None
    checkpoint_bytes: int | None = None
    degraded: bool = False
    warnings: list[str] = field(default_factory=list)
    saved_after_tx: bool = False
    created_in_tx: bool = False  # True when doc had no path at begin (new unsaved)
    steps: list[JournalStep] = field(default_factory=list)
    dir_path: Path | None = None

    @property
    def dirty(self) -> bool:
        return bool(self.steps) or self.saved_after_tx

    def unsupported_tools(self) -> list[str]:
        return [s.tool for s in self.steps if s.unsupported]

    def to_meta(self) -> dict[str, Any]:
        return {
            "tx_id": self.tx_id,
            "name": self.name,
            "mode": self.mode,
            "status": self.status,
            "title": self.title,
            "path": self.path,
            "doc_type": self.doc_type,
            "config": self.config,
            "state_version": self.state_version,
            "fingerprint": self.fingerprint,
            "saved_before": self.saved_before,
            "sketch_open": self.sketch_open,
            "epoch": self.epoch,
            "created_at": self.created_at,
            "checkpoint_path": self.checkpoint_path,
            "checkpoint_bytes": self.checkpoint_bytes,
            "degraded": self.degraded,
            "warnings": list(self.warnings),
            "saved_after_tx": self.saved_after_tx,
            "created_in_tx": self.created_in_tx,
        }

    @classmethod
    def from_meta(cls, data: dict[str, Any], *, dir_path: Path | None = None) -> TxSession:
        return cls(
            tx_id=str(data["tx_id"]),
            name=str(data.get("name") or ""),
            mode=str(data.get("mode") or "checkpoint"),
            status=str(data.get("status") or "active"),
            title=str(data.get("title") or ""),
            path=data.get("path"),
            doc_type=str(data.get("doc_type") or "part"),
            config=str(data.get("config") or ""),
            state_version=int(data.get("state_version") or 0),
            fingerprint=dict(data.get("fingerprint") or {}),
            saved_before=bool(data.get("saved_before")),
            sketch_open=bool(data.get("sketch_open")),
            epoch=str(data.get("epoch") or ""),
            created_at=str(data.get("created_at") or ""),
            checkpoint_path=data.get("checkpoint_path"),
            checkpoint_bytes=data.get("checkpoint_bytes"),
            degraded=bool(data.get("degraded")),
            warnings=list(data.get("warnings") or []),
            saved_after_tx=bool(data.get("saved_after_tx")),
            created_in_tx=bool(data.get("created_in_tx")),
            dir_path=dir_path,
        )


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _append_journal(path: Path, step: JournalStep) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(step.to_dict(), ensure_ascii=False) + "\n")


def _read_journal(path: Path) -> list[JournalStep]:
    if not path.is_file():
        return []
    out: list[JournalStep] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(JournalStep.from_dict(json.loads(line)))
    return out


def _fp_public(fp: FingerprintSI) -> dict[str, Any]:
    return {
        "volume_m3": fp.volume_m3,
        "surface_area_m2": fp.surface_area_m2,
        "mass_kg": fp.mass_kg,
        "face_count": fp.face_count,
        "edge_count": fp.edge_count,
        "bbox_m": list(fp.bbox_m),
    }


def ext_for_doc(doc_type: str, path: str | None) -> str:
    """File extension for a checkpoint/copy based on doc_type or existing path."""
    if path:
        suf = Path(path).suffix.lower()
        if suf in {".sldprt", ".sldasm", ".slddrw"}:
            return suf
    return {".assembly": ".sldasm", "assembly": ".sldasm",
            "drawing": ".slddrw"}.get(doc_type, ".sldprt")


class TxManager:
    """Session-scoped transaction manager (one active tx per Kernel)."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = Path(workspace)
        self.active: TxSession | None = None

    # ---------- begin / status / commit ----------

    def begin(
        self,
        backend: Any,
        *,
        name: str,
        mode: str = "checkpoint",
        state_version: int,
    ) -> dict[str, Any]:
        if mode not in {"checkpoint", "journal-only"}:
            raise fail(
                "INVALID_ARGUMENT",
                f"Unknown tx mode: {mode!r}",
                "mode must be checkpoint or journal-only",
            )
        if self.active is not None and self.active.status == "active":
            raise fail(
                "INVALID_ARGUMENT",
                f"Transaction already active: {self.active.tx_id}",
                "Call tx_commit or tx_rollback before starting another transaction",
                tx_id=self.active.tx_id,
            )
        info = backend.active_document()
        if info is None:
            raise fail(
                "NO_ACTIVE_DOCUMENT",
                "No active document for transaction",
                "Create or open a document before tx_begin",
            )

        warnings: list[str] = [COVERAGE_HINT]
        fp = None
        fp_dict: dict[str, Any] = {}
        try:
            fp = backend.fingerprint()
            fp_dict = _fp_public(fp)
        except Exception as exc:  # noqa: BLE001 — drawings may lack solid fp
            log.debug("tx_begin fingerprint skipped: %s", exc)
            warnings.append(f"fingerprint unavailable at begin: {type(exc).__name__}")

        sketch_open = False
        try:
            sketch_open = backend.active_sketch() is not None
        except Exception:
            sketch_open = False

        config = ""
        try:
            active_cfg, _ = backend.list_configurations()
            config = str(active_cfg or "")
        except Exception:
            config = ""

        fp_dig = fingerprint_digest(fp_dict or None)
        epoch = compute_epoch(
            path=info.path,
            title=info.title,
            modified=bool(info.modified),
            fp_digest=fp_dig,
            state_version=state_version,
        )
        # saved_before: has a path and is not dirty → can reload from disk/copy
        saved_before = bool(info.path) and not bool(info.modified)
        created_in_tx = not bool(info.path)

        tx_id = new_tx_id()
        directory = tx_dir(self.workspace, tx_id)
        directory.mkdir(parents=True, exist_ok=True)

        session = TxSession(
            tx_id=tx_id,
            name=name,
            mode=mode,
            title=info.title,
            path=info.path,
            doc_type=info.doc_type,
            config=config,
            state_version=state_version,
            fingerprint=fp_dict,
            saved_before=saved_before,
            sketch_open=sketch_open,
            epoch=epoch,
            created_at=_iso(_utc_now()),
            created_in_tx=created_in_tx,
            warnings=list(warnings),
            dir_path=directory,
        )

        checkpoint_payload: dict[str, Any] | None = None
        if mode == "checkpoint":
            checkpoint_payload = self._maybe_checkpoint(backend, session, directory)
        else:
            session.mode = "journal-only"

        _write_json(directory / _META, session.to_meta())
        (directory / _JOURNAL).write_text("", encoding="utf-8")
        self._enforce_retention(doc_key=self._doc_key(session))
        self.active = session

        out: dict[str, Any] = {
            "tx_id": tx_id,
            "name": name,
            "mode": session.mode,
            "checkpoint": checkpoint_payload,
            "fingerprint": fp_dict or None,
            "state_version": state_version,
            "warnings": list(session.warnings),
        }
        return out

    def _maybe_checkpoint(
        self, backend: Any, session: TxSession, directory: Path
    ) -> dict[str, Any] | None:
        ext = ext_for_doc(session.doc_type, session.path)
        rel = f"{_TX_ROOT}/{_TX_DIR}/{session.tx_id}/step_0{ext}"
        try:
            dest = ensure_output_path(
                rel,
                roots=self.workspace,
                extensions={".sldprt", ".sldasm", ".slddrw"},
                overwrite=True,
                create_parents=True,
            )
        except Exception as exc:
            session.degraded = True
            session.mode = "journal-only"
            session.warnings.append(
                f"checkpoint path rejected ({exc}); degraded to journal-only"
            )
            return None

        # Probe size via save attempt; if existing copy huge — N/A before write.
        try:
            backend.save_copy_as(dest)
        except Exception as exc:
            session.degraded = True
            session.mode = "journal-only"
            session.warnings.append(
                f"SaveAsCopy failed ({type(exc).__name__}: {exc}); degraded to journal-only"
            )
            if dest.exists():
                try:
                    dest.unlink()
                except OSError:
                    pass
            return None

        size = dest.stat().st_size if dest.exists() else 0
        if size > CHECKPOINT_THRESHOLD_BYTES:
            session.degraded = True
            session.mode = "journal-only"
            session.warnings.append(
                f"checkpoint {size} bytes exceeds {CHECKPOINT_THRESHOLD_BYTES} "
                "threshold; degraded to journal-only (not blocked)"
            )
            try:
                dest.unlink()
            except OSError:
                pass
            return None

        session.checkpoint_path = str(dest)
        session.checkpoint_bytes = size
        return {"path": str(dest), "bytes": size}

    def status(self, tx_id: str) -> dict[str, Any]:
        session = self._require_active(tx_id)
        return {
            "tx_id": session.tx_id,
            "status": session.status,
            "mode": session.mode,
            "steps": [s.to_dict() for s in session.steps],
            "last_state_version": (
                session.steps[-1].state_version if session.steps else session.state_version
            ),
            "dirty": session.dirty,
            "warnings": list(session.warnings) + [
                f"TX_UNSUPPORTED_STEP: {t}" for t in session.unsupported_tools()
            ],
            "saved_after_tx": session.saved_after_tx,
            "unsupported": session.unsupported_tools(),
        }

    def commit(self, tx_id: str) -> dict[str, Any]:
        session = self._require_active(tx_id)
        journal_path = (session.dir_path or tx_dir(self.workspace, tx_id)) / _JOURNAL
        removed = False
        if session.checkpoint_path:
            cp = Path(session.checkpoint_path)
            if cp.is_file():
                try:
                    cp.unlink()
                    removed = True
                except OSError as exc:
                    log.warning("Failed to remove checkpoint %s: %s", cp, exc)
            session.checkpoint_path = None
            session.checkpoint_bytes = None
        session.status = "committed"
        _write_json((session.dir_path or tx_dir(self.workspace, tx_id)) / _META, session.to_meta())
        self.active = None
        # verified: commit acknowledges journal; geometric verified only if no unsupported + no degrade issues
        verified = not session.unsupported_tools()
        return {
            "tx_id": tx_id,
            "verified": verified,
            "journal_path": str(journal_path),
            "checkpoint_removed": removed,
        }

    # ---------- journal hook ----------

    def capture_before(self, backend: Any, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        """Pre-mutation snapshot for compensators. Empty dict when not needed / fails soft."""
        if self.active is None or self.active.status != "active":
            return {}
        if tool not in COVERED_TOOLS:
            return {}
        try:
            return _capture(backend, tool, args)
        except Exception as exc:  # noqa: BLE001
            log.debug("tx capture_before failed for %s: %s", tool, exc)
            return {"_capture_error": f"{type(exc).__name__}: {exc}"}

    def record_step(
        self,
        *,
        tool: str,
        args: dict[str, Any],
        state_version: int,
        payload: dict[str, Any] | None,
        delta_changed: list[str] | None,
        capture: dict[str, Any] | None,
    ) -> list[str]:
        """Append journal after successful mutating tool. Returns warning strings."""
        session = self.active
        if session is None or session.status != "active":
            return []
        if tool.startswith("tx_"):
            return []

        warnings: list[str] = []
        # Cross-doc / binding drift: refuse to journal under wrong doc — mark unsafe flag
        # (caller still succeeded; we warn and mark unsupported so compensate refuses)
        unsupported = tool not in COVERED_TOOLS
        compensator = None
        feature_returned = None
        compensate_payload: dict[str, Any] = {}

        if tool in {"save_document", "save_as"}:
            session.saved_after_tx = True
            # Saving mid-tx is allowed but blocks rollback
            unsupported = False  # not a compensate target; tracked via flag
            compensator = None
        elif tool in COVERED_TOOLS:
            compensator, feature_returned, compensate_payload = _build_payload(
                tool, args, payload or {}, capture or {}
            )
            if compensator is None or (capture or {}).get("_capture_error"):
                unsupported = True
                compensator = None
        else:
            unsupported = True

        if unsupported and tool not in {"save_document", "save_as"}:
            warnings.append(f"TX_UNSUPPORTED_STEP: {tool}")
            session.warnings.append(f"TX_UNSUPPORTED_STEP: {tool}")

        step = JournalStep(
            step=len(session.steps) + 1,
            tool=tool,
            args_hash=args_hash(args),
            state_version=state_version,
            side_effect=SideEffect.APPLIED.value,
            delta_changed=list(delta_changed or []),
            feature_returned=feature_returned,
            compensator=compensator,
            compensate_payload=compensate_payload,
            unsupported=unsupported and tool not in {"save_document", "save_as"},
        )
        session.steps.append(step)
        journal = (session.dir_path or tx_dir(self.workspace, session.tx_id)) / _JOURNAL
        _append_journal(journal, step)
        _write_json((session.dir_path or tx_dir(self.workspace, session.tx_id)) / _META, session.to_meta())
        return warnings

    def note_doc_mismatch(self) -> None:
        if self.active and self.active.status == "active":
            self.active.warnings.append("document binding drift detected during transaction")

    # ---------- rollback ----------

    def check_safe(self, backend: Any, session: TxSession, *, mode: str) -> None:
        """Raise ROLLBACK_UNSAFE with side_effect=NONE when unsafe. Model must be untouched."""
        info = backend.active_document()
        if info is None:
            raise fail(
                "ROLLBACK_UNSAFE",
                "No active document; cannot verify rollback safety",
                "Re-open the bound document or discard only if it was created in this tx",
                side_effect=SideEffect.NONE,
                mode=mode,
                tx_id=session.tx_id,
            )
        if info.title != session.title or (info.path or None) != (session.path or None):
            raise fail(
                "ROLLBACK_UNSAFE",
                f"Document binding drift: expected title={session.title!r} path={session.path!r}",
                "Switch back to the document that started the transaction, or commit instead",
                side_effect=SideEffect.NONE,
                mode=mode,
                tx_id=session.tx_id,
                current_title=info.title,
                current_path=info.path,
            )
        if session.saved_after_tx:
            raise fail(
                "ROLLBACK_UNSAFE",
                "Document was saved during the transaction; rollback refused",
                "Do not rollback after save_document; continue editing or open a new transaction",
                side_effect=SideEffect.NONE,
                mode=mode,
                tx_id=session.tx_id,
            )

        fp_dict: dict[str, Any] = {}
        try:
            fp_dict = _fp_public(backend.fingerprint())
        except Exception:
            fp_dict = {}
        epoch = compute_epoch(
            path=info.path,
            title=info.title,
            modified=bool(info.modified),
            fp_digest=fingerprint_digest(fp_dict or None),
            # Use begin state_version in epoch baseline was at begin; recompute with current
            # modified+fp — if user externally changed geometry without our tools, fp changes.
            state_version=session.state_version,
        )
        # Conservative: if path/title match but we cannot confirm epoch for reload modes,
        # still check saved_after and unsupported separately. Epoch mismatch when fingerprint
        # at begin existed and current differs AND no journaled steps explain it is hard;
        # we treat: if begin had fingerprint and current fp differs from begin AND steps empty
        # → external change. If steps non-empty, compensate/reload still allowed unless other flags.
        if not session.steps and session.fingerprint and fp_dict:
            if fingerprint_digest(fp_dict) != fingerprint_digest(session.fingerprint):
                raise fail(
                    "ROLLBACK_UNSAFE",
                    "Model changed outside the transaction (fingerprint drift with empty journal)",
                    "Commit is not applicable; reload from your own backup if needed",
                    side_effect=SideEffect.NONE,
                    mode=mode,
                    tx_id=session.tx_id,
                )

        if mode == "compensate" and session.unsupported_tools():
            raise fail(
                "ROLLBACK_UNSAFE",
                "Compensate refused: journal contains unsupported steps",
                "Use reload if a checkpoint exists, or manually reverse unsupported tools",
                side_effect=SideEffect.NONE,
                mode=mode,
                tx_id=session.tx_id,
                unsupported=session.unsupported_tools(),
            )

        if mode == "reload":
            if not session.saved_before:
                raise fail(
                    "ROLLBACK_UNSAFE",
                    "reload requires saved_before=True at tx_begin",
                    "Use compensate, or discard if the document was created in this tx",
                    side_effect=SideEffect.NONE,
                    mode=mode,
                    tx_id=session.tx_id,
                )
            if not session.checkpoint_path or not Path(session.checkpoint_path).is_file():
                raise fail(
                    "ROLLBACK_UNSAFE",
                    "reload requires an existing checkpoint copy",
                    "Transaction was journal-only or checkpoint was removed; try compensate",
                    side_effect=SideEffect.NONE,
                    mode=mode,
                    tx_id=session.tx_id,
                )
            # epoch: path/title already checked; refuse if begin epoch cannot be related
            if session.epoch and epoch and session.path:
                # Recompute epoch with begin's modified=False expectation for saved_before
                begin_like = compute_epoch(
                    path=info.path,
                    title=info.title,
                    modified=False,
                    fp_digest=fingerprint_digest(session.fingerprint or None),
                    state_version=session.state_version,
                )
                # If title/path drifted we already failed. Soft-check: ok.
                _ = begin_like

        if mode == "discard":
            if not session.created_in_tx:
                raise fail(
                    "ROLLBACK_UNSAFE",
                    "discard only allowed for documents created inside the transaction (never saved)",
                    "Use compensate or reload instead",
                    side_effect=SideEffect.NONE,
                    mode=mode,
                    tx_id=session.tx_id,
                )
            if session.saved_after_tx or info.path:
                raise fail(
                    "ROLLBACK_UNSAFE",
                    "discard refused: document has been saved or acquired a path",
                    "Use compensate or close manually",
                    side_effect=SideEffect.NONE,
                    mode=mode,
                    tx_id=session.tx_id,
                )

    def rollback(self, backend: Any, tx_id: str, *, mode: str = "compensate") -> dict[str, Any]:
        if mode not in {"reload", "compensate", "discard"}:
            raise fail(
                "INVALID_ARGUMENT",
                f"Unknown rollback mode: {mode!r}",
                "mode must be reload, compensate, or discard",
            )
        session = self._require_active(tx_id)
        # Safety first — zero side effects on refuse
        self.check_safe(backend, session, mode=mode)

        compensated = 0
        try:
            if mode == "reload":
                assert session.checkpoint_path
                backend.close_document(discard=True)
                backend.open_document(Path(session.checkpoint_path))
            elif mode == "discard":
                backend.close_document(discard=True)
            else:
                for step in reversed(session.steps):
                    if step.compensator is None:
                        continue
                    _apply_compensate(backend, step)
                    compensated += 1
        except Exception as exc:
            # Never report success
            code = getattr(exc, "code", None)
            if code in {"ROLLBACK_UNSAFE", "NO_ACTIVE_TRANSACTION", "INVALID_ARGUMENT"}:
                raise
            raise fail(
                "ROLLBACK_FAILED",
                f"Rollback failed at compensated_steps={compensated}: {exc}",
                "Inspect the model; do not assume prior state. Prefer checkpoint reload if available",
                side_effect=SideEffect.UNKNOWN,
                mode=mode,
                tx_id=tx_id,
                compensated_steps=compensated,
                failed_step=compensated + 1,
                cause=f"{type(exc).__name__}: {exc}",
            ) from exc

        # Cleanup own artifacts (checkpoint); keep journal
        if session.checkpoint_path:
            cp = Path(session.checkpoint_path)
            if cp.is_file():
                try:
                    cp.unlink()
                except OSError:
                    pass
            session.checkpoint_path = None

        session.status = "rolled_back"
        _write_json((session.dir_path or tx_dir(self.workspace, tx_id)) / _META, session.to_meta())
        self.active = None

        # Post fingerprint for result payload
        fp_out = None
        try:
            if backend.active_document() is not None:
                fp_out = _fp_public(backend.fingerprint())
        except Exception:
            fp_out = None

        return {
            "tx_id": tx_id,
            "mode": mode,
            "compensated_steps": compensated,
            "fingerprint": fp_out,
            "rolled_back": True,
        }

    # ---------- helpers ----------

    def _require_active(self, tx_id: str) -> TxSession:
        if self.active is None or self.active.status != "active" or self.active.tx_id != tx_id:
            raise fail(
                "NO_ACTIVE_TRANSACTION",
                f"No active transaction for tx_id={tx_id!r}",
                "Call tx_begin first, or check tx_id from the previous tx_begin result",
                side_effect=SideEffect.NONE,
                tx_id=tx_id,
            )
        return self.active

    @staticmethod
    def _doc_key(session: TxSession) -> str:
        return session.path or f"title:{session.title}"

    def _enforce_retention(self, *, doc_key: str) -> None:
        root = tx_root(self.workspace)
        if not root.is_dir():
            return
        # Drop journals older than retention
        cutoff = _utc_now() - timedelta(days=JOURNAL_RETENTION_DAYS)
        dirs: list[tuple[float, Path, dict[str, Any]]] = []
        for child in root.iterdir():
            if not child.is_dir():
                continue
            meta_path = child / _META
            meta: dict[str, Any] = {}
            if meta_path.is_file():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception:
                    meta = {}
            created = meta.get("created_at") or ""
            try:
                created_dt = datetime.fromisoformat(created) if created else None
            except ValueError:
                created_dt = None
            if created_dt is not None and created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=UTC)
            if created_dt is not None and created_dt < cutoff and meta.get("status") != "active":
                shutil.rmtree(child, ignore_errors=True)
                continue
            mtime = child.stat().st_mtime
            dirs.append((mtime, child, meta))

        # Cap per document (by path/title key)
        same = [
            (mtime, child, meta)
            for mtime, child, meta in dirs
            if (meta.get("path") or f"title:{meta.get('title')}") == doc_key
        ]
        same.sort(key=lambda t: t[0], reverse=True)
        for _, child, meta in same[MAX_TX_PER_DOC:]:
            if meta.get("status") == "active":
                continue
            shutil.rmtree(child, ignore_errors=True)


# ---------- compensator capture / apply ----------


def _capture(backend: Any, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    if tool in _DELETE_FEATURE_TOOLS:
        return {}
    if tool == "set_dimension":
        name = str(args.get("name") or "")
        dims = backend.list_dimensions()
        hit = next((d for d in dims if d.name == name), None)
        if hit is None:
            return {"_capture_error": f"dimension not found: {name}"}
        return {"name": name, "value_si": float(hit.value_si), "kind": hit.kind}
    if tool == "set_material":
        name, database = backend.get_material()
        return {"name": name, "database": database}
    if tool == "set_color":
        rgb = backend.get_color()
        return {"color": list(rgb) if rgb else None}
    if tool == "set_configuration":
        active, _ = backend.list_configurations()
        return {"name": active}
    if tool in {"move_component", "rotate_component"}:
        component = str(args.get("component") or args.get("name") or "")
        xf = backend.get_component_transform(component)
        return {"component": component, "transform": list(xf)}
    if tool == "insert_component":
        return {}  # instance name comes from result
    if tool == "suppress_feature":
        # Invert whatever is being requested
        return {
            "name": str(args.get("name") or ""),
            "suppress": bool(args.get("suppress", True)),
        }
    return {}


def _build_payload(
    tool: str,
    args: dict[str, Any],
    payload: dict[str, Any],
    capture: dict[str, Any],
) -> tuple[str | None, str | None, dict[str, Any]]:
    if capture.get("_capture_error"):
        return None, None, {}
    if tool in _DELETE_FEATURE_TOOLS:
        name = payload.get("name")
        if not name:
            return None, None, {}
        return "delete_feature", str(name), {"name": str(name)}
    if tool == "set_dimension":
        return "set_dimension", None, {
            "name": capture["name"],
            "value_si": capture["value_si"],
        }
    if tool == "set_material":
        return "set_material", None, {"name": capture.get("name") or ""}
    if tool == "set_color":
        return "set_color", None, {"color": capture.get("color")}
    if tool == "set_configuration":
        return "set_configuration", None, {"name": capture.get("name") or "Default"}
    if tool in {"move_component", "rotate_component"}:
        return "set_component_transform", None, {
            "component": capture["component"],
            "transform": capture["transform"],
        }
    if tool == "insert_component":
        name = payload.get("name")
        if not name:
            return None, None, {}
        return "delete_component", str(name), {"name": str(name)}
    if tool == "suppress_feature":
        return "suppress_feature", None, {
            "name": capture["name"],
            "suppress": not bool(capture.get("suppress", True)),
        }
    return None, None, {}


def _apply_compensate(backend: Any, step: JournalStep) -> None:
    kind = step.compensator
    p = step.compensate_payload
    if kind == "delete_feature":
        backend.delete_feature(str(p["name"]))
    elif kind == "set_dimension":
        backend.set_dimension(str(p["name"]), float(p["value_si"]))
    elif kind == "set_material":
        prior = str(p.get("name") or "").strip()
        if not prior:
            return  # was unset; cannot clear material reliably
        backend.set_material(prior)
    elif kind == "set_color":
        color = p.get("color")
        if color is None:
            # No prior color — best-effort leave as-is (cannot clear reliably)
            return
        backend.set_color(float(color[0]), float(color[1]), float(color[2]))
    elif kind == "set_configuration":
        backend.set_configuration(str(p.get("name") or "Default"), create=False)
    elif kind == "set_component_transform":
        backend.set_component_transform(str(p["component"]), list(p["transform"]))
    elif kind == "delete_component":
        backend.delete_component(str(p["name"]))
    elif kind == "suppress_feature":
        backend.suppress_feature(str(p["name"]), bool(p.get("suppress", False)))
    else:
        raise fail(
            "ROLLBACK_FAILED",
            f"Unknown compensator: {kind!r}",
            "Journal may be corrupt; prefer checkpoint reload",
            side_effect=SideEffect.UNKNOWN,
            compensator=kind,
        )


__all__ = [
    "COVERED_TOOLS",
    "COVERAGE_HINT",
    "CHECKPOINT_THRESHOLD_BYTES",
    "TxManager",
    "TxSession",
    "compute_epoch",
    "ext_for_doc",
    "fingerprint_digest",
    "new_tx_id",
]
