"""Audit trail via Strands hooks.

Families in this situation are being asked to trust an autonomous system with
their parent's affairs. Trust needs receipts. This hook subscribes to the
Strands agent lifecycle and writes every tool invocation to the ledger's
audit table, which feeds both the dashboard's live activity stream and the
permanent "everything Epilogue did" record.
"""

from __future__ import annotations

import json

from strands.hooks import HookRegistry
from strands.hooks.events import AfterToolCallEvent, BeforeToolCallEvent

from .ledger import Ledger

# Tool calls that only read state — logged at lower salience in the feed.
_READ_ONLY = {
    "get_case_file",
    "get_playbook",
    "list_matters",
    "get_matter",
    "check_document_vault",
    "current_date",
    "search_benefit_records",
}


def _preview(value: object, limit: int = 140) -> str:
    try:
        text = json.dumps(value, default=str)
    except Exception:  # noqa: BLE001
        text = str(value)
    return text[:limit] + ("…" if len(text) > limit else "")


class AuditHook:
    """Records every tool call an agent makes, with its input, to the ledger."""

    def __init__(self, ledger: Ledger, case_id: str) -> None:
        self.ledger = ledger
        self.case_id = case_id

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(BeforeToolCallEvent, self._before_tool)
        registry.add_callback(AfterToolCallEvent, self._after_tool)

    def _actor(self, event) -> str:
        return getattr(event.agent, "name", None) or "Agent"

    def _before_tool(self, event: BeforeToolCallEvent) -> None:
        name = event.tool_use.get("name", "?")
        args = event.tool_use.get("input", {})
        self.ledger.record(
            self.case_id,
            actor=self._actor(event),
            kind="tool_call",
            summary=f"{self._actor(event)} → {name}",
            detail=_preview(args, 400),
            task_id=args.get("task_id") if isinstance(args, dict) else None,
        )

    def _after_tool(self, event: AfterToolCallEvent) -> None:
        if event.exception is None:
            return  # successful results are visible through their own ledger records
        name = event.tool_use.get("name", "?")
        self.ledger.record(
            self.case_id,
            actor=self._actor(event),
            kind="tool_call",
            summary=f"{name} failed: {event.exception}",
            detail=_preview(getattr(event, "result", ""), 300),
        )
