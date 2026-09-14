"""A representative mid-case state for previewing the dashboard — no model needed.

This writes ledger records directly; no agent is involved. It exists so anyone
can see and feel the product in one command (`epilogue preview`) before
configuring model credentials. The real thing is `epilogue demo`, which runs
the full agent pipeline live.
"""

from __future__ import annotations

from datetime import date, timedelta

from .domain import (
    Case,
    Decision,
    DecisionOption,
    Person,
    Survivor,
    TaskItem,
    TaskStatus,
)
from .ledger import Ledger


def seed_preview(ledger: Ledger) -> Case:
    """Reset the ledger and populate the James Mitchell preview case."""
    ledger.reset()

    case = Case(
        deceased=Person(full_name="James Mitchell", date_of_birth=date(1948, 3, 14),
                        date_of_death=date(2026, 8, 30), state="OH"),
        survivor=Survivor(full_name="Sarah Mitchell", relationship="daughter", is_executor=True),
        narrative="My dad, James Mitchell, passed away on August 30th…",
    )
    ledger.save_case(case)
    start = date(2026, 9, 8)
    ledger.set_sim_today(start + timedelta(days=11))

    T = [
        ("Notify First Harbor Bank and secure both accounts", "financial", TaskStatus.DONE, 150),
        ("Close Meridian Visa and freeze interest", "financial", TaskStatus.DONE, 60),
        ("Report death to the federal benefits agency", "government", TaskStatus.NEEDS_DECISION, 180),
        ("Keep the lights on at 44 Maple Crest Dr", "utilities", TaskStatus.DONE, 40),
        ("Cancel StreamFlix — preserve Dad's profiles first", "subscriptions", TaskStatus.DONE, 35),
        ("PixelVault: 22,384 photos — protect before renewal", "digital_legacy", TaskStatus.NEEDS_DECISION, 80),
        ("Cancel IronWorks Fitness (written notice required)", "subscriptions", TaskStatus.FOLLOW_UP, 35),
        ("File Beacon Mutual life insurance claim", "insurance", TaskStatus.WAITING_RESPONSE, 120),
        ("Deceased alert — Equifax", "identity", TaskStatus.DONE, 30),
        ("Deceased alert — Experian", "identity", TaskStatus.DONE, 30),
        ("Deceased alert — TransUnion", "identity", TaskStatus.DONE, 30),
        ("Transfer 84,210 Skyway miles to the family", "subscriptions", TaskStatus.WAITING_RESPONSE, 45),
        ("Cancel ClearLine Wireless line", "subscriptions", TaskStatus.DONE, 30),
        ("Cancel The Daily Ledger — recover prepaid balance", "subscriptions", TaskStatus.DONE, 25),
        ("Claim $312 from Ohio unclaimed funds", "benefits", TaskStatus.IN_PROGRESS, 60),
        ("Scan for benefits and money owed to the family", "benefits", TaskStatus.DONE, 200),
    ]
    tasks = []
    for title, cat, status, minutes in T:
        t = TaskItem(case_id=case.id, title=title, category=cat, status=status,
                     estimated_minutes_saved=minutes,
                     why="", risk="routine")
        ledger.save_task(t)
        tasks.append(t)

    pv = tasks[5]
    ledger.save_decision(Decision(
        case_id=case.id, task_id=pv.id, urgency="this_week",
        question="Before anything changes: should I export all 22,384 of your dad's photos first?",
        context=("His PixelVault plan renews on the 12th for $119.88. I can request a full archive "
                 "download, then downgrade the plan so nothing renews — the photos stay safe and "
                 "viewable either way. Nothing will ever be deleted without you."),
        options=[
            DecisionOption(id="export", label="Export everything, then stop the billing",
                           consequence="Photos preserved forever; no renewal charge"),
            DecisionOption(id="keep", label="Keep the plan running for now",
                           consequence="$119.88/year continues; decide later"),
        ],
        recommendation="export",
    ))
    ssa = tasks[2]
    ledger.save_decision(Decision(
        case_id=case.id, task_id=ssa.id, urgency="whenever",
        question="The benefits agency asks for $1,847 back — okay to repay it from the estate account?",
        context=("A retirement payment arrived on Sept 3, after your dad passed. Benefits aren't payable "
                 "for the month of death, so it must be returned — this is normal and there is no "
                 "penalty. I've prepared the repayment; I just won't move that much money without you."),
        authorizes_amount_usd=1847.0,
        options=[
            DecisionOption(id="repay", label="Yes, repay it from the estate account",
                           consequence="Closes the matter; no interest accrues"),
            DecisionOption(id="hold", label="Hold — I want to ask the estate attorney",
                           consequence="I'll pause and re-raise it in a week"),
        ],
        recommendation="repay",
    ))

    E = [
        (0, "Epilogue", "status", "Case opened for the family of James Mitchell"),
        (0, "Archivist", "status", "Read the family's documents: found 14 accounts and obligations"),
        (0, "Planner", "status", "Planned the road ahead: 16 matters to settle"),
        (0, "Scribe", "letter_sent", "Sent to First Harbor Bank: “Notice of death — James R. Mitchell”"),
        (0, "Scribe", "letter_sent", "Sent to Equifax (simulated): “Deceased alert request”"),
        (1, "Scribe", "letter_sent", "Sent to StreamFlix: “Account holder deceased — cancellation”"),
        (3, "Postal service", "mail_received", "Reply arrived from First Harbor Bank: “Additional documentation required”"),
        (3, "Scribe", "letter_sent", "Sent to First Harbor Bank: “Certified documents enclosed” (attached: certified_death_certificate)"),
        (4, "Postal service", "mail_received", "Reply arrived from StreamFlix: “Before we close this account…”"),
        (4, "Steward", "decision_opened", "Asked Sarah: Keep Dad's watch profiles by moving them to your account?"),
        (5, "Survivor", "decision_resolved", "Sarah decided: Transfer the profiles to my account"),
        (6, "Steward", "status", "Settled: Cancel StreamFlix — preserve Dad's profiles first"),
        (7, "Postal service", "mail_received", "Reply arrived from First Harbor Bank: “Accounts restricted — date-of-death balance letter enclosed”"),
        (7, "Steward", "status", "Settled: Notify First Harbor Bank and secure both accounts"),
        (9, "Postal service", "mail_received", "Reply arrived from Experian (simulated): “ALERT: credit application blocked on protected file”"),
        (9, "Sentinel", "status", "Assessed the blocked application: contained — the deceased alert did its job. Someone tried to open a retail card in your dad's name; they were automatically declined."),
        (10, "Postal service", "mail_received", "Reply arrived from Ohio Light & Power: “Account transferred to the estate”"),
        (10, "Steward", "status", "Settled: Keep the lights on at 44 Maple Crest Dr"),
        (11, "Steward", "decision_opened", "Asked Sarah: Before anything changes: export all 22,384 photos first?"),
    ]
    for offset, actor, kind, summary in E:
        ledger.set_sim_today(start + timedelta(days=offset))
        detail = ""
        if kind in ("letter_sent", "mail_received"):
            detail = ("Dear Estate Services,\n\nI write on behalf of the estate of James R. Mitchell "
                      "(date of death: August 30, 2026)…\n\n— Sarah Mitchell, Personal Representative"
                      if kind == "letter_sent" else
                      "Dear Personal Representative,\n\nWe are sorry for your loss…")
        ledger.record(case.id, actor, kind, summary, detail=detail)

    ledger.set_sim_today(start + timedelta(days=11))
    ledger.kv_set(
        f"weekly_note:{case.id}",
        "Sarah,\n\nA quieter week than it looks. The bank finished its paperwork — both of your dad's "
        "accounts are now safely restricted, and I have the balance letter the court will want. His "
        "StreamFlix profiles made it to your account before the subscription closed, watch history and "
        "all. One thing you should know: someone tried to open a credit card in his name on Tuesday. "
        "The alerts we placed two weeks ago caught it, and it was declined automatically — nothing "
        "for you to do. The insurance claim is moving; I expect the packet this week. Two small "
        "questions are waiting whenever you have a minute. There is no hurry.\n\n— Epilogue",
    )
    # Two certified copies have already been spent (bank + insurer claim).
    ledger.kv_set(f"vault:{case.id}:certified_death_certificate", "3")

    return case
