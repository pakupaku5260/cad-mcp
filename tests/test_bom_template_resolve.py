"""BOM template resolution: registry/install-root scan, no hard-coded Program Files paths."""
from __future__ import annotations

from pathlib import Path

from cadmcp.backend.solidworks.infrastructure import (
    bom_templates_under_install,
    discover_bom_standard_templates,
)


def test_bom_templates_under_install_prefers_chinese_then_english(tmp_path: Path):
    root = tmp_path / "SOLIDWORKS"
    (root / "lang" / "german").mkdir(parents=True)
    (root / "lang" / "english").mkdir(parents=True)
    (root / "lang" / "chinese-simplified").mkdir(parents=True)
    (root / "lang" / "german" / "bom-standard.sldbomtbt").write_text("g", encoding="utf-8")
    (root / "lang" / "english" / "bom-standard.sldbomtbt").write_text("e", encoding="utf-8")
    (root / "lang" / "chinese-simplified" / "bom-standard.sldbomtbt").write_text("c", encoding="utf-8")

    found = bom_templates_under_install(root)
    assert [p.parent.name for p in found] == ["chinese-simplified", "english", "german"]


def test_discover_bom_standard_templates_uses_extra_roots_only(tmp_path: Path, monkeypatch):
    root = tmp_path / "SW"
    (root / "lang" / "english").mkdir(parents=True)
    tpl = root / "lang" / "english" / "bom-standard.sldbomtbt"
    tpl.write_text("e", encoding="utf-8")

    monkeypatch.setattr(
        "cadmcp.backend.solidworks.infrastructure.discover_solidworks_install_roots",
        lambda: [],
    )
    found = discover_bom_standard_templates(extra_roots=[root])
    assert found == [tpl]


def test_discover_bom_standard_templates_dedupes(tmp_path: Path, monkeypatch):
    root = tmp_path / "SW"
    (root / "lang" / "english").mkdir(parents=True)
    tpl = root / "lang" / "english" / "bom-standard.sldbomtbt"
    tpl.write_text("e", encoding="utf-8")

    monkeypatch.setattr(
        "cadmcp.backend.solidworks.infrastructure.discover_solidworks_install_roots",
        lambda: [root],
    )
    found = discover_bom_standard_templates(extra_roots=[root, root])
    assert found == [tpl]
