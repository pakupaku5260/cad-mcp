"""Compare imports in _baseline/base.py.orig vs protocol/protocol.py."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORIG = ROOT / "internal-evidence" / "_baseline" / "base.py.orig"
PROTO = ROOT / "cadmcp" / "backend" / "protocol" / "protocol.py"


def extract_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for name in node.names:
                out.append(f"from {node.module} import {name.name}")
        elif isinstance(node, ast.Import):
            for name in node.names:
                out.append(f"import {name.name}")
    return out


orig = set(extract_imports(ORIG))
proto = set(extract_imports(PROTO))

print("=== in base.py.orig but not protocol.py (need to add) ===")
for imp in sorted(orig - proto):
    print(f"  {imp}")
