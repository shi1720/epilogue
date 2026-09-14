"""The Vigil — Epilogue's quiet background loop.

Estate settlement is not a conversation; it is weeks of small obligations
arriving on their own schedule. The Vigil wakes on a cadence (a scheduler in
production, an accelerated clock in the demo), and each cycle it:

1. delivers any institution replies that have come due,
2. triages each reply into a typed disposition and routes it,
3. resumes matters the survivor has unblocked by answering a decision,
4. works whatever matters are due — new ones, and follow-ups on
   institutions that have gone quiet,
5. every simulated week, writes the survivor a plain-language note about
   what was handled.

Design note: the agents are deliberately **stateless between cycles**. All
memory lives in the ledger — matter notes, correspondence, decisions — so
any Steward instance can pick up any case at any time. That is what makes
the system restartable, horizontally scalable, and auditable: the context
window is a scratchpad, never the system of record.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from .agents import build_steward, read_intake, run_archivist, run_planner, triage_mail
from .domain import Case, Person, Survivor, TaskStatus, utcnow
from .ledger import Ledger
from .runtime import Runtime
from .simworld import SimWorld


@dataclass
class TickReport:
    sim_date: str = ""
    mail_delivered: int = 0
    mail_triaged: int = 0
    steward_runs: int = 0
    matters_touched: list[str] = field(default_factory=list)
    quiet: bool = True

    def summary(self) -> str:
        if self.quiet:
            return f"{self.sim_date}: a quiet day — nothing needed attention."
        return (
            f"{self.sim_date}: {self.mail_delivered} replies delivered, {self.mail_triaged} triaged, "
            f"{self.steward_runs} matters worked."
        )


class Vigil:
    """Owns the background cadence for every case in the ledger."""

    def __init__(
        self,
        ledger: Ledger,
        model,
        max_steward_runs_per_tick: int = 6,
        enable_weekly_notes: bool = True,
    ) -> None:
        self.ledger = ledger
        self.world = SimWorld(ledger)
        self.model = model
        self.max_steward_runs = max_steward_runs_per_tick
        self.enable_weekly_notes = enable_weekly_notes
        self._locks: dict[str, threading.Lock] = {}
        self._lock_guard = threading.Lock()

    def _case_lock(self, case_id: str) -> threading.Lock:
        with self._lock_guard:
            return self._locks.setdefault(case_id, threading.Lock())

    def _runtime(self, case: Case) -> Runtime:
        return Runtime(ledger=self.ledger, world=self.world, case=case)

    # ------------------------------------------------------------------
    # Intake
    # ------------------------------------------------------------------

    def open_case(self, narrative: str, documents: str) -> Case:
        """Run the full intake pipeline: narrative → profile → inventory → plan."""
        profile = read_intake(self.model, narrative)
        case = Case(
            deceased=Person(
                full_name=profile.deceased_full_name,
                date_of_death=profile.deceased_date_of_death,
                state=profile.deceased_state,
            ),
            survivor=Survivor(
                full_name=profile.survivor_full_name,
                relationship=profile.survivor_relationship,
                is_executor=profile.survivor_is_executor,
            ),
            narrative=narrative,
        )
        self.ledger.save_case(case)
        self.ledger.record(
            case.id,
            "Epilogue",
            "status",
            f"Case opened for the family of {case.deceased.full_name}",
            detail=f"Immediate worries heard at intake: {', '.join(profile.immediate_worries) or '—'}",
        )
        rt = self._runtime(case)
        inventory = run_archivist(self.model, rt, documents)
        run_planner(self.model, rt, profile, inventory)
        self.world.seed_case_events(case.id)
        return case

    # ------------------------------------------------------------------
    # One cycle
    # ------------------------------------------------------------------

    def tick(self, case_id: str) -> TickReport:
        lock = self._case_lock(case_id)
        with lock:
            return self._tick_locked(case_id)

    def _tick_locked(self, case_id: str) -> TickReport:
        case = self.ledger.get_case(case_id)
        if case is None:
            raise ValueError(f"No case {case_id}")
        rt = self._runtime(case)
        report = TickReport(sim_date=self.ledger.sim_today().isoformat())

        # 1. The postal service does its rounds.
        delivered = self.world.deliver_due(case_id)
        report.mail_delivered = len(delivered)

        steward = build_steward(self.model, rt)
        runs = 0

        # 2. Read and route the morning's mail.
        for mail in self.ledger.unread_mail(case_id):
            triage = triage_mail(self.model, mail.subject, mail.body, mail.institution_name)
            report.mail_triaged += 1
            mail.status = "processed"
            self.ledger.save_mail(mail)
            task = self.ledger.get_task(mail.task_id) if mail.task_id else None

            if triage.disposition == "resolved" and task is not None:
                task.status = TaskStatus.DONE
                task.notes.append(f"[{self.ledger.sim_today()}] {triage.summary}")
                self.ledger.save_task(task)
                self.ledger.record(
                    case_id,
                    "Steward",
                    "status",
                    f"Settled: {task.title}",
                    detail=triage.summary,
                    task_id=task.id,
                )
                report.matters_touched.append(task.id)
                continue
            if triage.disposition == "wait":
                if task is not None and triage.follow_up_days:
                    self._schedule_follow_up(task, triage.follow_up_days, triage.summary)
                continue
            if runs >= self.max_steward_runs:
                continue  # leave for the next cycle; mail stays in the matter record
            runs += 1
            prompt = (
                f"Correspondence arrived from {mail.institution_name}"
                + (f" on matter {mail.task_id}" if mail.task_id else "")
                + f".\nSubject: {mail.subject}\n\n{mail.body}\n\n"
                f"A first read classified it as: {triage.model_dump_json()}\n\n"
                "Handle this now, end to end. If it needs the survivor, craft the decision well."
            )
            steward(prompt)
            if mail.task_id:
                report.matters_touched.append(mail.task_id)

        # 3. Resume matters the survivor has unblocked.
        for decision in self.ledger.decisions_for_case(case_id, status="resolved"):
            flag = f"decision_handled:{decision.id}"
            if self.ledger.kv_get(flag):
                continue
            self.ledger.kv_set(flag, "1")
            if runs >= self.max_steward_runs:
                continue
            chosen = next((o for o in decision.options if o.id == decision.resolution_option_id), None)
            runs += 1
            steward(
                f"{case.survivor.full_name.split()[0]} answered your question on matter "
                f"{decision.task_id}.\nQuestion: {decision.question}\nThey chose: "
                f"'{chosen.label if chosen else decision.resolution_option_id}'"
                + (f" and added: “{decision.resolution_note}”" if decision.resolution_note else "")
                + "\n\nProceed on that matter now, honoring their choice exactly."
            )
            if decision.task_id:
                report.matters_touched.append(decision.task_id)

        # 4. Work what is due: fresh matters and follow-ups on quiet institutions.
        for task in self.ledger.due_tasks(case_id):
            if runs >= self.max_steward_runs:
                break
            if task.id in report.matters_touched or task.status == TaskStatus.NEEDS_DECISION:
                continue
            runs += 1
            overdue_note = ""
            if task.status in (TaskStatus.WAITING_RESPONSE, TaskStatus.FOLLOW_UP):
                overdue_note = (
                    "\nThis matter is back because the scheduled follow-up date arrived — the "
                    "institution has NOT answered. Chase it: re-send, switch channel per the "
                    "playbook, or escalate."
                )
            steward(
                f"Work this matter now: {task.id} — {task.title} (category {task.category}, "
                f"status {task.status.value}).{overdue_note}\n"
                "Read it first with get_matter, consult the playbook if this is first contact, "
                "then act end to end and record progress."
            )
            report.matters_touched.append(task.id)

        report.steward_runs = runs
        report.quiet = report.mail_delivered == 0 and report.mail_triaged == 0 and runs == 0

        # 5. The weekly note home.
        if self.enable_weekly_notes:
            self._maybe_write_weekly_note(case)
        return report

    def _schedule_follow_up(self, task, days: int, note: str) -> None:
        task.status = TaskStatus.FOLLOW_UP
        task.next_action_at = datetime.combine(
            self.ledger.sim_today() + timedelta(days=days), datetime.min.time(), tzinfo=timezone.utc
        )
        task.notes.append(f"[{self.ledger.sim_today()}] {note}")
        self.ledger.save_task(task)

    # ------------------------------------------------------------------
    # Clock control (the demo compresses weeks into minutes)
    # ------------------------------------------------------------------

    def advance(self, case_id: str, days: int = 1) -> TickReport:
        self.ledger.advance_days(days)
        return self.tick(case_id)

    # ------------------------------------------------------------------
    # Survivor actions
    # ------------------------------------------------------------------

    def resolve_decision(self, decision_id: str, option_id: str, note: str = "") -> None:
        decision = self.ledger.get_decision(decision_id)
        if decision is None or decision.status == "resolved":
            return
        decision.status = "resolved"
        decision.resolution_option_id = option_id
        decision.resolution_note = note or None
        decision.resolved_at = utcnow()
        self.ledger.save_decision(decision)
        chosen = next((o for o in decision.options if o.id == option_id), None)
        case = self.ledger.get_case(decision.case_id)
        first = case.survivor.full_name.split()[0] if case else "The survivor"
        self.ledger.record(
            decision.case_id,
            "Survivor",
            "decision_resolved",
            f"{first} decided: {chosen.label if chosen else option_id}",
            detail=(note or ""),
            task_id=decision.task_id,
        )
        if decision.task_id:
            task = self.ledger.get_task(decision.task_id)
            if task is not None:
                task.status = TaskStatus.IN_PROGRESS
                task.next_action_at = None
                self.ledger.save_task(task)

    # ------------------------------------------------------------------
    # The weekly note
    # ------------------------------------------------------------------

    def _maybe_write_weekly_note(self, case: Case) -> None:
        today = self.ledger.sim_today()
        last = self.ledger.kv_get(f"weekly_note_date:{case.id}")
        if last and (today - date.fromisoformat(last)).days < 7:
            return
        events = [
            e
            for e in self.ledger.audit_for_case(case.id, limit=150)
            if e.kind in ("letter_sent", "mail_received", "status", "decision_resolved")
            and (not last or (e.sim_date and e.sim_date.isoformat() > last))
        ]
        if len(events) < 3:
            return
        self.ledger.kv_set(f"weekly_note_date:{case.id}", today.isoformat())
        from strands import Agent

        first = case.survivor.full_name.split()[0]
        writer = Agent(
            model=self.model,
            name="Steward",
            system_prompt=(
                f"You write {first} a short weekly note about what Epilogue quietly handled on "
                f"the estate of {case.deceased.full_name}. Warm, plain, unhurried — like a "
                "trusted family friend reporting in. 4-7 sentences. Mention concrete things "
                "(letters sent, replies received, money recovered, anything protected). No "
                "bullet points, no sign-off flourishes. Sign simply: — Epilogue"
            ),
            callback_handler=None,
        )
        lines = "\n".join(f"[{e.sim_date}] {e.actor}: {e.summary}" for e in reversed(events))
        note = str(writer(f"This week's record:\n{lines}\n\nWrite this week's note to {first}."))
        self.ledger.kv_set(f"weekly_note:{case.id}", note.strip())
        self.ledger.record(
            case.id, "Epilogue", "note", f"A note for {first} about the week", detail=note.strip()
        )
