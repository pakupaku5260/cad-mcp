"""COM error-code usage under solidworks/ + F3 remediation catalog gates.

Rule (v1.2.2 §12.1): the `COM_CALL_FAILED` literal may appear only in `sta.py`
(`_map_error` / `_com_failed` / timeouts). Business mixins must use those entry points.

F3: first-batch codes must expose complete, executable remediation metadata and
appear in the shared cadmcp://help/errors / help(errors) body.
"""
from __future__ import annotations

import ast
from pathlib import Path

from cadmcp.errors import (
    CATALOG,
    FIRST_BATCH_ERROR_CODES,
    render_errors_help,
)
from cadmcp.resources import read_resource, topic_entry, topic_uri
from cadmcp.resources.content import TOPICS

ROOT = Path(__file__).resolve().parents[2]
COM_DIR = ROOT / "cadmcp" / "backend" / "solidworks"

# Files allowed to raise with the "COM_CALL_FAILED" literal
WHITELIST_FILES = {"sta.py"}


def _iter_py_files():
    for f in COM_DIR.rglob("*.py"):
        if "__pycache__" in f.parts:
            continue
        if f.name in WHITELIST_FILES:
            continue
        yield f


def test_no_com_call_failed_outside_sta():
    """Under solidworks/, only sta.py may raise COM_CALL_FAILED."""
    violations: list[str] = []
    for f in _iter_py_files():
        source = f.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Raise):
                text = ast.unparse(node)
                if "COM_CALL_FAILED" in text:
                    violations.append(f"{f.name}:{node.lineno}: {text[:60]}")
    assert not violations, "Illegal COM_CALL_FAILED:\n" + "\n".join(violations)


def test_first_batch_remediation_metadata_complete():
    """Each first-batch code has executable action + coherent auto/confirmation flags."""
    assert len(FIRST_BATCH_ERROR_CODES) == 14
    missing = sorted(FIRST_BATCH_ERROR_CODES - set(CATALOG))
    assert not missing, f"first-batch codes missing from CATALOG: {missing}"
    for code in sorted(FIRST_BATCH_ERROR_CODES):
        entry = CATALOG[code]
        assert isinstance(entry.auto, bool), code
        assert isinstance(entry.requires_confirmation, bool), code
        assert entry.action.strip(), f"{code}: action must be non-empty"
        assert not (entry.auto and entry.requires_confirmation), (
            f"{code}: auto and requires_confirmation must not both be true"
        )


def test_errors_help_sources_are_identical_and_list_first_batch():
    """render_errors_help ≡ topic_entry ≡ resources/read ≡ TOPICS['errors'].text."""
    rendered = render_errors_help()
    topic_body = TOPICS["errors"].text
    entry = topic_entry("errors")
    assert entry is not None
    uri, via_topic = entry
    assert uri == topic_uri("errors") == "cadmcp://help/errors"
    via_resource = read_resource("cadmcp://help/errors")
    assert rendered == topic_body == via_topic == via_resource
    # Envelope / retry guidance preserved
    assert "side_effect" in rendered
    assert "ok=false" in rendered
    assert "Remediation catalog" in rendered
    for code in sorted(FIRST_BATCH_ERROR_CODES):
        assert f"`{code}`" in rendered, f"{code} missing from help/errors"
        action = CATALOG[code].action.strip()
        # action text (possibly pipe-escaped) must appear
        assert action.replace("|", "\\|") in rendered or action in rendered, (
            f"{code} action not visible in help/errors"
        )
