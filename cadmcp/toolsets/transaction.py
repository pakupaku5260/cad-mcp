"""Transaction toolset: tx_begin / tx_status / tx_commit / tx_rollback (F4)."""
from __future__ import annotations

from cadmcp.errors import fail
from cadmcp.kernel import OpContext
from cadmcp.registry import ToolSpec, make_schema
from cadmcp.transaction import TxManager


def _manager(ctx: OpContext) -> TxManager:
    mgr = getattr(ctx, "tx", None)
    if mgr is None:
        raise fail(
            "INTERNAL_ERROR",
            "Transaction manager not wired on OpContext",
            "Server defect; Kernel must attach TxManager before dispatching tx_* tools",
        )
    return mgr


def tx_begin(ctx: OpContext, name: str, mode: str = "checkpoint") -> dict:
    return _manager(ctx).begin(
        ctx.backend, name=name, mode=mode, state_version=ctx.state_version
    )


def tx_status(ctx: OpContext, tx_id: str) -> dict:
    return _manager(ctx).status(tx_id)


def tx_commit(ctx: OpContext, tx_id: str) -> dict:
    return _manager(ctx).commit(tx_id)


def tx_rollback(ctx: OpContext, tx_id: str, mode: str = "compensate") -> dict:
    return _manager(ctx).rollback(ctx.backend, tx_id, mode=mode)


TRANSACTION_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="tx_begin",
        toolset="transaction",
        description=(
            "Start a compensating transaction (L1 checkpoint + journal). "
            "mode=checkpoint tries SaveAsCopy under .cadmcp/tx/; oversized (>200MB) "
            "degrades to journal-only with a warning (not blocked). "
            "One active transaction per session; single-document only. "
            + "Does not implement SolidWorks undo."
        ),
        input_schema=make_schema(
            {
                "name": {
                    "type": "string",
                    "description": "Human-readable transaction label for journals.",
                },
                "mode": {
                    "type": "string",
                    "enum": ["checkpoint", "journal-only"],
                    "description": "checkpoint (default) or journal-only (skip SaveAsCopy).",
                },
            },
            ["name"],
        ),
        handler=tx_begin,
        mutating=True,
        timeout_class="normal",
    ),
    ToolSpec(
        name="tx_status",
        toolset="transaction",
        description=(
            "Read journal steps, dirty flag, and unsupported-step warnings for an active tx_id."
        ),
        input_schema=make_schema(
            {
                "tx_id": {
                    "type": "string",
                    "description": "Transaction id from tx_begin.",
                },
            },
            ["tx_id"],
        ),
        handler=tx_status,
        mutating=False,
        timeout_class="fast",
    ),
    ToolSpec(
        name="tx_commit",
        toolset="transaction",
        description=(
            "Commit the active transaction: delete checkpoint copy, keep journal under .cadmcp/."
        ),
        input_schema=make_schema(
            {
                "tx_id": {
                    "type": "string",
                    "description": "Transaction id from tx_begin.",
                },
            },
            ["tx_id"],
        ),
        handler=tx_commit,
        mutating=True,
        timeout_class="normal",
    ),
    ToolSpec(
        name="tx_rollback",
        toolset="transaction",
        description=(
            "Roll back an active transaction. mode=compensate (LIFO compensators), "
            "reload (close+reopen checkpoint), or discard (close unsaved tx-created doc). "
            "Unsafe preconditions → ROLLBACK_UNSAFE (model unchanged). "
            "Execution failure → ROLLBACK_FAILED with side_effect=unknown."
        ),
        input_schema=make_schema(
            {
                "tx_id": {
                    "type": "string",
                    "description": "Transaction id from tx_begin.",
                },
                "mode": {
                    "type": "string",
                    "enum": ["reload", "compensate", "discard"],
                    "description": "Rollback strategy (default compensate).",
                },
            },
            ["tx_id"],
        ),
        handler=tx_rollback,
        mutating=True,
        verify_delta=True,
        timeout_class="slow",
    ),
]

__all__ = [
    "TRANSACTION_SPECS",
    "tx_begin",
    "tx_commit",
    "tx_rollback",
    "tx_status",
]
