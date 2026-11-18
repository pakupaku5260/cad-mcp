"""Design toolset: DesignSpec validate (F10) + controlled run (F11/F12) + strategies (F21)."""
from __future__ import annotations

from cadmcp import task_ledger as ledger
from cadmcp.design_run import run_design
from cadmcp.design_spec import load_design_spec
from cadmcp.kernel import OpContext
from cadmcp.part_strategies import list_part_strategies as catalog_list_part_strategies
from cadmcp.registry import ToolSpec, make_schema
from cadmcp.safety import ensure_input_path

_SPEC_EXTS = {".json"}

# Keep ≤300 tokens (F21 B1): name + description + schema.
_LIST_STRATEGIES_DESCRIPTION = (
    "List part-type strategy catalog entries (plate/box/fillet_pattern/surface_thicken) "
    "backed by examples/*.json recipes. Read-only metadata: id, part_type, description, "
    "source_recipe, required_toolsets, feature_tools, key_params. "
    "Does not run recipes, design_run, or replay_recipe. "
    "part_type=null lists all; unknown type returns empty strategies. "
    "Returns {ok, strategies, count}. "
    "Read cadmcp://help/part_strategies before choosing a strategy."
)

_VALIDATE_DESCRIPTION = (
    "Validate a DesignSpec JSON file (schema_version 1) inside the workspace. "
    "Read-only: no modeling, no COM, no side effects. "
    "Required fields: schema_version=1, kind (part|assembly|drawing), "
    "doc.title (non-empty), doc.units (mm|inch), features (non-empty array of "
    "{name, tool, args}). Optional: params (number|bool|string), "
    "variants ({row:{param:scalar}} design table), "
    "features[].assert (keys ⊆ ok|error_code|result_keys|delta_changed), "
    "features[].depends_on (existing names, no cycles), "
    "checkpoints (subset of feature names in features order), "
    "verify.groups (geometry|features|mass_bbox|assembly|drawing), "
    "verify.thresholds (object), outputs[{kind: step|stl|pdf|dxf, path}]. "
    "Args may use {\"$param\": \"name\"} placeholders (substituted by design_run). "
    "On success returns {ok, spec:{schema_version,kind,doc,feature_count,"
    "features,checkpoints,verify_groups,output_kinds}}. "
    "Failures: PATH_NOT_FOUND / PATH_OUTSIDE_SANDBOX / INVALID_ARGUMENT "
    "(message names the JSON path, e.g. design_spec.features[2].tool). "
    "Full schema: cadmcp://help/design_spec (help topic)."
)

# Token budget: part profile headroom after F13 budget bump; keep description tight.
_RUN_DESCRIPTION = (
    "Execute a DesignSpec: topo-sort features (depends_on, stable within layer), "
    "substitute {\"$param\": name} from params, dispatch each feature, evaluate "
    "assert (recipe keys), then verify_model when verify.groups is set and the run "
    "was not aborted. Not atomic — each step has its own OpResult; wrap with tx_* "
    "for rollback. "
    "On success of a declared checkpoint feature, writes an L1 copy + fingerprint "
    "sidecar under .cadmcp/checkpoints/ (capture does not bump state_version). "
    "Snapshot failure is recorded (ok=false+detail) and does not fail the run. "
    "resume_from=<checkpoint> (optional): after read-only precheck, discards the "
    "active doc (unsaved edits lost), opens the snapshot copy (title=filename stem; "
    "SaveAs to keep), skips features up to that checkpoint (listed in skipped), "
    "and continues. "
    "After steps+verify, declared outputs are exported via the export tool "
    "(overwrite=false; delete old files or change path). Export failures go into "
    "outputs.written and set payload ok=false without aborting the run; aborted "
    "runs skip export (written=[]). Verification failure does not block export. "
    "stop_on_error=true (default) stops after the first failed step/assert; false "
    "continues and keeps the first failure in failed_step. "
    "Optional variant=<name> selects spec.variants[name] over params (unknown → "
    "INVALID_ARGUMENT; payload shape unchanged). "
    "Precheck (unknown tool / bad $param / bad resume_from / bad variant) raises "
    "with zero side effects before restore/dispatch. "
    "Outer OpResult.ok stays true when steps fail; inspect payload ok / failed_step "
    "(same as replay_recipe). Payload ok is also false when verification is not "
    "verified or an output fails. "
    "Returns {ok, spec, steps, failed_step, verification, checkpoints, outputs}; "
    "checkpoints has declared/snapshots/resumed_from/skipped. "
    "Schema help: cadmcp://help/design_spec (help topic)."
)


def design_spec_validate(ctx: OpContext, spec_path: str) -> dict:
    """Load + validate DesignSpec; return a compact summary (no execution)."""
    resolved = ensure_input_path(spec_path, roots=ctx.workspace, extensions=_SPEC_EXTS)
    spec = load_design_spec(resolved)
    return {
        "ok": True,
        "spec": {
            "schema_version": spec["schema_version"],
            "kind": spec["kind"],
            "doc": spec["doc"],
            "feature_count": len(spec["features"]),
            "features": [f["name"] for f in spec["features"]],
            "checkpoints": list(spec["checkpoints"]),
            "verify_groups": list(spec["verify"]["groups"]),
            "output_kinds": [o["kind"] for o in spec["outputs"]],
        },
    }


def list_part_strategies(ctx: OpContext, part_type: str | None = None) -> dict:
    """Readonly strategy catalog; does not execute recipes."""
    strategies = catalog_list_part_strategies(part_type)
    return {"ok": True, "strategies": strategies, "count": len(strategies)}


def design_run(
    ctx: OpContext,
    spec_path: str,
    stop_on_error: bool = True,
    resume_from: str | None = None,
    variant: str | None = None,
) -> dict:
    """Controlled DesignSpec execution (mutating; expect_* injected by registry)."""

    def _call() -> dict:
        resolved = ensure_input_path(spec_path, roots=ctx.workspace, extensions=_SPEC_EXTS)
        spec = load_design_spec(resolved)
        return run_design(
            ctx,
            spec,
            stop_on_error=bool(stop_on_error),
            resume_from=resume_from,
            variant=variant,
        )

    return ledger.logged("design_run", _call)


DESIGN_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="design_spec_validate",
        toolset="design",
        description=_VALIDATE_DESCRIPTION,
        input_schema=make_schema(
            {
                "spec_path": {
                    "type": "string",
                    "description": "Path to DesignSpec JSON inside the workspace",
                },
            },
            ["spec_path"],
        ),
        handler=design_spec_validate,
        timeout_class="fast",
        bypass_queue=True,
    ),
    ToolSpec(
        name="list_part_strategies",
        toolset="design",
        description=_LIST_STRATEGIES_DESCRIPTION,
        input_schema=make_schema(
            {
                "part_type": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": "Filter by part_type; null (default) returns all four.",
                },
            },
        ),
        handler=list_part_strategies,
        mutating=False,
        bypass_queue=True,
        timeout_class="fast",
        layer="domain",
    ),
    ToolSpec(
        name="design_run",
        toolset="design",
        description=_RUN_DESCRIPTION,
        input_schema=make_schema(
            {
                "spec_path": {
                    "type": "string",
                    "description": "Path to DesignSpec JSON inside the workspace",
                },
                "stop_on_error": {
                    "type": "boolean",
                    "default": True,
                    "description": (
                        "If true (default), stop after the first failed step/assert. "
                        "If false, continue remaining features and keep the first "
                        "failure in failed_step."
                    ),
                },
                "resume_from": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": (
                        "Optional checkpoint name from spec.checkpoints. "
                        "After precheck, discard active doc and open the snapshot "
                        "copy, then run only features after that checkpoint."
                    ),
                },
                "variant": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": (
                        "Optional design-table row from spec.variants; overrides "
                        "matching params keys for this run."
                    ),
                },
            },
            ["spec_path"],
        ),
        handler=design_run,
        mutating=True,
        timeout_class="slow",
        layer="task",
    ),
]

__all__ = ["DESIGN_SPECS", "design_run", "design_spec_validate", "list_part_strategies"]
