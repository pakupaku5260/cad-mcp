"""Check whether the module-level constants in com_backend.py are all moved to com/_constants.py."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COM_BACKEND = ROOT / "cadmcp" / "backend" / "solidworks" / "backend.py"
CONSTANTS = ROOT / "cadmcp" / "backend" / "solidworks" / "_constants.py"


def module_level_assignments(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in tree.body:  # module level only, not inside classes/functions
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out.add(t.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            out.add(node.target.id)
    return out


orig = module_level_assignments(COM_BACKEND)
new = module_level_assignments(CONSTANTS)

# Only care about constant names of all_caps
orig_caps = {x for x in orig if x.isupper() or x.startswith("_")}
new_caps = {x for x in new if x.isupper() or x.startswith("_")}

missing = orig_caps - new_caps
if missing:
    print("= = = There are more in com_backend.py but these constants are not moved to _constants.py = = =")
    for m in sorted(missing):
        print(f"  {m}")
    print()
    print(f"Total {len (missing)} missing. Please move to _constants.py one by one against the original file.")
else:
    print("✓ All constants moved")
    