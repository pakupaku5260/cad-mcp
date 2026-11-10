"""Tool registration and grouping (v4 §5 W2-6): ToolSpec is the sole contract for chat/batch/spec.

ToolSpec rules:
- `handler(ctx, **args)`: explicit keyword signature; **must align 1:1 with input_schema properties**
  (no default ↔ required, default ↔ optional)—enforced by contract tests;
- `mutating=True`: changes model/doc; kernel increments state_version on success;
- `verify_delta=True`: geometry-changing features; kernel fingerprints before/after, attaches Delta + rebuild;
  sketch-only ops are mutating without verify (see kernel docstring);
- `timeout_class`: executor (W3) timeout tier, not tied to side-effect risk;
- `bypass_queue=True`: read-only, never queued (currently status)—server inlines;
  mutually exclusive with mutating; see server docstring. timeout_class still declared but unused.

Toolsets declared at register time; unknown toolset rejected; unknown tool name rejected in kernel.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field

NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

# Toolset id → description for models. M0 implements core; others are placeholders.
TOOLSET_DEFS: dict[str, str] = {
    "core": "Documents, sketches, basic features, queries—minimum viable set",
    "assembly": "Assemblies: insert, mates, component operations",
    "drawing": "Drawings: views, annotations, DrawingSpec, verification",
    "sheetmetal": "Sheet metal: base/flange/miter, hems, flat pattern and DXF",
    "export": "Export: STEP/STL (parts, assemblies) and PDF/DXF (drawings)",
    "sketch_adv": "Advanced sketch: lines, splines, offset, trim, mirror, dims, constraints",
    "features_adv": "Advanced features: thread, helix, sweep, surfaces, thicken, feature ops",
    "view": "View: standard orientations and screenshots",
    "selection": "Selection: face/edge pick, query, GUI pick readback",
}

# Per-toolset token budget (estimate_tokens); over budget fails contract tests.
DEFAULT_TOOLSET_BUDGET_TOKENS = 4000

# Runtime profiles ship only needed toolsets. Each profile must close over dependencies.
# Counts from core_registry() / docs/TOOL_INVENTORY.md—do not hardcode in tests.
TOOLSET_PROFILES: dict[str, tuple[str, ...]] = {
    "full": tuple(TOOLSET_DEFS),
    "part": ("core", "sketch_adv", "features_adv", "selection", "view", "export"),
    "assembly": ("core", "assembly", "selection", "view", "export"),
    "drawing": ("core", "drawing", "view", "export"),
    "sheetmetal": ("core", "sheetmetal", "selection", "view", "export"),
}


def resolve_toolsets(
    names: Iterable[str] | None = None, *, profile: str = "full"
) -> tuple[str, ...]:
    """Resolve --toolsets list or --profile name to deduplicated toolset tuple."""
    if names is None:
        try:
            return TOOLSET_PROFILES[profile]
        except KeyError as exc:
            known = ", ".join(sorted(TOOLSET_PROFILES))
            raise ValueError(f"Unknown profile {profile!r}; choose {known}") from exc
    resolved = tuple(dict.fromkeys(n.strip() for n in names if n.strip()))
    unknown = [n for n in resolved if n not in TOOLSET_DEFS]
    if unknown:
        known = ", ".join(sorted(TOOLSET_DEFS))
        raise ValueError(f"Unknown toolset {unknown!r}; choose {known}")
    return resolved

TIMEOUT_CLASSES: frozenset[str] = frozenset({"fast", "normal", "slow"})


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict
    handler: Callable[..., dict]
    toolset: str = "core"
    mutating: bool = False
    verify_delta: bool = False
    timeout_class: str = "normal"
    examples: tuple[str, ...] = field(default_factory=tuple)
    bypass_queue: bool = False  # read-only, not queued (status); see module docstring


class ToolRegistry:
    """Register-time structural checks; query by name or toolset."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> ToolSpec:
        if not NAME_PATTERN.match(spec.name):
            raise ValueError(f"Invalid tool name {spec.name!r}: must be snake_case starting with a letter")
        if spec.name in self._tools:
            raise ValueError(f"Duplicate tool registration: {spec.name}")
        if spec.toolset not in TOOLSET_DEFS:
            raise ValueError(f"Unknown toolset {spec.toolset!r}: declare in TOOLSET_DEFS first")
        if spec.timeout_class not in TIMEOUT_CLASSES:
            raise ValueError(f"Unknown timeout_class {spec.timeout_class!r}; choose {sorted(TIMEOUT_CLASSES)}")
        if spec.bypass_queue and spec.mutating:
            raise ValueError(
                f"Tool {spec.name} has bypass_queue but is mutating: inline would bypass busy reject and queue"
            )
        if not spec.description.strip():
            raise ValueError(f"Tool {spec.name} missing description (models rely on it)")
        if spec.input_schema.get("type") != "object":
            raise ValueError(f"Tool {spec.name} input_schema root must be object")
        self._tools[spec.name] = spec
        return spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def all(self) -> list[ToolSpec]:
        return [self._tools[n] for n in self.names()]

    def by_toolset(self, toolset: str) -> list[ToolSpec]:
        return [s for s in self.all() if s.toolset == toolset]

    def __iter__(self) -> Iterator[ToolSpec]:
        return iter(self.all())

    def __len__(self) -> int:
        return len(self._tools)


def make_schema(properties: dict, required: list[str] | None = None) -> dict:
    """Build input_schema: object + additionalProperties:false.

    Omit empty required: schema-equivalent, saves payload across many tools.
    """
    schema = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


def estimate_tokens(text: str) -> int:
    """Rough tokens: 1 per CJK char, else len/4—enough for budget gates."""
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return cjk + (len(text) - cjk) // 4


def spec_tokens(spec: ToolSpec) -> int:
    """Estimated tools/list cost for one tool (name + description + schema JSON)."""
    return estimate_tokens(spec.name + " " + spec.description + json.dumps(spec.input_schema, ensure_ascii=False))
