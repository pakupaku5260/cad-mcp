"""S2 gate: com.backend.ComBackend MRO has no undeclared private conflicts.

v1.2.2 §4.3.1: each mixin provides `_init_state`, called explicitly from ComBackend.__init__.
`_init_state` is a cooperative-init convention name, not a conflict.

Private methods with the same name (`_xxx`) are conflicts unless declared in INDEX.yaml
`mixin_overrides`.
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
INDEX_FILE = ROOT / "cadmcp" / "backend" / "INDEX.yaml"

# v1.2.2 §4.3.1 cooperative init convention
SKIP_METHODS = {"_init_state"}


def _load_mixin_overrides() -> list[dict]:
    if not INDEX_FILE.exists():
        return []
    data = yaml.safe_load(INDEX_FILE.read_text(encoding="utf-8"))
    return data.get("mixin_overrides") or []


def test_no_undeclared_private_conflict():
    """ComBackend MRO: no undeclared private method conflicts."""
    from cadmcp.backend.solidworks import ComBackend

    declared = {o["method"] for o in _load_mixin_overrides() if "method" in o}

    seen: dict[str, str] = {}
    conflicts: list[str] = []
    for klass in ComBackend.__mro__:
        for name in klass.__dict__:
            if name in SKIP_METHODS:
                continue
            if not name.startswith("_") or name.startswith("__"):
                continue
            if name in seen and seen[name] != klass.__name__:
                if name not in declared:
                    conflicts.append(
                        f"{name}: {seen[name]} and {klass.__name__} both define (undeclared)"
                    )
            seen[name] = klass.__name__

    assert not conflicts, "MRO private conflicts:\n" + "\n".join(conflicts)


def test_mixin_overrides_match_mro():
    """INDEX.yaml mixin_overrides match MRO (S2: empty overrides allowed)."""
    overrides = _load_mixin_overrides()
    if not overrides:
        return  # S2 stage empty
    # If overrides exist, winner must precede overridden in MRO
    from cadmcp.backend.solidworks import ComBackend
    mro = [c.__name__ for c in ComBackend.__mro__]
    for o in overrides:
        winner = o.get("winner")
        for loser in o.get("overridden") or []:
            assert winner in mro and loser in mro, "override references unknown class"
            assert mro.index(winner) < mro.index(loser), (
                f"override {o['method']}: winner={winner} must precede {loser}"
            )
