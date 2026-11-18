"""L1 design_run checkpoints: document copy + sidecar fingerprint (not TxManager).

Snapshots live under ``<workspace>/.cadmcp/checkpoints/<sha1(doc_key)[:12]>/``.
Capture talks to the backend directly (save_copy_as / fingerprint) and does **not**
go through dispatch, so ``state_version`` is recorded but not bumped.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cadmcp.errors import CadMcpError, SideEffect, fail
from cadmcp.safety import ensure_input_path, ensure_output_path
from cadmcp.transaction import ext_for_doc, fingerprint_digest

log = logging.getLogger("cadmcp.checkpoints")

_SNAPSHOT_EXTS = {".sldprt", ".sldasm", ".slddrw"}
_KEEP_DEFAULT = 10


def checkpoints_root(workspace: Path) -> Path:
    return Path(workspace) / ".cadmcp" / "checkpoints"


def doc_key(info: Any) -> str:
    """Stable document identity — same rule as TxManager._doc_key."""
    path = getattr(info, "path", None)
    title = getattr(info, "title", "") or ""
    return path or f"title:{title}"


def snapshot_dir(workspace: Path, key: str) -> Path:
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
    return checkpoints_root(workspace) / digest


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)


def _sidecar_path(dest: Path) -> Path:
    return dest.with_suffix(".json")


def _write_sidecar(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _read_sidecar(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def capture(
    backend: Any,
    workspace: Path,
    *,
    name: str,
    index: int,
    state_version: int | None,
) -> dict[str, Any]:
    """Save a document copy + sidecar. Never raises into the caller (ok=false on failure)."""
    entry: dict[str, Any] = {
        "name": name,
        "index": index,
        "ok": False,
        "path": None,
        "bytes": None,
        "fingerprint_digest": None,
        "state_version": state_version,
        "error_code": None,
        "detail": None,
    }
    dest: Path | None = None
    sidecar: Path | None = None
    try:
        info = backend.active_document()
        if info is None:
            entry["detail"] = "No active document to checkpoint."
            entry["error_code"] = "NO_ACTIVE_DOCUMENT"
            return entry
        key = doc_key(info)
        ext = ext_for_doc(getattr(info, "doc_type", "part") or "part", getattr(info, "path", None))
        rel = (
            Path(".cadmcp")
            / "checkpoints"
            / hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
            / f"{index:02d}_{_safe_name(name)}{ext}"
        )
        dest = ensure_output_path(
            rel.as_posix(),
            roots=workspace,
            extensions=_SNAPSHOT_EXTS,
            overwrite=True,
            create_parents=True,
        )
        backend.save_copy_as(dest)
        if not dest.is_file():
            entry["detail"] = "Checkpoint file missing after save_copy_as."
            return entry
        size = dest.stat().st_size
        digest = fingerprint_digest(backend.fingerprint())
        created = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        sidecar_payload = {
            "name": name,
            "index": index,
            "path": str(dest),
            "bytes": size,
            "fingerprint_digest": digest,
            "state_version": state_version,
            "doc_key": key,
            "doc_title": getattr(info, "title", "") or "",
            "doc_type": getattr(info, "doc_type", "part") or "part",
            "created_at": created,
        }
        sidecar = _sidecar_path(dest)
        _write_sidecar(sidecar, sidecar_payload)
        prune(workspace, key, keep=_KEEP_DEFAULT)
        entry.update(
            {
                "ok": True,
                "path": str(dest),
                "bytes": size,
                "fingerprint_digest": digest,
                "detail": None,
                "error_code": None,
            }
        )
        return entry
    except CadMcpError as exc:
        entry["error_code"] = getattr(exc, "code", None) or None
        entry["detail"] = str(getattr(exc, "message", None) or exc)
        _cleanup_partial(dest, sidecar)
        return entry
    except Exception as exc:  # noqa: BLE001 — capture must never raise into run
        entry["error_code"] = None
        entry["detail"] = f"Checkpoint capture failed: {exc}"
        log.warning("checkpoint capture failed name=%s: %s", name, exc)
        _cleanup_partial(dest, sidecar)
        return entry


def _cleanup_partial(dest: Path | None, sidecar: Path | None) -> None:
    for p in (dest, sidecar):
        if p is None:
            continue
        try:
            if p.is_file():
                p.unlink()
        except OSError:
            pass


def find(workspace: Path, key: str, name: str) -> dict[str, Any] | None:
    """Return the newest sidecar payload for ``name``, or None if missing."""
    folder = snapshot_dir(workspace, key)
    if not folder.is_dir():
        return None
    matches: list[tuple[float, dict[str, Any]]] = []
    for path in folder.glob("*.json"):
        if path.name == "meta.json":
            continue
        try:
            data = _read_sidecar(path)
        except (OSError, json.JSONDecodeError, UnicodeError):
            continue
        if data.get("name") == name:
            try:
                mtime = path.stat().st_mtime
            except OSError:
                mtime = 0.0
            matches.append((mtime, data))
    if not matches:
        return None
    matches.sort(key=lambda t: t[0], reverse=True)
    return matches[0][1]


def restore(
    backend: Any,
    workspace: Path,
    *,
    key: str,
    name: str,
) -> dict[str, Any]:
    """Close active doc (discard) and open the checkpoint copy. Raises CadMcpError on failure."""
    meta = find(workspace, key, name)
    if meta is None:
        raise fail(
            "PATH_NOT_FOUND",
            f"Checkpoint {name!r} not found for this document.",
            "Run design_run once with checkpoints declared before resume_from",
        )
    snap_path = meta.get("path")
    if not snap_path:
        raise fail(
            "INVALID_ARGUMENT",
            f"Checkpoint sidecar for {name!r} has no path.",
            "Delete corrupt sidecars under .cadmcp/checkpoints and re-run",
        )
    try:
        resolved = ensure_input_path(
            snap_path,
            roots=workspace,
            must_exist=True,
            extensions=_SNAPSHOT_EXTS,
        )
    except CadMcpError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise fail(
            "PATH_NOT_FOUND",
            f"Checkpoint file unavailable: {exc}",
            "Re-run design_run with checkpoints to recreate the snapshot",
        ) from exc
    backend.close_document(discard=True)
    try:
        backend.open_document(resolved)
    except Exception as exc:  # noqa: BLE001 — the active doc is already gone
        # The session was mutated (doc closed/discarded): never report a clean no-op.
        raise fail(
            "ROLLBACK_FAILED",
            f"Checkpoint restore failed for {name!r}: {exc}",
            "Re-open the original document; do not assume the prior state survived",
            side_effect=SideEffect.UNKNOWN,
            checkpoint=name,
            cause=f"{type(exc).__name__}: {exc}",
        ) from exc
    return meta


def prune(workspace: Path, key: str, *, keep: int = _KEEP_DEFAULT) -> list[str]:
    """Keep the newest ``keep`` snapshot pairs (by mtime); delete older ones. Returns deleted paths."""
    folder = snapshot_dir(workspace, key)
    if not folder.is_dir() or keep < 0:
        return []
    files: list[Path] = []
    for path in folder.iterdir():
        if not path.is_file():
            continue
        if path.suffix.lower() in _SNAPSHOT_EXTS:
            files.append(path)
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    deleted: list[str] = []
    for stale in files[keep:]:
        for victim in (stale, _sidecar_path(stale)):
            try:
                if victim.is_file():
                    victim.unlink()
                    deleted.append(str(victim))
            except OSError:
                pass
    return deleted


__all__ = [
    "capture",
    "checkpoints_root",
    "doc_key",
    "find",
    "prune",
    "restore",
    "snapshot_dir",
]
