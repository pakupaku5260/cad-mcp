"""Usage-layer skills: single-source markdown, registered as cadmcp://skill/<id>, sync to .opencode/skills.

Wave 7 SKILL: body covers when to stop / what to query first / error handling / forbidden ops—no tool schemas.
"""
from __future__ import annotations

import re
from pathlib import Path

SKILL_IDS: tuple[str, ...] = (
    "solidworks-modeling",
    "solidworks-assembly",
    "solidworks-recovery",
)

_MAX_BYTES = 4096
_SKILLS_DIR = Path(__file__).resolve().parent / "resources" / "content" / "skills"
_FRONT_MATTER_RE = re.compile(r"^---\r?\n.*?\r?\n---\r?\n", re.DOTALL)
_TOOL_NAME_RE = re.compile(r"`([a-z][a-z0-9_]*)`")
_URI_RE = re.compile(r"\bcadmcp://[^\s'\"`,.)\\]]+")


def skill_path(skill_id: str) -> Path:
    return _SKILLS_DIR / f"{skill_id}.md"


def load_skill_text(skill_id: str) -> str:
    path = skill_path(skill_id)
    if not path.is_file():
        raise FileNotFoundError(f"Missing skill source: {path}")
    text = path.read_text(encoding="utf-8")
    if len(text.encode("utf-8")) > _MAX_BYTES:
        raise ValueError(f"skill {skill_id} exceeds {_MAX_BYTES} byte limit")
    return text


def skill_body(skill_id: str) -> str:
    """Body without YAML front matter (for OpenCode SKILL.md)."""
    text = load_skill_text(skill_id)
    return _FRONT_MATTER_RE.sub("", text, count=1).lstrip()


def skill_uri(skill_id: str) -> str:
    return f"cadmcp://skill/{skill_id}"


def iter_skill_ids() -> tuple[str, ...]:
    return SKILL_IDS


def mentioned_tool_names(text: str, known: set[str] | None = None) -> set[str]:
    """Registered tool names mentioned in text; with known, return intersection only."""
    if known is not None:
        found: set[str] = set()
        for name in known:
            if re.search(rf"(?<![a-z0-9_]){re.escape(name)}(?![a-z0-9_])", text):
                found.add(name)
        return found
    # Without registry, fall back to backtick scan (`name` and `name(`)
    names = set(_TOOL_NAME_RE.findall(text))
    names |= set(re.findall(r"`([a-z][a-z0-9_]*)\(", text))
    return names


def mentioned_uris(text: str) -> set[str]:
    return set(_URI_RE.findall(text))


def sync_opencode_skills(repo_root: Path | None = None) -> list[Path]:
    """Write skill body to .opencode/skills/<id>/SKILL.md for client discovery."""
    root = repo_root or Path(__file__).resolve().parents[1]
    written: list[Path] = []
    for skill_id in SKILL_IDS:
        dest_dir = root / ".opencode" / "skills" / skill_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / "SKILL.md"
        # Keep front matter for OpenCode name/description
        dest.write_text(load_skill_text(skill_id), encoding="utf-8", newline="\n")
        written.append(dest)
    return written


__all__ = [
    "SKILL_IDS",
    "iter_skill_ids",
    "load_skill_text",
    "mentioned_tool_names",
    "mentioned_uris",
    "skill_body",
    "skill_path",
    "skill_uri",
    "sync_opencode_skills",
]
