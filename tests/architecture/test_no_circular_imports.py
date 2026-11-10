"""S1 gate: import graph has no cycles."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "cadmcp" / "backend"


def _iter_imports(file: Path) -> set[str]:
    tree = ast.parse(file.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
        elif isinstance(node, ast.Import):
            for name in node.names:
                out.add(name.name)
    return out


def _file_to_module(file: Path) -> str:
    rel = file.relative_to(ROOT)
    parts = list(rel.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _build_graph() -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {}
    for py_file in BACKEND.rglob("*.py"):
        if "_baseline" in py_file.parts or "__pycache__" in py_file.parts:
            continue
        mod = _file_to_module(py_file)
        imports = _iter_imports(py_file)
        # Keep only in-repo backend deps
        targets = {
            imp for imp in imports
            if imp.startswith("cadmcp.backend")
        }
        graph[mod] = targets
    return graph


def _has_cycle(graph: dict[str, set[str]]) -> list[str]:
    """Detect a cycle; return the cycle path."""
    visited: set[str] = set()
    path: list[str] = []

    def dfs(node: str) -> list[str] | None:
        if node in path:
            return path[path.index(node) :] + [node]
        if node in visited:
            return None
        visited.add(node)
        path.append(node)
        for nxt in graph.get(node, ()):
            cycle = dfs(nxt)
            if cycle:
                return cycle
        path.pop()
        return None

    for node in graph:
        cycle = dfs(node)
        if cycle:
            return cycle
    return []


def test_no_circular_imports():
    graph = _build_graph()
    cycle = _has_cycle(graph)
    assert not cycle, f"Circular import: {' -> '.join(cycle)}"
