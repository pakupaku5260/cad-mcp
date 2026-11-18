"""Rules toolset (F16): readonly machine-checkable model rules via check_rules."""
from __future__ import annotations

from typing import Any

from cadmcp.errors import fail
from cadmcp.kernel import OpContext
from cadmcp.registry import ToolSpec, make_schema
from cadmcp.rules import RULES, evaluate_rules
from cadmcp.verification import build_task_verification

_CHECK_DESCRIPTION = (
    "Run machine-checkable model rules against a readonly fact snapshot "
    "(active document, features, part_parameters, sketch_status, interference). "
    "Does not call verify_model; never mutates or bumps state_version. "
    "rules=null runs all ten; a name list runs a subset. "
    "Unknown names → INVALID_ARGUMENT. Missing facts skip that rule (not fail). "
    "Returns {verification, rules_run, skipped}. "
    "Read cadmcp://help/rules before choosing a subset."
)


def _dispatch_payload(ctx: OpContext, name: str, args: dict | None = None) -> dict | None:
    """Inline readonly dispatch; failure → None (fact missing)."""
    if ctx.dispatch is None:
        return None
    result = ctx.dispatch(name, args or {})
    if not result.ok or result.result is None:
        return None
    return result.result


def _collect_sketch_statuses(ctx: OpContext, features_payload: dict | None) -> list[dict] | None:
    """Build sketch_statuses from open sketch + feature names + contiguous SketchN probe.

    Fact is present when list_features succeeded or at least one status was collected.
    Contiguous SketchN probe covers Fake backends that omit sketches from list_features.
    """
    out: list[dict] = []
    seen: set[str] = set()

    open_st = _dispatch_payload(ctx, "sketch_status", {})
    if open_st is not None:
        out.append(open_st)
        name = open_st.get("sketch")
        if isinstance(name, str) and name:
            seen.add(name)

    features_ok = features_payload is not None
    if features_ok:
        for feat in features_payload.get("features") or []:
            name = feat.get("name") or ""
            kind = str(feat.get("kind") or "").lower()
            if not name or name in seen:
                continue
            if kind != "sketch" and not (
                name.startswith("Sketch") and name[6:].isdigit()
            ):
                continue
            st = _dispatch_payload(ctx, "sketch_status", {"sketch": name})
            if st is not None:
                out.append(st)
                seen.add(name)

    for i in range(1, 33):
        name = f"Sketch{i}"
        if name in seen:
            continue
        st = _dispatch_payload(ctx, "sketch_status", {"sketch": name})
        if st is None:
            break
        out.append(st)
        seen.add(name)

    if features_ok or out:
        return out
    return None


def collect_facts(ctx: OpContext) -> dict[str, Any]:
    """Gather readonly fact snapshot for evaluate_rules. Omits keys on failure."""
    facts: dict[str, Any] = {}

    active = _dispatch_payload(ctx, "get_active_document", {})
    if active is not None:
        facts["active_document"] = active

    features = _dispatch_payload(ctx, "list_features", {})
    if features is not None:
        facts["features"] = features

    params = _dispatch_payload(ctx, "part_parameters", {})
    if params is not None:
        facts["part_parameters"] = params

    sketch_statuses = _collect_sketch_statuses(ctx, features)
    if sketch_statuses is not None:
        facts["sketch_statuses"] = sketch_statuses

    # Interference only meaningful for assemblies; still attempt when doc_type matches
    # so a failed call yields skip (missing) rather than a false clear.
    if active is not None and active.get("doc_type") == "assembly":
        inter = _dispatch_payload(ctx, "check_interference", {})
        if inter is not None:
            facts["interference"] = inter

    return facts


def check_rules(ctx: OpContext, rules: list | None = None) -> dict:
    """Evaluate selected rules; payload is {verification, rules_run, skipped}."""
    if rules is not None:
        if not isinstance(rules, list) or not all(isinstance(n, str) for n in rules):
            raise fail(
                "INVALID_ARGUMENT",
                "rules must be null or an array of rule name strings",
                "Pass null for all rules, or e.g. [\"active_document\",\"units_declared\"]",
            )

    facts = collect_facts(ctx)
    checks, skipped = evaluate_rules(facts, rules)
    verification = build_task_verification(checks)
    if rules is None:
        rules_run = [r.name for r in RULES]
    else:
        # Deduped order matching evaluate_rules
        rules_run = list(dict.fromkeys(rules))

    return {
        "verification": verification.model_dump(),
        "rules_run": rules_run,
        "skipped": skipped,
    }


RULES_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="check_rules",
        toolset="rules",
        description=_CHECK_DESCRIPTION,
        input_schema=make_schema(
            {
                "rules": {
                    "type": ["array", "null"],
                    "default": None,
                    "items": {"type": "string"},
                    "description": (
                        "Rule names to run; null (default) runs all ten. "
                        "Unknown names → INVALID_ARGUMENT."
                    ),
                },
            },
        ),
        handler=check_rules,
        mutating=False,
        bypass_queue=True,
        timeout_class="fast",
        layer="domain",
    ),
]

__all__ = ["RULES_SPECS", "check_rules", "collect_facts"]
