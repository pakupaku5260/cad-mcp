"""Static checks (v4 §12–13): conversion literals, win32com whitelist, dangerous calls.

CI static scan as pytest, wired into local check.
Exempt a line with `# unit-allow: reason` at EOL.
"""

import re
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "cadmcp"

CONVERSION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?<![\w.])0\.001(?![\d.])"), "m↔mm (0.001)"),
    (re.compile(r"(?<![\w.])1e-3(?![\d.eE])"), "m↔mm (1e-3)"),
    (re.compile(r"(?<![\w.])25\.4(?![\d.])"), "in→m (25.4)"),
    (re.compile(r"(?<![\w.])304\.8(?![\d.])"), "ft→m (304.8)"),
    (re.compile(r"(?<![\w.])1e6(?![\d.eE])"), "m²→mm² (1e6)"),
    (re.compile(r"(?<![\w.])1e9(?![\d.eE])"), "m³→mm³ (1e9)"),
    (re.compile(r"(?<![\w.])([*\/]) ?1000(?![\d.])"), "m↔mm (×/÷ 1000)"),
]

WIN32_TOKEN_RE = re.compile(r"\b(win32com|pythoncom|win32gui|win32api)\b")
WIN32_ALLOWED = {
    "cli.py",
    "backend/solidworks/probe.py",
    "backend/solidworks/sta.py",
    "backend/solidworks/assembly/mate.py",
    "backend/solidworks/infrastructure.py",
    "backend/solidworks/selection.py",
    "backend/solidworks/geometry.py",
    "backend/solidworks/sketch/draw.py",
    "backend/solidworks/sketch/lifecycle.py",
    "backend/solidworks/sketch/constraints.py",
    "backend/solidworks/sketch/modify.py",
    "backend/solidworks/drawing.py",
    "backend/solidworks/document.py",
    "backend/solidworks/plane_axis.py",
    "backend/solidworks/config.py",
    "backend/solidworks/features/modify.py",
    "backend/solidworks/features/surface.py",
    "backend/solidworks/features/sheetmetal.py",
}

DANGEROUS_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bexec\s*\("), "exec"),
    (re.compile(r"\beval\s*\("), "eval"),
    (re.compile(r"(?<!\.)\bcompile\s*\("), "compile(builtin)"),  # re.compile ok
    (re.compile(r"\b__import__\b"), "__import__"),
    (re.compile(r"\bos\.system\b"), "os.system"),
    (re.compile(r"\bsubprocess\."), "subprocess."),
    (re.compile(r"\bimport\s+subprocess\b"), "import subprocess"),
    (re.compile(r"\bfrom\s+subprocess\b"), "from subprocess"),
    (re.compile(r"\bos\.popen\b"), "os.popen"),
    (re.compile(r"\bos\.exec"), "os.exec*"),
]


def _py_lines(exclude_names: tuple[str, ...] = ()):
    for f in sorted(PKG.rglob("*.py")):
        if f.name in exclude_names:
            continue
        for lineno, line in enumerate(f.read_text("utf-8").splitlines(), 1):
            yield f, lineno, line


def _where(f: Path, lineno: int, line: str) -> str:
    return f"{f.relative_to(PKG.parent)}:{lineno}: {line.strip()}"


def test_no_scattered_unit_conversion():
    """Conversion literals only in units.py."""
    violations = []
    for f, lineno, line in _py_lines(exclude_names=("units.py",)):
        if "# unit-allow" in line:
            continue
        code = line.split("#", 1)[0]  # ignore comments
        for pat, why in CONVERSION_PATTERNS:
            if pat.search(code):
                violations.append(_where(f, lineno, line) + f"  ← {why}")
    assert not violations, (
        "Scattered conversions (use UnitContext):\n"
        + "\n".join(violations)
        + "\nExempt with `# unit-allow: reason`"
    )


def test_win32_imports_whitelisted():
    """win32 imports only in whitelist (v4 §13)."""
    violations = []
    for f, lineno, line in _py_lines():
        rel = f.relative_to(PKG).as_posix()  # backslash whitelist
        if rel in WIN32_ALLOWED:
            continue
        if WIN32_TOKEN_RE.search(line.split("#", 1)[0]):
            violations.append(_where(f, lineno, line))
    assert not violations, (
        "win32 import/token only in "
        f"{sorted(WIN32_ALLOWED)}:\n" + "\n".join(violations)
    )


def test_no_dangerous_calls():
    """No arbitrary code execution (v4 §11)."""
    violations = []
    for f, lineno, line in _py_lines():
        code = line.split("#", 1)[0]
        for pat, name in DANGEROUS_PATTERNS:
            if pat.search(code):
                violations.append(_where(f, lineno, line) + f"  ← {name}")
    assert not violations, "Dangerous calls:\n" + "\n".join(violations)
