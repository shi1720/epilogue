"""Ledger: persistence, clock, decisions, stats."""

from datetime import date

from epilogue.domain import Decision, DecisionOption, MailMessage, TaskItem, TaskStatus


def test_sim_clock_persists_and_advances(ledger):
    today = ledger.sim_today()
    new_day = ledger.advance_days(3)
    assert (new_day - today).days == 3
    assert ledger.sim_today() == new_day


def test_task_roundtrip_and_due_selection(ledger, case):
    t = TaskItem(case_id=case.id, title="Notify bank", category="financial")
    ledger.save_task(t)
    loaded = ledger.get_task(t.id)
    assert loaded.title == "Notify bank"
    assert loaded.status == TaskStatus.PENDING
    # Pending tasks are always due; waiting tasks only when their date arrives.
    assert t.id in [x.id for x in ledger.due_tasks(case.id)]
    from datetime import datetime, timedelta, timezone

    loaded.status = TaskStatus.WAITING_RESPONSE
    loaded.next_action_at = datetime.combine(
        ledger.sim_today() + timedelta(days=5), datetime.min.time(), tzinfo=timezone.utc
    )
    ledger.save_task(loaded)
    assert loaded.id not in [x.id for x in ledger.due_tasks(case.id)]
    ledger.advance_days(5)
    assert loaded.id in [x.id for x in ledger.due_tasks(case.id)]


def test_decision_lifecycle(ledger, case):
    t = TaskItem(case_id=case.id, title="Photos", category="digital_legacy", risk="irreversible")
    ledger.save_task(t)
    d = Decision(
        case_id=case.id,
        task_id=t.id,
        question="Export the photos first?",
        context="22,384 photos are stored in the cloud.",
        options=[
            DecisionOption(id="export", label="Export then downgrade", consequence="Photos safe"),
            DecisionOption(id="keep", label="Keep paying", consequence="$119.88/yr"),
        ],
        recommendation="export",
    )
    ledger.save_decision(d)
    assert ledger.open_decision_for_task(t.id).id == d.id
    assert ledger.resolved_decision_for_task(t.id) is None
    d.status = "resolved"
    d.resolution_option_id = "export"
    ledger.save_decision(d)
    assert ledger.open_decision_for_task(t.id) is None
    assert ledger.resolved_decision_for_task(t.id).resolution_option_id == "export"


def test_stats_count_hours(ledger, case):
    done = TaskItem(
        case_id=case.id,
        title="A",
        category="financial",
        status=TaskStatus.DONE,
        estimated_minutes_saved=90,
    )
    ledger.save_task(done)
    ledger.save_task(TaskItem(case_id=case.id, title="B", category="financial"))
    stats = ledger.stats(case.id)
    assert stats["total_matters"] == 2
    assert stats["settled"] == 1
    assert stats["hours_given_back"] == 1.5


def test_audit_events_reach_listeners(ledger, case):
    seen = []
    ledger.on_event(seen.append)
    ledger.record(case.id, "Steward", "status", "hello world")
    assert seen and seen[0].summary == "hello world"
    assert ledger.audit_for_case(case.id)[0].sim_date == ledger.sim_today()


def test_mail_unread_flow(ledger, case):
    m = MailMessage(
        case_id=case.id,
        direction="inbound",
        institution_id="x",
        institution_name="X",
        subject="s",
        body="b",
        sim_date=date(2026, 9, 1),
    )
    ledger.save_mail(m)
    assert len(ledger.unread_mail(case.id)) == 1
    m.status = "processed"
    ledger.save_mail(m)
    assert ledger.unread_mail(case.id) == []
