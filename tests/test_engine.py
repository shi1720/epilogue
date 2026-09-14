"""The Vigil end to end: intake → plan → work → wait → reply → settle."""

from collections import deque
from datetime import date

from conftest import ScriptedModel

from epilogue.domain import (
    AccountInventory,
    DiscoveredAccount,
    IntakeProfile,
    PlannedTask,
    TaskPlan,
    TaskStatus,
    TriageResult,
)
from epilogue.engine import Vigil
from epilogue.ledger import Ledger


def _intake_structured():
    return {
        "IntakeProfile": IntakeProfile(
            deceased_full_name="James Mitchell",
            deceased_date_of_death=date(2026, 8, 30),
            deceased_state="OH",
            survivor_full_name="Sarah Mitchell",
            survivor_relationship="daughter",
            survivor_is_executor=True,
            immediate_worries=["identity theft", "the photos"],
        ),
        "AccountInventory": AccountInventory(
            accounts=[
                DiscoveredAccount(
                    institution_name="First Harbor Bank",
                    institution_kind="bank",
                    account_hint="checking ...4417",
                    evidence="Statement header",
                )
            ]
        ),
        "TaskPlan": TaskPlan(
            tasks=[
                PlannedTask(
                    title="Notify First Harbor Bank and secure accounts",
                    category="financial",
                    institution_id="first_harbor_bank",
                    playbook_id="bank_notification",
                    why="Stops new charges and gives the executor a clean starting balance.",
                    risk="careful",
                    estimated_minutes_saved=150,
                )
            ]
        ),
    }


def test_full_lifecycle_of_a_bank_matter(tmp_path):
    ledger = Ledger(tmp_path / "e2e.db")
    structured = _intake_structured()
    structured["TriageResult"] = deque(
        [
            TriageResult(
                disposition="needs_document",
                summary="The bank needs a certified death certificate and a letter of instruction.",
                requested_items=["certified death certificate", "letter of instruction"],
                suggested_next_step="Send the certified documents",
            ),
            TriageResult(
                disposition="resolved",
                summary="Accounts restricted; date-of-death balance letter received.",
            ),
        ]
    )
    model = ScriptedModel(structured=structured)
    vigil = Vigil(ledger, model, enable_weekly_notes=False)

    case = vigil.open_case("My dad James died Aug 30.", "First Harbor Bank statement …4417")
    tasks = ledger.tasks_for_case(case.id)
    assert len(tasks) == 5  # bank plus three bureau alerts and benefits scan
    task = next(t for t in tasks if t.institution_id == "first_harbor_bank")
    for extra in tasks:
        if extra.id != task.id:
            extra.status = TaskStatus.DISMISSED
            ledger.save_task(extra)

    # Day 0: the Steward makes first contact (no certificate — the bank will push back).
    model.turns.extend(
        [
            (
                "tool",
                "submit_to_institution",
                {
                    "task_id": task.id,
                    "institution_id": "first_harbor_bank",
                    "subject": "Notice of death — James Mitchell",
                    "body": "Please restrict the accounts of the late James Mitchell.",
                },
            ),
            ("text", "Notified the bank."),
        ]
    )
    report = vigil.tick(case.id)
    assert report.steward_runs == 1
    assert ledger.get_task(task.id).status == TaskStatus.WAITING_RESPONSE

    # Day 3: the bank's reply arrives; triage says needs_document; the Steward sends the cert.
    model.turns.extend(
        [
            (
                "tool",
                "submit_to_institution",
                {
                    "task_id": task.id,
                    "institution_id": "first_harbor_bank",
                    "subject": "Certified documents enclosed",
                    "body": "Enclosed: certified death certificate and letter of instruction.",
                    "attachments": ["certified_death_certificate"],
                },
            ),
            ("text", "Documents sent."),
        ]
    )
    ledger.advance_days(3)
    report = vigil.tick(case.id)
    assert report.mail_delivered == 1 and report.mail_triaged == 1

    # Day 7: the bank confirms; triage says resolved; the matter settles mechanically.
    ledger.advance_days(4)
    report = vigil.tick(case.id)
    assert report.mail_delivered == 1
    final = ledger.get_task(task.id)
    assert final.status == TaskStatus.DONE
    assert ledger.stats(case.id)["settled"] == 1
    # A certified copy was consumed from the vault.
    from epilogue.runtime import Runtime
    from epilogue.simworld import SimWorld

    rt = Runtime(ledger=ledger, world=SimWorld(ledger), case=case)
    assert rt.vault_status()["certified_death_certificate"] == 4


def test_quiet_day_is_quiet(tmp_path):
    ledger = Ledger(tmp_path / "quiet.db")
    model = ScriptedModel(structured=_intake_structured())
    vigil = Vigil(ledger, model, enable_weekly_notes=False)
    case = vigil.open_case("intake", "docs")
    # Isolate the bank matter; required planning coverage is tested separately.
    tasks = ledger.tasks_for_case(case.id)
    task = next(t for t in tasks if t.institution_id == "first_harbor_bank")
    for extra in tasks:
        if extra.id != task.id:
            extra.status = TaskStatus.DISMISSED
            ledger.save_task(extra)
    model.turns.extend(
        [
            (
                "tool",
                "update_matter",
                {
                    "task_id": task.id,
                    "status": "waiting_response",
                    "follow_up_days": 10,
                    "note": "Contacted by phone; awaiting written confirmation.",
                },
            ),
            ("text", "Waiting."),
        ]
    )
    vigil.tick(case.id)
    ledger.advance_days(1)
    report = vigil.tick(case.id)
    assert report.quiet
