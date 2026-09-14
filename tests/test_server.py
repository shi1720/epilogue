"""The whole product through the web app: intake → work → replies → settled.

These tests exercise the actual FastAPI application — background threads,
polling, the SSE-fed state endpoints — with the deterministic ScriptedModel
underneath, proving the integrated system (not just its parts) handles a
case end to end.
"""

from __future__ import annotations

import importlib
import json
import time
from datetime import date

import pytest
from conftest import ScriptedModel
from fastapi.testclient import TestClient

from epilogue.domain import (
    AccountInventory,
    DiscoveredAccount,
    IntakeProfile,
    PlannedTask,
    TaskPlan,
    TriageResult,
)
from epilogue.engine import Vigil


def _triage_by_content(messages) -> TriageResult:
    text = json.dumps(messages)
    if "restricted" in text or "balance letter" in text.lower():
        return TriageResult(disposition="resolved", summary="Accounts restricted; balance letter received.")
    if "documentation" in text.lower() or "certified" in text.lower():
        return TriageResult(disposition="needs_document", summary="Bank requires a certified death certificate.")
    return TriageResult(disposition="wait", summary="Nothing to do yet.")


def _scripted_model() -> ScriptedModel:
    return ScriptedModel(
        structured={
            "IntakeProfile": IntakeProfile(
                deceased_full_name="James Mitchell",
                deceased_date_of_death=date(2026, 8, 30),
                deceased_state="OH",
                survivor_full_name="Sarah Mitchell",
                survivor_relationship="daughter",
                survivor_is_executor=True,
            ),
            "AccountInventory": AccountInventory(
                accounts=[
                    DiscoveredAccount(
                        institution_name="First Harbor Bank",
                        institution_kind="bank",
                        evidence="Statement header",
                    )
                ]
            ),
            "TaskPlan": TaskPlan(
                tasks=[
                    PlannedTask(
                        title="Notify First Harbor Bank",
                        category="financial",
                        institution_id="first_harbor_bank",
                        playbook_id="bank_notification",
                        why="Secures the accounts.",
                        risk="careful",
                        estimated_minutes_saved=150,
                    )
                ]
            ),
            # Keyed by mail content, not call order: the day-8 cycle delivers both
            # the bank's confirmation and simworld's ambient renewal reminder, and
            # their relative order is an implementation detail.
            "TriageResult": _triage_by_content,
        }
    )


@pytest.fixture()
def webapp(tmp_path, monkeypatch):
    monkeypatch.setenv("EPILOGUE_DATA_DIR", str(tmp_path))
    import epilogue.server as server

    server = importlib.reload(server)
    model = _scripted_model()
    server.STATE.vigil = Vigil(server.STATE.ledger, model, enable_weekly_notes=False)
    with TestClient(server.app) as client:
        yield client, server, model


def _wait_idle(client, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = client.get("/api/state").json()
        if state.get("status") == "idle" and state.get("case"):
            return state
        time.sleep(0.05)
    raise AssertionError("server did not return to idle in time")


def test_full_case_through_the_web_app(webapp):
    client, server, model = webapp

    # A visitor with no case sees the intake surface.
    assert client.get("/").status_code == 200
    assert client.get("/api/state").json()["case"] is None
    seed = client.get("/api/seed").json()
    assert "James Mitchell" in seed["narrative"]

    # Intake. (The scripted model's day-0 steward cycle is a no-op text turn; the
    # real work is scripted per-cycle below, once the task id is known.)
    res = client.post("/api/case", json={"narrative": seed["narrative"], "documents": seed["documents"]})
    assert res.status_code == 200
    state = _wait_idle(client)
    tasks = state["tasks"]
    assert len(tasks) == 1
    task_id = tasks[0]["id"]

    # Cycle 2: the Steward makes first contact.
    model.turns.extend(
        [
            (
                "tool",
                "submit_to_institution",
                {
                    "task_id": task_id,
                    "institution_id": "first_harbor_bank",
                    "subject": "Notice of death — James Mitchell",
                    "body": "Please restrict the accounts of the late James Mitchell.",
                },
            ),
            ("text", "Notified the bank."),
        ]
    )
    assert client.post("/api/clock/advance", json={"days": 1}).status_code == 200
    state = _wait_idle(client)
    assert state["tasks"][0]["status"] == "waiting_response"
    assert any(e["kind"] == "letter_sent" for e in state["timeline"])

    # Days pass; the bank wants documents; the Steward sends a certified copy.
    model.turns.extend(
        [
            (
                "tool",
                "submit_to_institution",
                {
                    "task_id": task_id,
                    "institution_id": "first_harbor_bank",
                    "subject": "Certified documents enclosed",
                    "body": "Enclosed is the certified death certificate.",
                    "attachments": ["certified_death_certificate"],
                },
            ),
            ("text", "Documents sent."),
        ]
    )
    assert client.post("/api/clock/advance", json={"days": 3}).status_code == 200
    state = _wait_idle(client)
    assert state["vault"]["certified_death_certificate"] == 4  # one copy used, visible in the UI

    # The bank confirms; the matter settles without another model call.
    assert client.post("/api/clock/advance", json={"days": 4}).status_code == 200
    state = _wait_idle(client)
    assert state["tasks"][0]["status"] == "done"
    assert state["stats"]["settled"] == 1
    assert client.get("/api/mail").json()["mail"]  # correspondence is on file


def test_preview_case_and_decision_resolution(webapp):
    client, server, model = webapp
    from epilogue.preview import seed_preview

    seed_preview(server.STATE.ledger)
    state = client.get("/api/state").json()
    assert state["stats"]["total_matters"] == 16
    open_decisions = [d for d in state["decisions"] if d["status"] == "open"]
    assert len(open_decisions) == 2

    decision = open_decisions[0]
    res = client.post(
        f"/api/decisions/{decision['id']}/resolve",
        json={"option_id": decision["options"][0]["id"]},
    )
    assert res.status_code == 200
    state = _wait_idle(client)
    resolved = [d for d in state["decisions"] if d["id"] == decision["id"]][0]
    assert resolved["status"] == "resolved"
    assert any(e["kind"] == "decision_resolved" for e in state["timeline"])


def test_reset_is_refused_mid_cycle(webapp):
    client, server, model = webapp
    server.STATE.status = "working"
    assert client.post("/api/reset").status_code == 409
    server.STATE.status = "idle"
    assert client.post("/api/reset").status_code == 200
