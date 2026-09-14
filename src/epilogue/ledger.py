"""The task ledger — Epilogue's single source of truth.

A small SQLite store holding the case file, every matter Epilogue is carrying,
every letter sent and received, every decision surfaced to the survivor, and a
complete audit trail of everything the agents did. Records are Pydantic models
persisted as JSON with a few indexed columns for querying.

The ledger also carries the simulation clock ("sim date"). Estate settlement
happens over weeks; the Vigil advances this clock so a demo can live through
months of quiet work in minutes, and a real deployment simply advances it in
step with the calendar.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .domain import (
    AuditEvent,
    Case,
    Decision,
    MailMessage,
    TaskItem,
    TaskStatus,
    utcnow,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cases    (id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tasks    (id TEXT PRIMARY KEY, case_id TEXT, status TEXT, category TEXT,
                                     next_action_at TEXT, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS decisions(id TEXT PRIMARY KEY, case_id TEXT, status TEXT, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit    (id TEXT PRIMARY KEY, case_id TEXT, at TEXT, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS mail     (id TEXT PRIMARY KEY, case_id TEXT, direction TEXT, status TEXT,
                                     data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS kv      (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_tasks_case ON tasks(case_id, status);
CREATE INDEX IF NOT EXISTS idx_mail_case  ON mail(case_id, direction, status);
CREATE INDEX IF NOT EXISTS idx_audit_case ON audit(case_id, at);
"""


class Ledger:
    """Thread-safe SQLite-backed ledger with a lightweight event bus.

    Agents run on worker threads while the dashboard streams live activity
    over SSE; subscribers registered with :meth:`on_event` receive every
    audit event as it lands.
    """

    def __init__(self, path: str | Path = "data/epilogue.db", records=None) -> None:
        self.records = records
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.RLock()
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
        self._listeners: list[Callable[[AuditEvent], None]] = []
        if records:
            for entry in records.all():
                table, row = entry["table"], entry["row"]
                if table not in ("cases", "tasks", "decisions", "audit", "mail", "kv"):
                    raise ValueError("Unexpected ledger table")
                names = ",".join(row)
                placeholders = ",".join("?" for _ in row)
                self._conn.execute(f"INSERT OR REPLACE INTO {table} ({names}) VALUES ({placeholders})", tuple(row.values()))
            self._conn.commit()

    # -- event bus ---------------------------------------------------------

    def on_event(self, listener: Callable[[AuditEvent], None]) -> None:
        self._listeners.append(listener)

    def _emit(self, event: AuditEvent) -> None:
        for listener in list(self._listeners):
            try:
                listener(event)
            except Exception:  # noqa: BLE001 - a bad listener must not break the agents
                pass

    # -- helpers -----------------------------------------------------------

    def _put(self, table: str, row_id: str, data: str, extra: dict | None = None) -> None:
        cols = {"id": row_id, "data": data, **(extra or {})}
        placeholders = ",".join("?" for _ in cols)
        names = ",".join(cols)
        with self._lock:
            if self.records:
                self.records.put(table, row_id, cols)
            self._conn.execute(
                f"INSERT OR REPLACE INTO {table} ({names}) VALUES ({placeholders})", tuple(cols.values())
            )
            self._conn.commit()

    def _rows(self, sql: str, args: tuple = ()) -> list[str]:
        with self._lock:
            return [r[0] for r in self._conn.execute(sql, args).fetchall()]

    # -- sim clock ---------------------------------------------------------

    def sim_today(self) -> date:
        rows = self._rows("SELECT value FROM kv WHERE key='sim_today'")
        if rows:
            return date.fromisoformat(rows[0])
        today = datetime.now(timezone.utc).date()
        self.set_sim_today(today)
        return today

    def set_sim_today(self, day: date) -> None:
        self.kv_set("sim_today", day.isoformat())

    def advance_days(self, days: int = 1) -> date:
        new_day = self.sim_today() + timedelta(days=days)
        self.set_sim_today(new_day)
        return new_day

    # -- generic kv (used by simworld for its delivery queue and stages) ----

    def kv_get(self, key: str, default: str | None = None) -> str | None:
        rows = self._rows("SELECT value FROM kv WHERE key=?", (key,))
        return rows[0] if rows else default

    def kv_set(self, key: str, value: str) -> None:
        with self._lock:
            if self.records:
                self.records.put("kv", key, {"key": key, "value": value})
            self._conn.execute("INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)", (key, value))
            self._conn.commit()

    # -- cases -------------------------------------------------------------

    def save_case(self, case: Case) -> Case:
        self._put("cases", case.id, case.model_dump_json())
        return case

    def get_case(self, case_id: str) -> Case | None:
        rows = self._rows("SELECT data FROM cases WHERE id=?", (case_id,))
        return Case.model_validate_json(rows[0]) if rows else None

    def first_case(self) -> Case | None:
        rows = self._rows("SELECT data FROM cases ORDER BY rowid LIMIT 1")
        return Case.model_validate_json(rows[0]) if rows else None

    # -- tasks -------------------------------------------------------------

    def save_task(self, task: TaskItem) -> TaskItem:
        task.updated_at = utcnow()
        self._put(
            "tasks",
            task.id,
            task.model_dump_json(),
            {
                "case_id": task.case_id,
                "status": task.status.value,
                "category": task.category,
                "next_action_at": task.next_action_at.isoformat() if task.next_action_at else None,
            },
        )
        return task

    def get_task(self, task_id: str) -> TaskItem | None:
        rows = self._rows("SELECT data FROM tasks WHERE id=?", (task_id,))
        return TaskItem.model_validate_json(rows[0]) if rows else None

    def tasks_for_case(self, case_id: str, status: TaskStatus | None = None) -> list[TaskItem]:
        if status:
            rows = self._rows(
                "SELECT data FROM tasks WHERE case_id=? AND status=? ORDER BY rowid", (case_id, status.value)
            )
        else:
            rows = self._rows("SELECT data FROM tasks WHERE case_id=? ORDER BY rowid", (case_id,))
        return [TaskItem.model_validate_json(r) for r in rows]

    def due_tasks(self, case_id: str) -> list[TaskItem]:
        """Tasks the Vigil should touch this cycle: fresh, or due for follow-up."""
        now = datetime.combine(self.sim_today(), datetime.min.time(), tzinfo=timezone.utc)
        out: list[TaskItem] = []
        for task in self.tasks_for_case(case_id):
            if task.status == TaskStatus.PENDING:
                out.append(task)
            elif task.status in (TaskStatus.WAITING_RESPONSE, TaskStatus.FOLLOW_UP, TaskStatus.IN_PROGRESS):
                if task.next_action_at is None or task.next_action_at <= now:
                    out.append(task)
        return out

    # -- decisions ---------------------------------------------------------

    def save_decision(self, decision: Decision) -> Decision:
        self._put(
            "decisions",
            decision.id,
            decision.model_dump_json(),
            {"case_id": decision.case_id, "status": decision.status},
        )
        return decision

    def get_decision(self, decision_id: str) -> Decision | None:
        rows = self._rows("SELECT data FROM decisions WHERE id=?", (decision_id,))
        return Decision.model_validate_json(rows[0]) if rows else None

    def decisions_for_case(self, case_id: str, status: str | None = None) -> list[Decision]:
        if status:
            rows = self._rows(
                "SELECT data FROM decisions WHERE case_id=? AND status=? ORDER BY rowid", (case_id, status)
            )
        else:
            rows = self._rows("SELECT data FROM decisions WHERE case_id=? ORDER BY rowid", (case_id,))
        return [Decision.model_validate_json(r) for r in rows]

    def open_decision_for_task(self, task_id: str) -> Decision | None:
        for dec in [
            Decision.model_validate_json(r)
            for r in self._rows("SELECT data FROM decisions WHERE status='open'")
        ]:
            if dec.task_id == task_id:
                return dec
        return None

    def resolved_decision_for_task(self, task_id: str) -> Decision | None:
        rows = self._rows("SELECT data FROM decisions WHERE status='resolved' ORDER BY rowid DESC")
        for raw in rows:
            dec = Decision.model_validate_json(raw)
            if dec.task_id == task_id:
                return dec
        return None

    def authorizing_decision_for_task(self, task_id: str) -> Decision | None:
        """The most recent resolved decision whose CHOSEN option authorizes action.

        A survivor who answered "hold — let me ask the attorney" has decided, but
        has not authorized anything; the Decision Gate must stay closed. Only the
        chosen option's ``authorizes`` flag opens it.
        """
        decision = self.resolved_decision_for_task(task_id)
        if decision is None:
            return None
        chosen = next((o for o in decision.options if o.id == decision.resolution_option_id), None)
        return decision if (chosen is not None and chosen.authorizes) else None

    # -- mail --------------------------------------------------------------

    def save_mail(self, mail: MailMessage) -> MailMessage:
        self._put(
            "mail",
            mail.id,
            mail.model_dump_json(),
            {"case_id": mail.case_id, "direction": mail.direction, "status": mail.status},
        )
        return mail

    def unread_mail(self, case_id: str) -> list[MailMessage]:
        rows = self._rows(
            "SELECT data FROM mail WHERE case_id=? AND direction='inbound' AND status='unread' ORDER BY rowid",
            (case_id,),
        )
        return [MailMessage.model_validate_json(r) for r in rows]

    def mail_for_case(self, case_id: str, limit: int = 200) -> list[MailMessage]:
        rows = self._rows(
            "SELECT data FROM mail WHERE case_id=? ORDER BY rowid DESC LIMIT ?", (case_id, limit)
        )
        return [MailMessage.model_validate_json(r) for r in rows]

    def get_mail(self, mail_id: str) -> MailMessage | None:
        rows = self._rows("SELECT data FROM mail WHERE id=?", (mail_id,))
        return MailMessage.model_validate_json(rows[0]) if rows else None

    # -- audit -------------------------------------------------------------

    def record(
        self,
        case_id: str,
        actor: str,
        kind: str,
        summary: str,
        detail: str = "",
        task_id: str | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            case_id=case_id,
            actor=actor,
            kind=kind,
            summary=summary,
            detail=detail,
            task_id=task_id,
            sim_date=self.sim_today(),
        )
        self._put(
            "audit", event.id, event.model_dump_json(), {"case_id": case_id, "at": event.at.isoformat()}
        )
        self._emit(event)
        return event

    def audit_for_case(self, case_id: str, limit: int = 400) -> list[AuditEvent]:
        rows = self._rows(
            "SELECT data FROM audit WHERE case_id=? ORDER BY at DESC, rowid DESC LIMIT ?", (case_id, limit)
        )
        return [AuditEvent.model_validate_json(r) for r in rows]

    # -- stats -------------------------------------------------------------

    def stats(self, case_id: str) -> dict:
        tasks = self.tasks_for_case(case_id)
        done = [t for t in tasks if t.status == TaskStatus.DONE]
        open_decisions = self.decisions_for_case(case_id, status="open")
        minutes = sum(t.estimated_minutes_saved for t in done)
        return {
            "total_matters": len(tasks),
            "settled": len(done),
            "in_motion": len(
                [
                    t
                    for t in tasks
                    if t.status in (TaskStatus.IN_PROGRESS, TaskStatus.WAITING_RESPONSE, TaskStatus.FOLLOW_UP)
                ]
            ),
            "waiting_on_you": len(open_decisions),
            "hours_given_back": round(minutes / 60, 1),
            "sim_today": self.sim_today().isoformat(),
        }

    def reset(self) -> None:
        if self.records:
            raise RuntimeError("Create a new ledger generation to reset a hosted case.")
        with self._lock:
            for table in ("cases", "tasks", "decisions", "audit", "mail", "kv"):
                self._conn.execute(f"DELETE FROM {table}")
            self._conn.commit()
