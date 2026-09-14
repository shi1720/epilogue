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
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from .agents import build_steward, read_intake, run_archivist, run_planner, triage_mail
from .domain import AccountInventory, Case, IntakeProfile, Person, Survivor, TaskStatus, utcnow
from .ledger import Ledger
from .runtime import Runtime
from .simworld import SimWorld

_TRANSIENT_MARKERS = (
    "503",
    "unavailable",
    "429",
    "throttl",
    "overload",
    "resource exhausted",
    "timed out",
    "timeout",
)


def _is_transient(exc: Exception) -> bool:
    text = str(exc).lower()
    if "insufficient_quota" in text or "billing" in text:
        return False
    return any(marker in text for marker in _TRANSIENT_MARKERS)


def _with_retry(label: str, fn, attempts: int = 4, base_delay: float = 8.0):
    """Ride out transient model-provider weather (503s, rate limits).

    Real estates take months; a five-minute provider hiccup should never cost
    the family anything. Non-transient errors raise immediately.
    """
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            if attempt == attempts - 1 or not _is_transient(exc):
                raise
            time.sleep(base_delay * (2**attempt))


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

    def _run_steward(self, steward, prompt: str, case_id: str) -> bool:
        """One steward work cycle, riding out transient provider errors.

        Returns False (and leaves a note) if the provider stayed down — the
        matter simply comes back next cycle; nothing is lost but time.
        """
        try:
            _with_retry("steward", lambda: steward(prompt), attempts=3, base_delay=10.0)
            return True
        except Exception as exc:  # noqa: BLE001
            if not _is_transient(exc):
                raise
            self.ledger.record(
                case_id,
                "Vigil",
                "status",
                "A model-provider hiccup interrupted one matter — it will be retried next cycle.",
                detail=str(exc)[:300],
            )
            return False

    # ------------------------------------------------------------------
    # Intake
    # ------------------------------------------------------------------

    def open_case(self, narrative: str, documents: str) -> Case:
        """Run the full intake pipeline: narrative → profile → inventory → plan."""
        saved_profile = self.ledger.kv_get("intake_profile")
        profile = (IntakeProfile.model_validate_json(saved_profile) if saved_profile else
                   _with_retry("intake", lambda: read_intake(self.model, narrative, today=self.ledger.sim_today())))
        self.ledger.kv_set("intake_profile", profile.model_dump_json())
        case = self.ledger.first_case() or Case(
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
        saved_inventory = self.ledger.kv_get(f"inventory:{case.id}")
        inventory = (AccountInventory.model_validate_json(saved_inventory) if saved_inventory else
                     _with_retry("archivist", lambda: run_archivist(self.model, rt, documents)))
        if not self.ledger.kv_get("intake_planned"):
            _with_retry("planner", lambda: run_planner(self.model, rt, profile, inventory))
            self.world.seed_case_events(case.id)
            self.ledger.kv_set("intake_planned", "1")
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
            try:
                triage = _with_retry(
                    "triage",
                    lambda m=mail: triage_mail(self.model, m.subject, m.body, m.institution_name),
                    attempts=3,
                    base_delay=10.0,
                )
            except Exception as exc:  # noqa: BLE001
                if not _is_transient(exc):
                    raise
                continue  # mail stays unread; the next cycle triages it
            report.mail_triaged += 1
            task = self.ledger.get_task(mail.task_id) if mail.task_id else None

            if triage.disposition == "resolved" and task is not None:
                mail.status = "processed"
                self.ledger.save_mail(mail)
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
                mail.status = "processed"
                self.ledger.save_mail(mail)
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
            if self._run_steward(steward, prompt, case_id):
                mail.status = "processed"
                self.ledger.save_mail(mail)
            if mail.task_id:
                report.matters_touched.append(mail.task_id)

        # 3. Resume matters the survivor has unblocked.
        for decision in self.ledger.decisions_for_case(case_id, status="resolved"):
            flag = f"decision_handled:{decision.id}"
            if self.ledger.kv_get(flag):
                continue
            if runs >= self.max_steward_runs:
                continue  # not marked handled — the next cycle delivers this context
            chosen = next((o for o in decision.options if o.id == decision.resolution_option_id), None)
            runs += 1
            handled = self._run_steward(
                steward,
                (
                    f"{case.survivor.full_name.split()[0]} answered your question on matter "
                    f"{decision.task_id}.\nQuestion: {decision.question}\nThey chose: "
                    f"'{chosen.label if chosen else decision.resolution_option_id}'"
                    + (f" and added: “{decision.resolution_note}”" if decision.resolution_note else "")
                    + "\n\nProceed on that matter now, honoring their choice exactly."
                ),
                case_id,
            )
            if handled:
                self.ledger.kv_set(flag, "1")
            if decision.task_id:
                report.matters_touched.append(decision.task_id)

        # 3.5 Reclaim orphans: a matter marked needs_decision with no decision on
        # file would otherwise wait forever (nothing for the survivor to answer).
        for task in self.ledger.tasks_for_case(case_id, status=TaskStatus.NEEDS_DECISION):
            if (
                self.ledger.open_decision_for_task(task.id) is None
                and self.ledger.resolved_decision_for_task(task.id) is None
            ):
                task.status = TaskStatus.IN_PROGRESS
                task.next_action_at = None
                task.notes.append(
                    f"[{self.ledger.sim_today()}] Reclaimed by the Vigil: marked needs_decision "
                    "but no decision was on file."
                )
                self.ledger.save_task(task)

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
            self._run_steward(
                steward,
                f"Work this matter now: {task.id} — {task.title} (category {task.category}, "
                f"status {task.status.value}).{overdue_note}\n"
                "Read it first with get_matter, consult the playbook if this is first contact, "
                "then act end to end and record progress.",
                case_id,
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
        resolve_decision(self.ledger, decision_id, option_id, note)

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
        self.ledger.kv_set(f"weekly_note_date:{case.id}", today.isoformat())
        self.ledger.record(
            case.id, "Epilogue", "note", f"A note for {first} about the week", detail=note.strip()
        )


def resolve_decision(ledger: Ledger, decision_id: str, option_id: str, note: str = "") -> None:
    """Record the survivor's answer on the ledger and unblock the matter.

    Standalone so the dashboard can resolve decisions even with no model
    configured (preview mode); the Vigil delegates here.
    """
    decision = ledger.get_decision(decision_id)
    if decision is None or decision.status == "resolved":
        return
    if not any(option.id == option_id for option in decision.options):
        raise ValueError("Choose one of the options on this decision.")
    decision.status = "resolved"
    decision.resolution_option_id = option_id
    decision.resolution_note = note or None
    decision.resolved_at = utcnow()
    ledger.save_decision(decision)
    chosen = next((o for o in decision.options if o.id == option_id), None)
    case = ledger.get_case(decision.case_id)
    first = case.survivor.full_name.split()[0] if case else "The survivor"
    ledger.record(
        decision.case_id,
        "Survivor",
        "decision_resolved",
        f"{first} decided: {chosen.label if chosen else option_id}",
        detail=(note or ""),
        task_id=decision.task_id,
    )
    if decision.task_id:
        task = ledger.get_task(decision.task_id)
        if task is not None:
            task.status = TaskStatus.IN_PROGRESS
            task.next_action_at = None
            ledger.save_task(task)
