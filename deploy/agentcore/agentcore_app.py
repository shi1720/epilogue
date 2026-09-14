"""Amazon Bedrock AgentCore entrypoint for Epilogue.

AgentCore Runtime hosts the agent serverlessly: each invocation receives a
JSON payload and returns a JSON result, with identity, memory, and
observability handled by the platform. Epilogue's Vigil maps onto this
naturally — the ledger lives on a mounted volume or is swapped for a
managed store, and Amazon EventBridge Scheduler fires the daily heartbeat
instead of the local clock.

Deploy (from the repository root):

    pip install bedrock-agentcore-starter-toolkit
    agentcore configure --entrypoint deploy/agentcore/agentcore_app.py
    agentcore launch

Then invoke:

    agentcore invoke '{"action": "tick"}'
    agentcore invoke '{"action": "open_case", "narrative": "...", "documents": "..."}'
"""

from __future__ import annotations

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from epilogue.config import db_path, make_model
from epilogue.engine import Vigil
from epilogue.ledger import Ledger

app = BedrockAgentCoreApp()

_ledger = Ledger(db_path())
_vigil: Vigil | None = None


def _get_vigil() -> Vigil:
    global _vigil
    if _vigil is None:
        _vigil = Vigil(_ledger, make_model())
    return _vigil


@app.entrypoint
def invoke(payload: dict, context=None) -> dict:
    """Route AgentCore invocations into the Vigil.

    Actions:
        open_case: {"action": "open_case", "narrative": str, "documents": str}
        tick:      {"action": "tick"}              — one heartbeat (wire to EventBridge Scheduler)
        advance:   {"action": "advance", "days": n} — demo clock control
        decide:    {"action": "decide", "decision_id": str, "option_id": str, "note": str}
        state:     {"action": "state"}             — case stats snapshot
    """
    vigil = _get_vigil()
    action = payload.get("action", "tick")

    if action == "open_case":
        case = vigil.open_case(payload["narrative"], payload.get("documents", ""))
        return {"case_id": case.id, "matters": len(_ledger.tasks_for_case(case.id))}

    case = _ledger.first_case()
    if case is None:
        return {"error": "no case open — send an open_case action first"}

    if action == "tick":
        report = vigil.tick(case.id)
        return {"report": report.summary(), "stats": _ledger.stats(case.id)}
    if action == "advance":
        report = vigil.advance(case.id, int(payload.get("days", 1)))
        return {"report": report.summary(), "stats": _ledger.stats(case.id)}
    if action == "decide":
        vigil.resolve_decision(payload["decision_id"], payload["option_id"], payload.get("note", ""))
        report = vigil.tick(case.id)
        return {"report": report.summary(), "stats": _ledger.stats(case.id)}
    if action == "state":
        return {
            "stats": _ledger.stats(case.id),
            "open_decisions": [
                {"id": d.id, "question": d.question}
                for d in _ledger.decisions_for_case(case.id, status="open")
            ],
        }
    return {"error": f"unknown action {action!r}"}


if __name__ == "__main__":
    app.run()
