"""The Steward through the real Strands event loop, on a scripted model.

These tests exercise genuine Strands machinery — tool dispatch, hooks,
multi-turn tool loops — with deterministic model behavior, proving the
agent-side plumbing (Decision Gate feedback, audit trail, world effects)
works exactly as designed.
"""

from conftest import ScriptedModel

from epilogue.agents import build_steward
from epilogue.domain import TaskItem, TaskStatus
from epilogue.engine import Vigil


def test_steward_hits_gate_then_asks_survivor_then_proceeds(runtime, ledger):
    task = TaskItem(
        case_id=runtime.case.id,
        title="PixelVault photo library",
        category="digital_legacy",
        institution_id="pixelvault",
        risk="irreversible",
    )
    ledger.save_task(task)

    model = ScriptedModel(
        turns=[
            ("tool", "get_matter", {"task_id": task.id}),
            (
                "tool",
                "submit_to_institution",
                {
                    "task_id": task.id,
                    "institution_id": "pixelvault",
                    "subject": "Account holder deceased — please export archive",
                    "body": "Please export the archive and downgrade the plan.",
                },
            ),
            (
                "tool",
                "ask_survivor",
                {
                    "task_id": task.id,
                    "question": "Before anything changes: export all 22,384 photos first?",
                    "context": "Your dad's photo plan renews soon. Nothing will be deleted either way.",
                    "options": [
                        {
                            "id": "export",
                            "label": "Export everything, then stop the billing",
                            "consequence": "Photos safe forever, no renewal charge",
                            "authorizes": True,
                        },
                        {
                            "id": "keep",
                            "label": "Keep the plan as it is",
                            "consequence": "$119.88/year continues",
                        },
                    ],
                    "recommendation": "export",
                    "urgency": "this_week",
                },
            ),
            ("text", "I've asked Sarah and will stand down until she answers."),
        ]
    )
    steward = build_steward(model, runtime)
    steward("Work this matter now: " + task.id)

    # The gate blocked the outward action: no mail left the building.
    assert ledger.mail_for_case(runtime.case.id) == []
    decisions = ledger.decisions_for_case(runtime.case.id, status="open")
    assert len(decisions) == 1
    assert ledger.get_task(task.id).status == TaskStatus.NEEDS_DECISION
    # The audit hook recorded every tool call.
    tool_events = [e for e in ledger.audit_for_case(runtime.case.id) if e.kind == "tool_call"]
    assert any("submit_to_institution" in e.summary for e in tool_events)

    # Sarah answers; the gate opens; the same action now succeeds.
    vigil = Vigil(ledger, model, enable_weekly_notes=False)
    vigil.resolve_decision(decisions[0].id, "export")
    model.turns.extend(
        [
            (
                "tool",
                "submit_to_institution",
                {
                    "task_id": task.id,
                    "institution_id": "pixelvault",
                    "subject": "Please export the full archive",
                    "body": "The family asks for a full archive export, then downgrade the plan.",
                },
            ),
            ("text", "Export requested; awaiting the archive."),
        ]
    )
    steward2 = build_steward(model, runtime)
    steward2("Sarah chose to export. Proceed on matter " + task.id)

    mail = ledger.mail_for_case(runtime.case.id)
    assert len(mail) == 1 and mail[0].direction == "outbound"
    assert ledger.get_task(task.id).status == TaskStatus.WAITING_RESPONSE

    # And the world answers in kind, days later.
    ledger.advance_days(3)
    delivered = vigil.world.deliver_due(runtime.case.id)
    assert delivered and "22,384" in delivered[0].body


def test_specialist_agents_are_mounted_as_tools(runtime):
    model = ScriptedModel(turns=[("text", "ok")])
    steward = build_steward(model, runtime)
    names = set(steward.tool_names)
    assert {"consult_scribe", "consult_advocate", "consult_sentinel"} <= names
    assert {"submit_to_institution", "ask_survivor", "get_playbook"} <= names
