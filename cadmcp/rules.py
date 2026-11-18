"""Machine-checkable model rules (F16). Pure evaluation — no COM/dispatch/backend.

Fact keys (populated by ``check_rules`` via readonly tool dispatch):

- ``active_document``: get_active_document payload
  (``title/path/doc_type/modified/units/configuration/epoch/saved``)
- ``features``: list_features payload (``features`` list of ``{name,kind}``)
- ``part_parameters``: part_parameters payload
  (``dimensions/equations/configurations/count/...``)
- ``sketch_statuses``: list of sketch_status payloads (``state/dof/sketch``)
- ``interference``: check_interference payload (``count/pairs/method/...``)

Missing required facts → rule goes to ``skipped`` (not a failed check).
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from cadmcp.errors import fail
from cadmcp.result import VerificationCheck

# check returns VerificationCheck on pass/fail, or a skip-reason string.
CheckFn = Callable[[dict[str, Any]], VerificationCheck | str]


@dataclass(frozen=True)
class Rule:
    name: str
    description: str
    requires: frozenset[str]
    check: CheckFn


_ALLOWED_UNITS = frozenset({"mm", "inch"})


def _rhs(expression: str) -> str:
    text = str(expression)
    if "=" in text:
        return text.split("=", 1)[1].strip()
    return text.strip()


def _active_document(facts: dict[str, Any]) -> VerificationCheck | str:
    doc = facts.get("active_document")
    if doc is None:
        return "missing active_document"
    return VerificationCheck(
        name="active_document",
        ok=True,
        detail="active document present",
    )


def _units_declared(facts: dict[str, Any]) -> VerificationCheck | str:
    doc = facts.get("active_document")
    if doc is None:
        return "missing active_document"
    units = doc.get("units")
    ok = units in _ALLOWED_UNITS
    return VerificationCheck(
        name="units_declared",
        ok=ok,
        detail=f"units={units!r}" if ok else f"units={units!r} not in {{mm, inch}}",
    )


def _feature_tree_present(facts: dict[str, Any]) -> VerificationCheck | str:
    doc = facts.get("active_document")
    if doc is None:
        return "missing active_document"
    doc_type = doc.get("doc_type")
    if doc_type not in {"part", "assembly"}:
        return f"doc_type={doc_type!r} is not part/assembly"
    feat_payload = facts.get("features")
    if feat_payload is None:
        return "missing features"
    features = feat_payload.get("features") or []
    count = len(features)
    ok = count >= 1
    return VerificationCheck(
        name="feature_tree_present",
        ok=ok,
        detail=f"feature_count={count}",
    )


def _positive_dimensions(facts: dict[str, Any]) -> VerificationCheck | str:
    params = facts.get("part_parameters")
    if params is None:
        return "missing part_parameters"
    dims = params.get("dimensions") or []
    bad = [d.get("name") for d in dims if not (isinstance(d.get("value"), (int, float)) and d["value"] > 0)]
    ok = not bad
    return VerificationCheck(
        name="positive_dimensions",
        ok=ok,
        detail="all dimension values > 0" if ok else f"non-positive: {bad}",
    )


def _equations_nonempty(facts: dict[str, Any]) -> VerificationCheck | str:
    params = facts.get("part_parameters")
    if params is None:
        return "missing part_parameters"
    eqs = params.get("equations") or []
    bad = [e.get("name") for e in eqs if not _rhs(e.get("expression") or "")]
    ok = not bad
    return VerificationCheck(
        name="equations_nonempty",
        ok=ok,
        detail="all equation RHS non-empty" if ok else f"empty RHS: {bad}",
    )


def _configuration_present(facts: dict[str, Any]) -> VerificationCheck | str:
    params = facts.get("part_parameters")
    if params is None:
        return "missing part_parameters"
    configs = params.get("configurations") or []
    count = len(configs)
    ok = count >= 1
    return VerificationCheck(
        name="configuration_present",
        ok=ok,
        detail=f"configuration_count={count}",
    )


def _sketches_constrained(facts: dict[str, Any]) -> VerificationCheck | str:
    if "sketch_statuses" not in facts:
        return "missing sketch_statuses"
    statuses = facts.get("sketch_statuses") or []
    under = [
        s.get("sketch") or "(open)"
        for s in statuses
        if s.get("state") == "under_defined"
    ]
    ok = not under
    return VerificationCheck(
        name="sketches_constrained",
        ok=ok,
        detail="no under-defined sketches" if ok else f"under_defined: {under}",
    )


def _no_unsaved_edits(facts: dict[str, Any]) -> VerificationCheck | str:
    doc = facts.get("active_document")
    if doc is None:
        return "missing active_document"
    modified = bool(doc.get("modified"))
    ok = not modified
    return VerificationCheck(
        name="no_unsaved_edits",
        ok=ok,
        detail=f"modified={modified}",
    )


def _no_interference(facts: dict[str, Any]) -> VerificationCheck | str:
    doc = facts.get("active_document")
    if doc is None:
        return "missing active_document"
    if doc.get("doc_type") != "assembly":
        return "not an assembly"
    inter = facts.get("interference")
    if inter is None:
        return "missing interference"
    count = int(inter.get("count") or 0)
    ok = count == 0
    return VerificationCheck(
        name="no_interference",
        ok=ok,
        detail=f"interference_count={count}",
    )


def _document_saved(facts: dict[str, Any]) -> VerificationCheck | str:
    doc = facts.get("active_document")
    if doc is None:
        return "missing active_document"
    saved = bool(doc.get("saved"))
    ok = saved
    return VerificationCheck(
        name="document_saved",
        ok=ok,
        detail=f"saved={saved}",
    )


RULES: tuple[Rule, ...] = (
    Rule(
        name="active_document",
        description="Active document exists",
        requires=frozenset({"active_document"}),
        check=_active_document,
    ),
    Rule(
        name="units_declared",
        description="Document units are mm or inch",
        requires=frozenset({"active_document"}),
        check=_units_declared,
    ),
    Rule(
        name="feature_tree_present",
        description="Part/assembly has at least one feature",
        requires=frozenset({"active_document", "features"}),
        check=_feature_tree_present,
    ),
    Rule(
        name="positive_dimensions",
        description="All dimension values are positive",
        requires=frozenset({"part_parameters"}),
        check=_positive_dimensions,
    ),
    Rule(
        name="equations_nonempty",
        description="Every equation has a non-empty RHS",
        requires=frozenset({"part_parameters"}),
        check=_equations_nonempty,
    ),
    Rule(
        name="configuration_present",
        description="At least one configuration exists",
        requires=frozenset({"part_parameters"}),
        check=_configuration_present,
    ),
    Rule(
        name="sketches_constrained",
        description="No under-defined sketches",
        requires=frozenset({"sketch_statuses"}),
        check=_sketches_constrained,
    ),
    Rule(
        name="no_unsaved_edits",
        description="Document has no unsaved edits",
        requires=frozenset({"active_document"}),
        check=_no_unsaved_edits,
    ),
    Rule(
        name="no_interference",
        description="Assembly has zero interference pairs",
        requires=frozenset({"active_document", "interference"}),
        check=_no_interference,
    ),
    Rule(
        name="document_saved",
        description="Document has a filesystem identity (saved)",
        requires=frozenset({"active_document"}),
        check=_document_saved,
    ),
)

RULE_BY_NAME: dict[str, Rule] = {r.name: r for r in RULES}


def evaluate_rules(
    facts: dict[str, Any],
    names: Sequence[str] | None = None,
) -> tuple[list[VerificationCheck], list[dict[str, str]]]:
    """Run selected rules against a fact snapshot.

    Returns ``(checks, skipped)``. Unknown ``names`` → ``INVALID_ARGUMENT``.
    """
    if names is None:
        selected = list(RULES)
    else:
        unknown = [n for n in names if n not in RULE_BY_NAME]
        if unknown:
            known = ", ".join(r.name for r in RULES)
            raise fail(
                "INVALID_ARGUMENT",
                f"Unknown rule name(s): {unknown}",
                f"Known rules: {known}",
            )
        # Preserve caller order; dedupe while keeping first occurrence.
        selected = []
        seen: set[str] = set()
        for n in names:
            if n in seen:
                continue
            seen.add(n)
            selected.append(RULE_BY_NAME[n])

    checks: list[VerificationCheck] = []
    skipped: list[dict[str, str]] = []
    for rule in selected:
        result = rule.check(facts)
        if isinstance(result, str):
            skipped.append({"name": rule.name, "reason": result})
        else:
            checks.append(result)
    return checks, skipped


__all__ = [
    "RULES",
    "RULE_BY_NAME",
    "Rule",
    "evaluate_rules",
]
