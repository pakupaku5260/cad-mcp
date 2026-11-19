"""Fail-closed dialog classification for session_respond (0.4.0 R1).

Pure text policy — no COM / Win32. Callers pass title+text+buttons from probe scan.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Action = Literal["yes", "no", "cancel"]

_YES_LABELS = ("yes", "是", "确定", "ok", "继续", "continue", "y")
_NO_LABELS = ("no", "否", "n")
_CANCEL_LABELS = ("cancel", "取消", "abort", "中止")


@dataclass(frozen=True, slots=True)
class DialogPolicy:
    """Classification result for one dialog blob."""

    kind: str  # restart | save_all | low_memory | progress | unknown
    allowed: frozenset[str]
    suggested: Action | None
    reason: str

    @property
    def classified(self) -> bool:
        return self.kind != "unknown"

    @property
    def blocks_sta(self) -> bool:
        """Progress wait UI must not abort COM (_modal_block skips these)."""
        return self.kind != "progress"


def _blob(title: str, text: str, buttons: list[str] | None) -> str:
    parts = [title or "", text or ""]
    if buttons:
        parts.extend(buttons)
    return "\n".join(parts)


def classify_dialog(
    *,
    title: str = "",
    text: str = "",
    buttons: list[str] | None = None,
) -> DialogPolicy:
    """Classify dialog text; unknown → no allowed actions (fail-closed)."""
    blob = _blob(title, text, buttons)
    lower = blob.lower()

    # Restart prompt — only dismiss with no
    if (
        "重新启动 solidworks" in lower
        or "重新启动solidworks" in lower
        or "restart solidworks" in lower
        or ("重新启动" in blob and "solidworks" in lower)
        or ("restart" in lower and "solidworks" in lower)
    ):
        return DialogPolicy(
            kind="restart",
            allowed=frozenset({"no"}),
            suggested="no",
            reason="Restart prompt: only action=no is allowed",
        )

    # Save All — only cancel (never yes/no which may save user docs)
    if (
        "全部保存" in blob
        or "保存所有" in blob
        or "save all" in lower
        or "saveall" in lower.replace(" ", "")
    ):
        return DialogPolicy(
            kind="save_all",
            allowed=frozenset({"cancel"}),
            suggested="cancel",
            reason="Save All prompt: only action=cancel is allowed",
        )

    # Low-memory continue prompt — yes is allowed when explicit
    if (
        "系统内存极低" in blob
        or "内存极低" in blob
        or ("low" in lower and "memory" in lower and ("continue" in lower or "继续" in blob))
        or ("是否要继续" in blob and ("内存" in blob or "memory" in lower))
    ):
        return DialogPolicy(
            kind="low_memory",
            allowed=frozenset({"yes"}),
            suggested="yes",
            reason="Low-memory continue prompt: only action=yes is allowed",
        )

    # Import / open progress wait UI — not actionable; STA must wait, not EXEC_BLOCKED
    if (
        "open progress" in lower
        or "打开进度" in blob
        or "导入进度" in blob
        or ("progress" in lower and ("open" in lower or "import" in lower or "打开" in blob))
    ):
        return DialogPolicy(
            kind="progress",
            allowed=frozenset(),
            suggested=None,
            reason="Progress wait UI: not actionable; do not treat as a blocking fail",
        )

    return DialogPolicy(
        kind="unknown",
        allowed=frozenset(),
        suggested=None,
        reason="Dialog text not on the whitelist; refusing all automatic actions",
    )


def dialog_context(
    *,
    title: str,
    text: str | None = None,
    buttons: list[str] | None = None,
    modal: bool | None = None,
) -> dict:
    """Structured dialog payload for error.context.dialog / session_dialogs."""
    return {
        "title": title,
        "text": text,
        "buttons": list(buttons or []),
        "modal": modal,
    }


def hint_for_policy(policy: DialogPolicy) -> str:
    """Next-step hint pointing at session_respond(action=...)."""
    if policy.kind == "restart":
        return (
            'Call session_respond(action="no") to dismiss the restart prompt; '
            "never pass yes or cancel"
        )
    if policy.kind == "save_all":
        return (
            'Call session_respond(action="cancel") to dismiss Save All; '
            "never pass yes or no (would save user documents)"
        )
    if policy.kind == "low_memory":
        return (
            'Call session_respond(action="yes") to continue after low-memory warning; '
            "action must be explicit"
        )
    return (
        "Call session_dialogs to inspect the dialog; session_respond refuses "
        "unclassified dialogs — dismiss manually in SolidWorks if unsure"
    )


def button_labels_for_action(action: Action) -> tuple[str, ...]:
    """Candidate button captions (case-insensitive match)."""
    if action == "yes":
        return _YES_LABELS
    if action == "no":
        return _NO_LABELS
    return _CANCEL_LABELS


def match_button_text(button: str, action: Action) -> bool:
    raw = (button or "").strip().lower()
    if not raw:
        return False
    # Strip accelerator ampersands (Yes(&Y) / 是(&Y))
    cleaned = raw.replace("&", "")
    for label in button_labels_for_action(action):
        if cleaned == label or cleaned.startswith(label) or label in cleaned:
            return True
    return False


__all__ = [
    "Action",
    "DialogPolicy",
    "button_labels_for_action",
    "classify_dialog",
    "dialog_context",
    "hint_for_policy",
    "match_button_text",
]
