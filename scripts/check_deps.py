"""Dependency check (three steps + architecture invariant).

Usage:
    python scripts/check_deps.py

Rules (v1.2.2 § 12.1):
    Step 1: Normalize Physical Paths
    Step 2: Exact matching (startswith forbidden, parent does not override child)
    Step 3: from-import semantic disambiguation (judged by file system)
    + Architecture invariant hard-coded check

S0 Phase: The script can be run, but the index.yaml is not yet complete and may report a large number of errors.
From S1: Gradually tighten after completing INDEX.yaml."""
from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
INDEX_FILE = ROOT / "cadmcp/backend/INDEX.yaml"

BACKEND_ROOT = ROOT / "cadmcp/backend"

# Hard-coded architecture invariants (configurations are not exempt)
INVARIANTS = [
    ("solidworks.sta", "solidworks.infrastructure"),
    ("solidworks.sta", "solidworks.naming"),
    ("solidworks.sta", "solidworks.selection"),
    ("solidworks.sta", "solidworks.geometry"),
    ("solidworks.sta", "solidworks.document"),
    ("solidworks.sta", "solidworks.sketch"),
    ("solidworks.infrastructure", "solidworks.naming"),
    ("solidworks.infrastructure", "solidworks.sketch"),
    ("solidworks.infrastructure", "solidworks.selection"),
    ("solidworks.infrastructure", "solidworks.geometry"),
    ("solidworks.document", "solidworks.backend"),
    ("solidworks.sketch", "solidworks.backend"),
    ("fake", "solidworks"),
    ("solidworks", "fake"),
    ("solidworks.naming", "solidworks.backend"),
    ("solidworks.selection", "solidworks.backend"),
    ("solidworks.geometry", "solidworks.backend"),
    ("solidworks.features", "solidworks.backend"),
    ("solidworks.assembly", "solidworks.backend"),
]

STDLIB = frozenset(sys.stdlib_module_names) | {"__future__"}

# Third-party whitelist (not part of cadmcp.backend but not stdlib)
THIRD_PARTY = {
    "pythoncom", "pywintypes",
    "win32com", "win32com.client", "win32com.server",
    "win32gui", "win32process", "win32con", "win32api",
    "win32event", "winerror",
    "pydantic", "pydantic_core",
    "yaml",
}

# Old files not scanned/shim/not in this split scope
SKIP_FILES = {
    "cadmcp/backend/export_formats.py",
}

def _module_exists(dotted: str) -> bool:
    """Check if dotted can be imported (not really imported)."""
    try:
        return importlib.util.find_spec(dotted) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False

def load_index() -> dict:
    if not INDEX_FILE.exists():
        print(f"⚠ Index.yaml does not exist: {INDEX_FILE}")
        return {"modules": {}, "external_deps": []}
    return yaml.safe_load(INDEX_FILE.read_text(encoding="utf-8")) or {}


def physical_to_logical(module_path: str) -> str | None:
    """Physical import path → logical module name."""
    if module_path.startswith("cadmcp.backend.protocol"):
        return module_path.replace("cadmcp.backend.", "")
    if module_path.startswith("cadmcp.backend.solidworks"):
        return module_path.replace("cadmcp.backend.", "")
    if module_path.startswith("cadmcp.backend.fake"):
        return module_path.replace("cadmcp.backend.", "")
    return None


def path_exists_as_module(dotted: str) -> bool:
    """Check if X/Y.py or X/Y/__init__.py exists (not imported)."""
    parts = dotted.split(".")
    # cadmcp/backend/... → starting with root
    if parts[0] != "cadmcp":
        return False
    base = ROOT / parts[0]
    for p in parts[1:]:
        base = base / p
    return (base.with_suffix(".py")).exists() or (base / "__init__.py").exists()


def iter_imports(file: Path) -> list[tuple[int, str, list[str] | None]]:
    """Returns [(lineno, module, names_or_None)]."""
    try:
        tree = ast.parse(file.read_text(encoding="utf-8"))
    except Exception:
        return []
    out: list[tuple[int, str, list[str] | None]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            # AST puts the hierarchy of relative imports at node.level, and the module
            # name itself does not have a dot; revert here to ".x"/".. x" for
            # resolve_import_target.
            module = "." * node.level + (node.module or "")
            out.append((node.lineno, module, [a.name for a in node.names]))
        elif isinstance(node, ast.Import):
            for a in node.names:
                out.append((node.lineno, a.name, None))
    return out


def resolve_import_target(
    current_module: str,
    module: str,
    names: list[str] | None,
    *,
    is_package: bool = False,
) -> list[str]:
    """Resolve import target logical module (Step 1 + Step 3).

    Returns possible target logical modules (for-import may involve several).
  When `is_package` is true the current file is `__init__.py`, so relative imports
    are resolved from the package itself (not its parent).
    """
    # Relative import
    if module == "" or module.startswith("."):
        base_parts = current_module.split(".")
        level = 0
        while level < len(module) and module[level] == ".":
            level += 1
        rest = module[level:]
        pkg_parts = base_parts if is_package else base_parts[:-1]
        if level - 1 > len(pkg_parts):
            return []
        base = pkg_parts[: len(pkg_parts) - (level - 1)]
        if rest:
            base.extend(rest.split("."))
        module = ".".join(base)

    #Return empty if not in this project (cadmcp.backend) (checked separately by external_deps)    if not module.startswith("cadmcp.backend"):
        return [module] if module else []

    #Step 3: Disambiguation from X import Y    if names is not None:
        targets = []
        for name in names:
            candidate = f"{module}.{name}"
            if path_exists_as_module(candidate):
                targets.append(candidate)
            else:
                targets.append(module)
        return targets

    return [module]


def logical_of(current_file: Path) -> str | None:
    """File path → logical module name."""
    try:
        rel = current_file.relative_to(BACKEND_ROOT)
    except ValueError:
        return None
    parts = list(rel.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def main() -> int:
    index = load_index()
    modules = index.get("modules", {})
    external = set(index.get("external_deps", []))

    errors: list[str] = []
    invariant_errors: list[str] = []

    for py_file in BACKEND_ROOT.rglob("*.py"):
        if "_baseline" in py_file.parts or "__pycache__" in py_file.parts:
            continue
        rel = py_file.relative_to(ROOT).as_posix()
        if rel in SKIP_FILES:
            continue
        current_logical = logical_of(py_file)
        if current_logical is None:
            continue
        #Stage A: INDEX.modules did not declare the module → to skip the deps declaration check        if current_logical not in modules:
            continue
        declared = modules.get(current_logical, {}).get("deps", [])
        declared_modules = {d["module"] if isinstance(d, dict) else d for d in declared}

        for lineno, module, names in iter_imports(py_file):
            targets = resolve_import_target(
                current_logical,
                module,
                names,
                is_package=py_file.name == "__init__.py",
            )
            for target in targets:
                if not target:
                    continue

                #① May not have cadmcp.backend. prefix after relative import parsing                #If target can be spelled cadmcp.backend.<target> and exists, deemed to be included in the package                if not target.startswith("cadmcp.backend"):
                    if _module_exists(f"cadmcp.backend.{target}"):
                        target = f"cadmcp.backend.{target}"

                #② External dependencies: stdlib/third_party/external_deps whitelist                if not target.startswith("cadmcp.backend"):
                    top = target.split(".")[0]
                    if top in STDLIB:
                        continue
                    if top in THIRD_PARTY or target in THIRD_PARTY:
                        continue
                    if target not in external and not any(
                        target == e or target.startswith(f"{e}.")
                        for e in external
                    ):
                        errors.append(
                            f"{rel}:{lineno}: external dependency {target} not in external_deps"
                        )
                    continue

                # in-package dependency
                target_logical = physical_to_logical(target)
                if target_logical is None or target_logical == current_logical:
                    continue

                # architecture invariants (hard-coded; violations exit 1)
                for from_pat, to_pat in INVARIANTS:
                    if current_logical.startswith(from_pat) and target_logical.startswith(to_pat):
                        invariant_errors.append(
                            f"{rel}:{lineno}: violates architecture invariant {from_pat} → {to_pat}"
                        )

                if target_logical not in declared_modules:
                    errors.append(
                        f"{rel}:{lineno}: import {target_logical} not declared in deps"
                    )

    if invariant_errors:
        print("Architecture invariant violations:")
        for e in invariant_errors:
            print(f"  ✗ {e}")
        return 1
    if errors:
        # Stage A: missing deps declarations are warnings until S2 tightens INDEX.yaml
        print(f"Deps declarations to add (tolerated in stage A, tightened in S2): {len(errors)}")
        for e in errors[:5]:
            print(f"  ⚠ {e}")
        if len(errors) > 5:
            print(f"  ... {len(errors) - 5} more")
    print("[OK] Dependency check passed (INVARIANTS hard check only)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
    