"""COM error-code usage under solidworks/.

Rule (v1.2.2 §12.1): the `COM_CALL_FAILED` literal may appear only in `sta.py`
(`_map_error` / `_com_failed` / timeouts). Business mixins must use those entry points.
"""
import ast
from pathlib import Path

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
