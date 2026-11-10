"""Wave 7 SKILL: size budget, URIs registered, tool names in body registered, .opencode syncable."""
from __future__ import annotations

from pathlib import Path

from cadmcp.resources import known_uris
from cadmcp.skills import (
    SKILL_IDS,
    load_skill_text,
    mentioned_tool_names,
    mentioned_uris,
    skill_uri,
    sync_opencode_skills,
)
from cadmcp.toolsets.core import core_registry


def test_skills_exist_under_budget_and_registered():
    assert len(SKILL_IDS) == 3
    for skill_id in SKILL_IDS:
        text = load_skill_text(skill_id)
        assert len(text.encode("utf-8")) <= 3 * 1024
        assert skill_uri(skill_id) in known_uris()
        assert "When to stop" in text or "何时停" in text


def test_skill_uris_and_tools_are_registered():
    registered = {s.name for s in core_registry().all()}
    for skill_id in SKILL_IDS:
        text = load_skill_text(skill_id)
        for uri in mentioned_uris(text):
            assert uri in known_uris(), f"{skill_id} references unregistered URI: {uri}"
        # Every tool name mentioned in the body must be registered (registry lookup avoids false positives)
        hits = mentioned_tool_names(text, registered)
        assert hits, f"{skill_id} does not mention any registered tool"
        assert hits <= registered


def test_sync_opencode_skills(tmp_path: Path):
    written = sync_opencode_skills(tmp_path)
    assert len(written) == 3
    for path in written:
        assert path.is_file()
        assert path.name == "SKILL.md"
        assert path.read_text(encoding="utf-8") == load_skill_text(path.parent.name)
