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

import inspect
import json
import math
import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field, replace

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
    "verification": "Model verification: geometry, features, mass/bbox, assembly, drawing",
    "transaction": "Transactions: L1 checkpoint/journal + L2 reload/compensate/discard",
    "design": "DesignSpec: declarative part/assembly/drawing intent (validate only)",
    "task": "Task layer: single-job batch execution",
    "rules": "Machine-checkable model rules (read-only check_rules)",
    "diagnostics": "Diagnostics: interpret cadmcp doctor JSON (check_doctor_matrix)",
}

# --- F8 token budgets (tiered) ---
# Large tier 6000 / small tier 4000. DEFAULT is the small-tier fallback for unknown toolsets
# and for ``from cadmcp.registry import DEFAULT_TOOLSET_BUDGET_TOKENS`` compatibility.
DEFAULT_TOOLSET_BUDGET_TOKENS = 4000

TOOLSET_BUDGET_TOKENS: dict[str, int] = {
    "core": 6000,
    "features_adv": 6000,
    "assembly": 6000,
    "drawing": 4000,
    "sketch_adv": 4000,
    "sheetmetal": 4000,
    "selection": 4000,
    "transaction": 4000,
    "verification": 4000,
    "export": 4000,
    "view": 4000,
    "design": 4000,
    "task": 4000,
    "rules": 4000,
    "diagnostics": 4000,
}

# Soft headroom: --strict requires tokens <= floor(0.8 * tier) (large ≤4800, small ≤3200).
TOOLSET_HEADROOM_RATIO = 0.8

# Profile caps: ceil(measured_tokens * 1.08) rounded up to 500 (F8 calibration @ TOTAL=18514),
# then assembly 9688→10500, drawing 8541→9500, sheetmetal 7709→8500.
# F13 exception: part 13500→14500 by explicit decision (measured 13871; the formula would give
# 15000). Raising it further needs the same explicit call, not silent drift.
# F16 R2: part 14500→15500 by F8 formula on post-F15 measured part≈14247:
# ceil(14247 * 1.08)=15387 → round up to 500 → 15500 (explicit; not silent drift).
# ``full`` is warn-only (no hard gate).
PROFILE_TOKEN_BUDGETS: dict[str, int | None] = {
    "full": None,
    "part": 15500,
    "assembly": 10500,
    "drawing": 9500,
    "sheetmetal": 8500,
}

# TOTAL hard gate (F8): ceil(18514 * 1.10) → 20400 (hundreds).
# F16 R1: 20400→22400 by F8 formula on post-F15 measured TOTAL≈20301:
# ceil(20301 * 1.10)=22332 → round up to hundreds → 22400 (explicit).
TOTAL_TOKEN_BUDGET = 22400

BUDGET_CARD_TEXT = (
    "分档 6000/4000，20% 余量上限 4800/3200，"
    "profile 15500/10500/9500/8500（full 仅告警），TOTAL ≤ 22400"
)


def toolset_budget(toolset: str) -> int:
    """Return tier budget for ``toolset``; unknown names fall back to DEFAULT."""
    return TOOLSET_BUDGET_TOKENS.get(toolset, DEFAULT_TOOLSET_BUDGET_TOKENS)


def toolset_headroom_cap(toolset: str) -> int:
    """Max tokens allowed under the ≥20% unused-headroom rule."""
    return int(math.floor(toolset_budget(toolset) * TOOLSET_HEADROOM_RATIO))


# Runtime profiles ship only needed toolsets. Each profile must close over dependencies.
# Counts from core_registry() / docs/TOOL_INVENTORY.md—do not hardcode in tests.
TOOLSET_PROFILES: dict[str, tuple[str, ...]] = {
    # Explicit full surface (F20: diagnostics is admin-only — not in bounded profiles).
    "full": tuple(TOOLSET_DEFS),
    "part": (
        "core",
        "sketch_adv",
        "features_adv",
        "selection",
        "view",
        "export",
        "verification",
        "transaction",
        "design",
        "task",
        "rules",
    ),
    "assembly": ("core", "assembly", "selection", "view", "export", "verification", "transaction"),
    "drawing": ("core", "drawing", "view", "export", "verification", "transaction"),
    "sheetmetal": ("core", "sheetmetal", "selection", "view", "export", "verification", "transaction"),
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

# Call-granularity layers (F14). Not an MCP schema field — metadata only.
# primitive = backend atomic call; domain = domain capability; task = one call carries
# a full intent (call-granularity atomic; internals are not transaction-atomic).
TOOL_LAYERS: tuple[str, ...] = ("primitive", "domain", "task")


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
    layer: str = "domain"  # TOOL_LAYERS; default keeps existing tools as domain


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
        if spec.layer not in TOOL_LAYERS:
            raise ValueError(
                f"Unknown layer {spec.layer!r} for tool {spec.name}: choose {list(TOOL_LAYERS)}"
            )
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


# F6: compact optional doc-context guards (semantics in WRONG_DOCUMENT hint / docs).
EXPECT_TITLE = "expect_title"
EXPECT_PATH = "expect_path"
_EXPECT_PROPS: dict = {
    EXPECT_TITLE: {"type": ["string", "null"], "default": None},
    EXPECT_PATH: {"type": ["string", "null"], "default": None},
}


def with_doc_guard(spec: ToolSpec) -> ToolSpec:
    """Inject expect_title/expect_path into mutating tool schema + handler signature.

    Kernel validates and pops these before side effects; the wrapper only keeps
    schema↔handler contract alignment (defaults apply when Kernel strips them).
    """
    if not spec.mutating:
        return spec
    props = dict(spec.input_schema.get("properties") or {})
    if EXPECT_TITLE in props and EXPECT_PATH in props:
        return spec
    props = {**props, **_EXPECT_PROPS}
    schema = {**spec.input_schema, "properties": props}

    orig = spec.handler
    orig_sig = inspect.signature(orig)
    params = list(orig_sig.parameters.values())
    insert_at = len(params)
    for i, p in enumerate(params):
        if p.kind == inspect.Parameter.VAR_KEYWORD:
            insert_at = i
            break
    extra = [
        inspect.Parameter(EXPECT_TITLE, inspect.Parameter.KEYWORD_ONLY, default=None),
        inspect.Parameter(EXPECT_PATH, inspect.Parameter.KEYWORD_ONLY, default=None),
    ]
    new_sig = orig_sig.replace(parameters=params[:insert_at] + extra + params[insert_at:])

    def guarded_handler(*args, **kwargs):
        ba = new_sig.bind(*args, **kwargs)
        ba.apply_defaults()
        return orig(**{name: ba.arguments[name] for name in orig_sig.parameters})

    guarded_handler.__signature__ = new_sig  # type: ignore[attr-defined]
    guarded_handler.__name__ = getattr(orig, "__name__", "handler")
    guarded_handler.__doc__ = getattr(orig, "__doc__", None)
    return replace(spec, input_schema=schema, handler=guarded_handler)


def estimate_tokens(text: str) -> int:
    """Rough tokens: 1 per CJK char, else len/4—enough for budget gates."""
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return cjk + (len(text) - cjk) // 4


def spec_tokens(spec: ToolSpec) -> int:
    """Estimated tools/list cost for one tool (name + description + schema JSON)."""
    return estimate_tokens(spec.name + " " + spec.description + json.dumps(spec.input_schema, ensure_ascii=False))
