"""DesignSpec: declarative modeling intent (schema_version 1).

Pure data layer — load JSON, validate structure, return a normalized dict.
No backend / executor / COM. Execution belongs to later milestones (F11+).

Shape (required unless noted)::

    {
      "schema_version": 1,
      "kind": "part" | "assembly" | "drawing",
      "doc": {"title": str, "units": "mm" | "inch"},
      "params": {str: number | bool | string},          # optional, default {}
      "variants": {                                     # optional design table
        str: {str: number | bool | string}              # row name → param overrides
      },
      "features": [
        {
          "name": str,                 # unique
          "tool": str,                 # registered tool name (not checked here)
          "args": object,
          "assert": object,            # optional; keys ⊆ recipe ASSERT_KEYS
          "depends_on": [str, ...]     # optional; must name earlier features, no cycles
        },
        ...
      ],
      "checkpoints": [str, ...],       # optional; subsequence of feature names
      "verify": {                      # optional
        "groups": [...],               # ⊆ VERIFY_GROUPS
        "thresholds": object
      },
      "outputs": [{"kind": "step"|"stl"|"pdf"|"dxf", "path": str}, ...]  # optional
    }

Validation failures raise CadMcpError with INVALID_ARGUMENT (JSON path in message)
or PATH_NOT_FOUND when the file is missing. Callers that need workspace sandboxing
must resolve the path via ensure_input_path before calling load_design_spec.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cadmcp.errors import fail
from cadmcp.recipe import ASSERT_KEYS
from cadmcp.verification import VERIFY_GROUPS

DESIGN_SPEC_SCHEMA_VERSION = 1
KIND_VALUES = frozenset({"part", "assembly", "drawing"})
DOC_UNITS = frozenset({"mm", "inch"})
OUTPUT_KINDS = frozenset({"step", "stl", "pdf", "dxf"})
OUTPUT_KIND_EXTS: dict[str, frozenset[str]] = {
    "step": frozenset({".step", ".stp"}),
    "stl": frozenset({".stl"}),
    "pdf": frozenset({".pdf"}),
    "dxf": frozenset({".dxf"}),
}


def load_design_spec(path: Path) -> dict[str, Any]:
    """Load and validate a DesignSpec JSON file; return a normalized dict."""
    if not path.is_file():
        raise fail(
            "PATH_NOT_FOUND",
            f"DesignSpec not found: {path}",
            "Ensure path is in workspace and readable",
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise fail(
            "INVALID_ARGUMENT",
            f"design_spec: invalid JSON: {exc}",
            "Check JSON syntax",
        ) from exc
    if not isinstance(data, dict):
        raise fail(
            "INVALID_ARGUMENT",
            "design_spec root must be an object",
            "See cadmcp://help/design_spec",
        )
    return _normalize(data)


def _normalize(data: dict[str, Any]) -> dict[str, Any]:
    version = data.get("schema_version")
    if version != DESIGN_SPEC_SCHEMA_VERSION:
        raise fail(
            "INVALID_ARGUMENT",
            f"design_spec.schema_version must be {DESIGN_SPEC_SCHEMA_VERSION}, got {version!r}",
            f"Set schema_version to {DESIGN_SPEC_SCHEMA_VERSION}",
        )

    kind = data.get("kind")
    if kind not in KIND_VALUES:
        raise fail(
            "INVALID_ARGUMENT",
            f"design_spec.kind must be one of {sorted(KIND_VALUES)}, got {kind!r}",
            "Use kind=part|assembly|drawing",
        )

    doc = data.get("doc")
    if not isinstance(doc, dict):
        raise fail(
            "INVALID_ARGUMENT",
            "design_spec.doc must be an object",
            'Example: {"title": "Base plate", "units": "mm"}',
        )
    title = doc.get("title")
    if not isinstance(title, str) or not title.strip():
        raise fail(
            "INVALID_ARGUMENT",
            "design_spec.doc.title must be a non-empty string",
            "Set doc.title",
        )
    units = doc.get("units")
    if units not in DOC_UNITS:
        raise fail(
            "INVALID_ARGUMENT",
            f"design_spec.doc.units must be one of {sorted(DOC_UNITS)}, got {units!r}",
            "Use units=mm|inch",
        )
    doc_out = {"title": title.strip(), "units": units}

    params_raw = data.get("params", {})
    if params_raw is None:
        params_raw = {}
    if not isinstance(params_raw, dict):
        raise fail(
            "INVALID_ARGUMENT",
            "design_spec.params must be an object",
            "Map parameter names to number|bool|string",
        )
    params = _normalize_param_map(params_raw, "design_spec.params")

    variants_raw = data.get("variants", {})
    if variants_raw is None:
        variants_raw = {}
    if not isinstance(variants_raw, dict):
        raise fail(
            "INVALID_ARGUMENT",
            "design_spec.variants must be an object",
            'Map row names to param objects, e.g. {"thick": {"thickness": 12}}',
        )
    variants: dict[str, dict[str, Any]] = {}
    for vkey, vparams in variants_raw.items():
        if not isinstance(vkey, str) or not vkey.strip():
            raise fail(
                "INVALID_ARGUMENT",
                "design_spec.variants keys must be non-empty strings",
                "Use a non-empty row name as the variants key",
            )
        vname = vkey.strip()
        if not isinstance(vparams, dict):
            raise fail(
                "INVALID_ARGUMENT",
                f"design_spec.variants.{vname} must be an object",
                "Each variant row maps param names to number|bool|string",
            )
        variants[vname] = _normalize_param_map(
            vparams, f"design_spec.variants.{vname}"
        )

    features_raw = data.get("features")
    if not isinstance(features_raw, list) or not features_raw:
        raise fail(
            "INVALID_ARGUMENT",
            "design_spec.features must be a non-empty array",
            "Add at least one named feature step",
        )

    features: list[dict[str, Any]] = []
    names: list[str] = []
    name_set: set[str] = set()
    for i, item in enumerate(features_raw):
        prefix = f"design_spec.features[{i}]"
        if not isinstance(item, dict):
            raise fail(
                "INVALID_ARGUMENT",
                f"{prefix} must be an object",
                "Each feature needs name/tool/args",
            )
        fname = item.get("name")
        if not isinstance(fname, str) or not fname.strip():
            raise fail(
                "INVALID_ARGUMENT",
                f"{prefix}.name must be a non-empty string",
                "Give each feature a unique name",
            )
        fname = fname.strip()
        if fname in name_set:
            raise fail(
                "INVALID_ARGUMENT",
                f"{prefix}.name duplicates earlier feature {fname!r}",
                "Feature names must be unique",
            )
        name_set.add(fname)
        names.append(fname)

        tool = item.get("tool")
        if not isinstance(tool, str) or not tool.strip():
            raise fail(
                "INVALID_ARGUMENT",
                f"{prefix}.tool must be a non-empty string",
                "tool is a registered tool name (checked at run time)",
            )

        args = item.get("args", {})
        if args is None:
            args = {}
        if not isinstance(args, dict):
            raise fail(
                "INVALID_ARGUMENT",
                f"{prefix}.args must be an object",
                "Pass a JSON object of tool arguments",
            )

        feat: dict[str, Any] = {
            "name": fname,
            "tool": tool.strip(),
            "args": dict(args),
        }

        assertion = item.get("assert")
        if assertion is not None:
            if not isinstance(assertion, dict):
                raise fail(
                    "INVALID_ARGUMENT",
                    f"{prefix}.assert must be an object",
                    f"Allowed keys: {', '.join(sorted(ASSERT_KEYS))}",
                )
            bad = sorted(set(assertion) - ASSERT_KEYS)
            if bad:
                raise fail(
                    "INVALID_ARGUMENT",
                    f"{prefix}.assert has unknown keys {bad}",
                    f"Allowed keys: {', '.join(sorted(ASSERT_KEYS))}",
                )
            feat["assert"] = dict(assertion)

        depends = item.get("depends_on")
        if depends is not None:
            if not isinstance(depends, list) or not all(isinstance(d, str) for d in depends):
                raise fail(
                    "INVALID_ARGUMENT",
                    f"{prefix}.depends_on must be an array of strings",
                    "List feature names this step depends on",
                )
            feat["depends_on"] = [str(d).strip() for d in depends]

        features.append(feat)

    # depends_on: references exist + no cycles
    for i, feat in enumerate(features):
        deps = feat.get("depends_on") or []
        for dep in deps:
            if dep not in name_set:
                raise fail(
                    "INVALID_ARGUMENT",
                    f"design_spec.features[{i}].depends_on references unknown {dep!r}",
                    "depends_on must name another features[].name",
                )
    cycle = _find_cycle({f["name"]: list(f.get("depends_on") or []) for f in features})
    if cycle is not None:
        raise fail(
            "INVALID_ARGUMENT",
            f"design_spec.features depends_on cycle: {' -> '.join(cycle)}",
            "Remove the cyclic depends_on edge",
        )

    checkpoints_raw = data.get("checkpoints", [])
    if checkpoints_raw is None:
        checkpoints_raw = []
    if not isinstance(checkpoints_raw, list) or not all(
        isinstance(c, str) for c in checkpoints_raw
    ):
        raise fail(
            "INVALID_ARGUMENT",
            "design_spec.checkpoints must be an array of strings",
            "List feature names in features order",
        )
    checkpoints = [c.strip() for c in checkpoints_raw]
    for c in checkpoints:
        if c not in name_set:
            raise fail(
                "INVALID_ARGUMENT",
                f"design_spec.checkpoints references unknown feature {c!r}",
                "checkpoints must be a subset of features[].name",
            )
    if not _is_subsequence(checkpoints, names):
        raise fail(
            "INVALID_ARGUMENT",
            "design_spec.checkpoints must follow features[] order",
            "Reorder checkpoints to match feature declaration order",
        )

    verify_raw = data.get("verify")
    verify_out: dict[str, Any] = {"groups": [], "thresholds": {}}
    if verify_raw is not None:
        if not isinstance(verify_raw, dict):
            raise fail(
                "INVALID_ARGUMENT",
                "design_spec.verify must be an object",
                'Example: {"groups": ["geometry"], "thresholds": {}}',
            )
        groups = verify_raw.get("groups", [])
        if groups is None:
            groups = []
        if not isinstance(groups, list):
            raise fail(
                "INVALID_ARGUMENT",
                "design_spec.verify.groups must be an array",
                f"Choose from: {', '.join(VERIFY_GROUPS)}",
            )
        cleaned_groups: list[str] = []
        for gi, g in enumerate(groups):
            if not isinstance(g, str) or g not in VERIFY_GROUPS:
                raise fail(
                    "INVALID_ARGUMENT",
                    f"design_spec.verify.groups[{gi}] invalid: {g!r}",
                    f"Choose from: {', '.join(VERIFY_GROUPS)}",
                )
            cleaned_groups.append(g)
        thresholds = verify_raw.get("thresholds", {})
        if thresholds is None:
            thresholds = {}
        if not isinstance(thresholds, dict):
            raise fail(
                "INVALID_ARGUMENT",
                "design_spec.verify.thresholds must be an object",
                "Pass verify_model-compatible thresholds",
            )
        verify_out = {"groups": cleaned_groups, "thresholds": dict(thresholds)}

    outputs_raw = data.get("outputs", [])
    if outputs_raw is None:
        outputs_raw = []
    if not isinstance(outputs_raw, list):
        raise fail(
            "INVALID_ARGUMENT",
            "design_spec.outputs must be an array",
            'Items like {"kind": "step", "path": "out/base.step"}',
        )
    outputs: list[dict[str, str]] = []
    for oi, item in enumerate(outputs_raw):
        prefix = f"design_spec.outputs[{oi}]"
        if not isinstance(item, dict):
            raise fail(
                "INVALID_ARGUMENT",
                f"{prefix} must be an object",
                "Include kind and path",
            )
        okind = item.get("kind")
        if okind not in OUTPUT_KINDS:
            raise fail(
                "INVALID_ARGUMENT",
                f"{prefix}.kind must be one of {sorted(OUTPUT_KINDS)}, got {okind!r}",
                "Use kind=step|stl|pdf|dxf",
            )
        opath = item.get("path")
        if not isinstance(opath, str) or not opath.strip():
            raise fail(
                "INVALID_ARGUMENT",
                f"{prefix}.path must be a non-empty string",
                "Set an output path inside the workspace",
            )
        path_s = opath.strip()
        suffix = Path(path_s).suffix.lower()
        allowed = OUTPUT_KIND_EXTS[str(okind)]
        if suffix not in allowed:
            raise fail(
                "INVALID_ARGUMENT",
                f"{prefix} kind {okind!r} requires suffix in {sorted(allowed)}, "
                f"got {suffix or '(none)'!r}",
                "Align outputs[].kind with the file extension (step↔.step/.stp)",
            )
        outputs.append({"kind": str(okind), "path": path_s})

    return {
        "schema_version": DESIGN_SPEC_SCHEMA_VERSION,
        "kind": kind,
        "doc": doc_out,
        "params": params,
        "variants": variants,
        "features": features,
        "checkpoints": checkpoints,
        "verify": verify_out,
        "outputs": outputs,
    }


def _normalize_param_map(raw: dict[str, Any], path_prefix: str) -> dict[str, Any]:
    """Validate a param object; values must be number|bool|string (bool ≠ int)."""
    out: dict[str, Any] = {}
    for key, value in raw.items():
        name = str(key)
        if type(value) is bool or type(value) in (int, float) or isinstance(value, str):
            out[name] = value
        else:
            raise fail(
                "INVALID_ARGUMENT",
                f"{path_prefix}.{name} must be number|bool|string, got {type(value).__name__}",
                "Use a JSON number, boolean, or string",
            )
    return out


def select_variant(spec: dict[str, Any], variant: str | None) -> dict[str, Any]:
    """Return effective params for a run (base ∪ variant overrides). Does not mutate spec.

    ``variant is None`` → base params only (current behaviour).
    Unknown name or missing/empty variants table → INVALID_ARGUMENT (zero side effects).
    """
    base = dict(spec.get("params") or {})
    if variant is None:
        return base
    variants = spec.get("variants") or {}
    if not isinstance(variants, dict) or not variants:
        raise fail(
            "INVALID_ARGUMENT",
            f"variant {variant!r} requested but design_spec.variants is empty",
            "Declare design_spec.variants or omit the variant argument",
        )
    if variant not in variants:
        known = ", ".join(sorted(variants)) or "(none)"
        raise fail(
            "INVALID_ARGUMENT",
            f"unknown variant {variant!r}; known: {known}",
            "Pass a variants key or omit variant",
        )
    merged = dict(base)
    merged.update(dict(variants[variant]))
    return merged


def _is_subsequence(sub: list[str], full: list[str]) -> bool:
    if not sub:
        return True
    it = iter(full)
    return all(any(x == item for x in it) for item in sub)


def _find_cycle(graph: dict[str, list[str]]) -> list[str] | None:
    """Return a cycle path (node list ending with start) or None."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in graph}
    parent: dict[str, str | None] = {n: None for n in graph}

    def dfs(u: str) -> list[str] | None:
        color[u] = GRAY
        for v in graph.get(u, []):
            if v not in color:
                continue
            if color[v] == GRAY:
                # v is an ancestor on the DFS stack: walk parents from u back to v.
                path = [u]
                cur: str | None = u
                while cur != v:
                    cur = parent[cur]
                    if cur is None:  # defensive: a GRAY node always has a parent chain to v
                        return [v, u, v]
                    path.append(cur)
                path.reverse()
                return [*path, v]
            if color[v] == WHITE:
                parent[v] = u
                found = dfs(v)
                if found is not None:
                    return found
        color[u] = BLACK
        return None

    for node in graph:
        if color[node] == WHITE:
            found = dfs(node)
            if found is not None:
                return found
    return None


__all__ = [
    "DESIGN_SPEC_SCHEMA_VERSION",
    "DOC_UNITS",
    "KIND_VALUES",
    "OUTPUT_KIND_EXTS",
    "OUTPUT_KINDS",
    "load_design_spec",
    "select_variant",
]
