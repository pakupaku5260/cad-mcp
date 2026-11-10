"""S9: capture API baseline after split is complete.

Usage:
    python scripts/snapshot_api_s9.py

Output:
    cadmcp/backend/api_baseline_s9.json

Differences from S0:
    - Uses **new import paths** (S0 used legacy paths); see `SNAPSHOT_TARGETS`;
    - Also checks legacy compat paths still import/getattr (`compat_imports_s9`);
    - One-shot artifact, not in git (v1.2.2 §12.4 exception).

Prerequisites:
    - Split complete (S9);
    - `api_baseline_s9.json` must not exist (no overwrite).

"""
from __future__ import annotations

import importlib
import inspect
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE_FILE = ROOT / "cadmcp/backend/api_baseline_s9.json"

SNAPSHOT_TARGETS: list[tuple[str, str, str]] = [
    ("CADBackend", "cadmcp.backend.protocol.protocol", "CADBackend"),
    ("ComBackend", "cadmcp.backend.solidworks.backend", "ComBackend"),
    ("Win32DialogProbe", "cadmcp.backend.solidworks.probe", "Win32DialogProbe"),
    ("FakeBackend", "cadmcp.backend.fake.backend", "FakeBackend"),
]

COMPAT_IMPORTS: list[dict] = [
    {"path": "cadmcp.backend.protocol.protocol", "name": "CADBackend", "kind": "class"},
    {"path": "cadmcp.backend.solidworks.backend", "name": "ComBackend", "kind": "class"},
    {"path": "cadmcp.backend.solidworks.probe", "name": "Win32DialogProbe", "kind": "class"},
    {"path": "cadmcp.backend.fake.backend", "name": "FakeBackend", "kind": "class"},
]


def snapshot_class(cls) -> dict:
    """Capture all public members of a class (walk MRO, classify by kind)."""
    out: dict = {}
    for klass in reversed(cls.__mro__):
        for name, raw in klass.__dict__.items():
            if name.startswith("_"):
                continue
            if isinstance(raw, staticmethod):
                kind, callable_obj = "staticmethod", raw.__func__
            elif isinstance(raw, classmethod):
                kind, callable_obj = "classmethod", raw.__func__
            elif isinstance(raw, property):
                kind, callable_obj = "property", raw.fget
            elif isinstance(raw, types.FunctionType):
                kind, callable_obj = "method", raw
            else:
                kind, callable_obj = "attribute", None

            try:
                sig = inspect.signature(callable_obj) if callable_obj else None
            except (TypeError, ValueError):
                sig = None

            out[name] = {
                "kind": kind,
                "signature_struct": _signature_to_struct(sig) if sig else None,
                "signature_str": str(sig) if sig else None,
                "source": klass.__name__,
            }
    return out


def _signature_to_struct(sig: inspect.Signature) -> dict:
    params = []
    for p in sig.parameters.values():
        params.append({
            "name": p.name,
            "kind": p.kind.name,
            "default": repr(p.default) if p.default is not inspect.Parameter.empty else None,
            "annotation": (
                str(p.annotation) if p.annotation is not inspect.Parameter.empty else None
            ),
        })
    return {
        "parameters": params,
        "return_annotation": (
            str(sig.return_annotation)
            if sig.return_annotation is not inspect.Signature.empty
            else None
        ),
    }


def _check_compat_import(item: dict) -> dict:
    """Resolve one legacy import path; record availability (no exception)."""
    result = dict(item)
    try:
        module = importlib.import_module(item["path"])
        obj = getattr(module, item["name"])
    except Exception as exc:  # noqa: BLE001
        result.update(ok=False, error=f"{type(exc).__name__}: {exc}")
        return result
    result.update(ok=obj is not None, error=None, resolved=f"{obj.__module__}.{obj.__name__}")
    return result


def main() -> int:
    if BASELINE_FILE.exists():
        print(f"Baseline file exists: {BASELINE_FILE}\nRefusing overwrite.")
        return 1

    classes_to_snapshot: dict[str, dict] = {}
    unavailable: list[dict] = []
    import_paths: dict[str, str] = {}

    for key, module_path, class_name in SNAPSHOT_TARGETS:
        try:
            module = importlib.import_module(module_path)
            cls = getattr(module, class_name)
        except Exception as exc:  # noqa: BLE001
            unavailable.append({
                "class": key,
                "path": f"{module_path}.{class_name}",
                "error": f"{type(exc).__name__}: {exc}",
            })
            continue
        classes_to_snapshot[key] = snapshot_class(cls)
        import_paths[key] = f"{module_path}.{class_name}"

    if "FakeBackend" not in classes_to_snapshot:
        print("[X] Cannot capture FakeBackend; S9 baseline incomplete; aborting.")
        for item in unavailable:
            print(f"  - {item['class']}: {item['error']}")
        return 1

    baseline = {
        "baseline_version": 1,
        "capture_stage": "S9",
        "classes": classes_to_snapshot,
        "import_paths_s9": import_paths,
        "compat_imports_s9": [_check_compat_import(item) for item in COMPAT_IMPORTS],
        "unavailable": unavailable,
    }

    BASELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_FILE.write_text(
        json.dumps(baseline, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"[OK] Saved S9 API baseline: {BASELINE_FILE}")
    print(f"  classes: {list(classes_to_snapshot.keys())}")
    for name, members in classes_to_snapshot.items():
        print(f"    {name}: {len(members)} public members")
    if unavailable:
        print("[!] Classes not captured (compare_api.py will treat as interface diff):")
        for item in unavailable:
            print(f"    {item['class']}: {item['error']}")
    failed = [item for item in baseline["compat_imports_s9"] if not item["ok"]]
    if failed:
        print("[!] Legacy import paths unavailable:")
        for item in failed:
            print(f"    {item['path']}.{item['name']}: {item['error']}")
    else:
        print("[OK] All legacy import paths available")
    return 0


if __name__ == "__main__":
    sys.exit(main())
