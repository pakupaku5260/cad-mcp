"""Public whitelist export must not leak internal docs / agent artifacts."""
from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXPORT_SCRIPT = ROOT / "scripts" / "export_public.py"

if not EXPORT_SCRIPT.is_file():
    # The gate lives in the internal repo only: export_public.py is never
    # exported, so the public tree must skip this module instead of failing.
    pytest.skip(
        "export gate is internal-only (scripts/export_public.py not exported)",
        allow_module_level=True,
    )


def _load_export_public():
    spec = importlib.util.spec_from_file_location("cadmcp_export_public", EXPORT_SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def export_mod():
    return _load_export_public()


def test_public_export_ref_head_clean(tmp_path: Path, export_mod) -> None:
    dest = tmp_path / "public"
    # Prefer --ref HEAD so the tree matches committed sources (not local dirt).
    archive = export_mod.materialize_ref("HEAD", repo=ROOT)
    try:
        export_mod.export(dest, clean=True, source=archive)
    finally:
        shutil.rmtree(archive, ignore_errors=True)

    assert export_mod.scan_forbidden(dest) == []
    assert export_mod.check_readme_langs(dest) == []

    assert not (dest / "docs" / "internal").exists()
    assert not (dest / "docs" / "handoff").exists()
    assert not (dest / ".opencode").exists()
    assert not (dest / "AGENTS.md").exists()
    assert not (dest / "CLAUDE.md").exists()
    assert not (dest / "HANDOFF.md").exists()
    assert not (dest / "scripts" / "export_public.py").exists()

    backend_mds = list((dest / "cadmcp" / "backend").rglob("*.md"))
    assert backend_mds == []


def test_narrative_scan_skips_source_and_flags_prose(tmp_path: Path, export_mod) -> None:
    """Machine identity: all files. Internal narrative: prose only (.md/.txt/.rst)."""
    tree = tmp_path / "scan"
    py = tree / "cadmcp" / "x.py"
    md = tree / "docs" / "x.md"
    py.parent.mkdir(parents=True)
    md.parent.mkdir(parents=True)
    py.write_text(
        '# risk: unverified — formal source annotation\nLEGACY = "docs/handoff/"\n',
        encoding="utf-8",
    )
    md.write_text("See docs/handoff for internal notes.\n", encoding="utf-8")

    hits = export_mod.scan_forbidden(tree)
    assert not any(h.startswith("cadmcp/x.py") for h in hits), hits
    assert any(
        h.startswith("docs/x.md") and "docs/handoff" in h for h in hits
    ), hits
