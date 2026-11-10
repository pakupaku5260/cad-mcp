"""Path sandbox: read/write boundary gates (v4 §11 W1-3).

Threat model (sandbox gap checklist):
- Text layer before parse: empty/nul, UNC, drive-relative, NTFS ADS (extra colons),
  reserved devices (CON/NUL/COM1...), trailing dot/space on components, 8.3 short names (heuristic).
- Parse layer: absolutize → resolve() → commonpath must stay under allowed roots (normcase).
- Symlinks: any symlink component under root → reject (stricter than target-only).
- Extension whitelist; overwrite requires overwrite=True; allow_outside=True is audited escape hatch.
- Sandbox is the **write gate** for save/export—mandatory last layer.
"""
from __future__ import annotations

import json
import os
import re
from collections.abc import Collection, Sequence
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath
from typing import Any

from cadmcp.errors import SideEffect, fail

RESERVED_DEVICE_NAMES: frozenset[str] = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)

DEFAULT_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".sldprt", ".sldasm", ".slddrw",
        ".step", ".stp", ".iges", ".igs", ".x_t", ".x_b", ".stl", ".obj",
        ".pdf", ".dxf", ".dwg",
        ".png", ".jpg", ".jpeg",
        ".csv", ".xlsx",
    }
)

_83_SHORT_RE = re.compile(r"^[A-Za-z0-9_$\-]{1,8}~\d+$")
_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def default_output_root() -> Path:
    """Default workspace (v4 §11: ~/cadmcp-workspace)."""
    return (Path.home() / "cadmcp-workspace").expanduser()


# ---------- audit log (§11: user config dir, not workspace) ----------

_audit_path: Path | None = None  # None = disabled until cli wires on serve start


def set_audit_path(path: Path | str | None) -> None:
    global _audit_path
    _audit_path = Path(path) if path else None


def _scrub(value: Any) -> Any:
    if isinstance(value, str):
        return value if len(value) <= 300 else value[:300] + "…(truncated)"
    if isinstance(value, Path):
        return _scrub(str(value))
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub(v) for v in value]
    return value


def audit(event: str, **fields: Any) -> None:
    """Append one JSON line; no-op when set_audit_path(None)."""
    if _audit_path is None:
        return
    record = {"ts": datetime.now(UTC).isoformat(), "event": event}
    record.update(_scrub(fields))
    _audit_path.parent.mkdir(parents=True, exist_ok=True)
    with _audit_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _reject(code: str, message: str, hint: str, raw: str, reason: str, **context: Any):
    audit("path_rejected", path=raw, reason=reason, code=code, **context)
    return fail(code, message, hint, side_effect=SideEffect.NONE, **context, path=raw)


# ---------- textual checks (pre-parse, platform-agnostic) ----------


def _textual_checks(raw: str) -> None:
    if not raw or not raw.strip():
        raise _reject("PATH_INVALID", "Path is empty", "Pass a file name or path relative to workspace", raw, "empty")
    if "\x00" in raw:
        raise _reject("PATH_INVALID", "Path contains null byte", "Check argument source; do not pass binary", raw, "nul_byte")
    if raw.startswith("\\\\") or raw.startswith("//"):
        raise _reject(
            "PATH_INVALID", f"UNC paths not supported: {raw!r}",
            "Files must stay in workspace; use a relative path", raw, "unc",
        )

    expanded = os.path.expanduser(raw)

    pwin = PureWindowsPath(expanded)
    if pwin.drive and not pwin.is_absolute():
        raise _reject(
            "PATH_INVALID", f"Drive-relative path invalid: {raw!r}",
            "Use a full absolute path or workspace-relative path", raw, "drive_relative",
        )
    if pwin.drive and pwin.is_absolute() and os.name != "nt":
        raise _reject(
            "PATH_INVALID", f"Cannot validate drive path on this platform: {raw!r}",
            "On Windows use absolute paths, or workspace-relative", raw, "foreign_drive",
        )

    colon_positions = [i for i, ch in enumerate(expanded) if ch == ":"]
    if colon_positions and not (len(colon_positions) == 1 and colon_positions[0] == 1):
        raise _reject(
            "PATH_INVALID", f"Extra colon in path (NTFS ADS or invalid drive): {raw!r}",
            "Remove colons; NTFS ADS not supported", raw, "ads_colon",
        )

    for comp in re.split(r"[\\/]", expanded):
        if comp in ("", ".", ".."):
            continue
        if comp.split(".")[0].upper() in RESERVED_DEVICE_NAMES:
            raise _reject(
                "PATH_INVALID", f"Reserved device name not allowed as file name: {comp!r}",
                "Choose another file name", raw, "reserved_device", component=comp,
            )
        if comp != comp.rstrip(". "):
            raise _reject(
                "PATH_INVALID", f"File name ends with dot or space: {comp!r}",
                "Strip trailing dots and spaces", raw, "trailing_chars", component=comp,
            )
        if _83_SHORT_RE.match(comp):
            raise _reject(
                "PATH_INVALID", f"Suspected 8.3 short file name: {comp!r}",
                "Use the full long file name", raw, "short_name", component=comp,
            )


# ---------- resolve: destination check + symlink walk ----------


def _as_roots(roots: Path | Sequence[Path]) -> list[Path]:
    items = [roots] if isinstance(roots, (str, Path)) else list(roots)
    if not items:
        raise ValueError("At least one allowed directory must be configured")
    return [Path(r).expanduser().resolve() for r in items]


def _within(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath([os.path.normcase(str(path)), os.path.normcase(str(root))]) == os.path.normcase(str(root))
    except ValueError:
        return False


def _resolve_within(raw: str, roots: list[Path], *, allow_outside: bool) -> Path:
    expanded = os.path.expanduser(raw)
    p = Path(expanded)

    candidates = [r / p for r in roots] if not p.is_absolute() else [p]

    winners: list[tuple[Path, Path, Path]] = []  # (root, candidate, resolved)
    for cand in candidates:
        resolved = cand.resolve()
        for r2 in roots:
            if _within(resolved, r2):
                winners.append((r2, cand, resolved))
                break

    if not winners:
        if allow_outside and p.is_absolute():
            resolved = p.resolve()
            audit("path_allowed_outside", path=str(resolved), mode="allow_outside")
            return resolved
        raise _reject(
            "PATH_OUTSIDE_SANDBOX",
            f"Resolved path outside allowed dirs: {expanded!r}",
            "Keep files under workspace; use relative paths",
            raw, "outside_roots",
            roots=[str(r) for r in roots],
        )

    root, cand, resolved = next((w for w in winners if w[2].exists()), winners[0])

    lexical = Path(os.path.normpath(str(cand)))
    try:
        rel_parts = lexical.relative_to(root).parts
    except ValueError:
        rel_parts = ()
    cur = root
    for part in rel_parts:
        cur = cur / part
        if cur.is_symlink():
            raise _reject(
                "PATH_SYMLINK_DENIED",
                f"Path crosses a symbolic link: {cur}",
                "Use the real path; sandbox rejects paths through symlinks",
                raw, "symlink_component", component=str(cur),
            )
    return resolved


# ---------- public gates ----------


def _normalize_exts(extensions: Collection[str] | None) -> frozenset[str]:
    src = DEFAULT_EXTENSIONS if extensions is None else extensions
    return frozenset(e.lower() if e.startswith(".") else "." + e.lower() for e in src)


def ensure_output_path(
    raw: str,
    *,
    roots: Path | Sequence[Path],
    extensions: Collection[str] | None = None,
    overwrite: bool = False,
    allow_outside: bool = False,
    create_parents: bool = True,
) -> Path:
    """Write gate: last layer for save_as / export; returns validated absolute path."""
    if not isinstance(raw, str):
        raise _reject("PATH_INVALID", f"Path must be a string, got {type(raw).__name__}",
                      "Pass a string path", repr(raw), "not_str")
    _textual_checks(raw)

    ext = Path(os.path.expanduser(raw)).suffix.lower()
    if ext not in _normalize_exts(extensions):
        raise _reject(
            "PATH_EXTENSION_DENIED",
            f"Extension {ext or '(none)'} not on whitelist",
            f"Allowed extensions: {', '.join(sorted(_normalize_exts(extensions)))}",
            raw, "extension", extension=ext,
        )

    resolved = _resolve_within(raw, _as_roots(roots), allow_outside=allow_outside)

    if resolved.exists() and not overwrite:
        raise _reject(
            "PATH_OVERWRITE_DENIED",
            f"File already exists: {resolved}",
            "Pick another name; set overwrite=true to replace",
            raw, "overwrite", target=str(resolved),
        )

    if create_parents:
        resolved.parent.mkdir(parents=True, exist_ok=True)

    audit(
        "path_allowed", mode="write", path=str(resolved),
        overwrite=overwrite, allow_outside=allow_outside,
    )
    return resolved


def ensure_input_path(
    raw: str,
    *,
    roots: Path | Sequence[Path],
    extensions: Collection[str] | None = None,
    must_exist: bool = True,
) -> Path:
    """Read gate: open_document etc.; default workspace plus user-allowed roots."""
    if not isinstance(raw, str):
        raise _reject("PATH_INVALID", f"Path must be a string, got {type(raw).__name__}",
                      "Pass a string path", repr(raw), "not_str")
    _textual_checks(raw)

    ext = Path(os.path.expanduser(raw)).suffix.lower()
    if ext not in _normalize_exts(extensions):
        raise _reject(
            "PATH_EXTENSION_DENIED",
            f"Extension {ext or '(none)'} not on whitelist",
            f"Allowed extensions: {', '.join(sorted(_normalize_exts(extensions)))}",
            raw, "extension", extension=ext,
        )

    resolved = _resolve_within(raw, _as_roots(roots), allow_outside=False)

    if must_exist and not resolved.exists():
        raise _reject(
            "PATH_NOT_FOUND", f"File not found: {resolved}",
            "Check spelling and location (relative to workspace)", raw, "missing",
            target=str(resolved),
        )

    audit("path_allowed", mode="read", path=str(resolved))
    return resolved
