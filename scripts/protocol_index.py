"""Extract public names from protocol/*.py; print name → file map (for S4 checklist)."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "cadmcp" / "backend" / "protocol"

FILES = ["models.py", "constants.py", "geometry_math.py", "geometry_engine.py",
         "validators.py", "parsers.py", "protocol.py"]

index: dict[str, str] = {}
for filename in FILES:
    f = PROTOCOL / filename
    if not f.exists():
        continue
    tree = ast.parse(f.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            index.setdefault(node.name, filename)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    index.setdefault(t.id, filename)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            index.setdefault(node.target.id, filename)

for name in sorted(index):
    print(f"{name:40s} -> {index[name]}")
