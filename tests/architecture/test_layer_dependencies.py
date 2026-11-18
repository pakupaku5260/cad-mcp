"""S1 gate: dependency direction from INDEX.yaml + architecture invariants."""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "cadmcp" / "backend"
INDEX_FILE = BACKEND / "INDEX.yaml"

# Hard invariants (not waivable via config)
INVARIANTS = [
    ("solidworks.sta", "solidworks.infrastructure"),
    ("solidworks.sta", "solidworks.naming"),
    ("solidworks.sta", "solidworks.selection"),
    ("solidworks.sta", "solidworks.geometry"),
    ("solidworks.sta", "solidworks.document"),
    ("solidworks.sta", "solidworks.sketch"),
    ("solidworks.infrastructure", "solidworks.naming"),
    ("solidworks.infrastructure", "solidworks.selection"),
    ("solidworks.infrastructure", "solidworks.geometry"),
    ("solidworks.document", "solidworks.backend"),
    ("solidworks.sketch", "solidworks.backend"),
    ("fake", "solidworks"),
    ("solidworks", "fake"),
]


def _iter_imports(file: Path) -> list[tuple[int, str]]:
    try:
        tree = ast.parse(file.read_text(encoding="utf-8"))
    except Exception:
        return []
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            out.append((node.lineno, node.module))
        elif isinstance(node, ast.Import):
            for name in node.names:
                out.append((node.lineno, name.name))
    return out


def _file_to_module(file: Path) -> str | None:
    try:
        rel = file.relative_to(BACKEND)
    except ValueError:
        return None
    parts = list(rel.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def test_architectural_invariants():
    """Hard check: sta must not depend on infrastructure, etc."""
    errors: list[str] = []
    for py_file in BACKEND.rglob("*.py"):
        if "_baseline" in py_file.parts or "__pycache__" in py_file.parts:
            continue
        current = _file_to_module(py_file)
        if current is None:
            continue
        for lineno, module in _iter_imports(py_file):
            if not module.startswith("cadmcp.backend"):
                continue
            target = module.replace("cadmcp.backend.", "")
            for from_pat, to_pat in INVARIANTS:
                if current.startswith(from_pat) and target.startswith(to_pat):
                    errors.append(
                        f"{py_file.relative_to(ROOT)}:{lineno}: "
                        f"violates invariant {from_pat} → {to_pat}"
                    )
    assert not errors, "\n".join(errors)


def test_layer_dependencies():
    """INDEX.yaml dependency rules. S1: INDEX incomplete, warn-only."""
    # S1: INDEX.yaml not complete yet — skip strict check
    pytest.skip("S1: INDEX.yaml incomplete; strict check enabled at S2")


# F4: top-level package layering (transaction must not reach backends directly)
_CADMCP = ROOT / "cadmcp"
_TX_FORBIDDEN_PREFIXES = (
    "cadmcp.backend.solidworks",
    "cadmcp.backend.fake",
)


def test_transaction_package_does_not_import_backends():
    """cadmcp.transaction and toolsets.transaction stay above backend concretes."""
    targets = [
        _CADMCP / "transaction.py",
        _CADMCP / "toolsets" / "transaction.py",
    ]
    errors: list[str] = []
    for path in targets:
        for lineno, module in _iter_imports(path):
            if any(module == p or module.startswith(p + ".") for p in _TX_FORBIDDEN_PREFIXES):
                errors.append(f"{path.relative_to(ROOT)}:{lineno}: forbidden import {module}")
    assert not errors, "\n".join(errors)


def test_transaction_toolset_depends_on_transaction_module():
    """toolsets.transaction must go through cadmcp.transaction (not reimplement journal)."""
    path = _CADMCP / "toolsets" / "transaction.py"
    imports = {mod for _, mod in _iter_imports(path)}
    assert "cadmcp.transaction" in imports
