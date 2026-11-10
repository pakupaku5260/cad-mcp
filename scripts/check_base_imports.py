"""Check the import block of base.py and compare what is missing from protocol.py."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "cadmcp" / "backend" / "base.py"
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


base_imports = set(extract_imports(BASE))
proto_imports = set(extract_imports(PROTO))

print("= = = base.py yes but protocol.py no = = =")
for imp in sorted(base_imports - proto_imports):
    print(f"  {imp}")

print()
print("= = = protocol.py Yes but base.py No = = =")
for imp in sorted(proto_imports - base_imports):
    print(f"  {imp}")
    