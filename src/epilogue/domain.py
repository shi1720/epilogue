"""Domain model for Epilogue.

Everything the agents read and write is expressed in these types. They are
deliberately plain Pydantic models: the task ledger persists them as JSON,
the Strands agents receive them as structured-output targets, and the
dashboard renders them directly.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Case file
# ---------------------------------------------------------------------------


class Person(BaseModel):
    full_name: str
    date_of_birth: date | None = None
    date_of_death: date | None = None
    last_address: str | None = None
    state: str | None = Field(default=None, description="US state of residence, e.g. 'OH'")
    ssn_last4: str | None = Field(default=None, description="Last 4 digits of SSN, never the full number")


class Survivor(BaseModel):
    full_name: str
    relationship: str = Field(description="Relationship to the deceased, e.g. 'daughter'")
    email: str | None = None
    is_executor: bool = Field(default=False, description="Whether they are executor/personal representative")


class AutonomyLevel(str, Enum):
    """How much latitude the survivor has granted Epilogue for a category of work.

    This is the heart of the product: the Autonomy Contract. Routine work runs
    without interruption; anything irreversible, financial above threshold, or
    sentimental crosses the Decision Gate and waits for a human.
    """

    ACT = "act"  # act freely, report in the weekly letter
    ACT_AND_NOTIFY = "act_and_notify"  # act, but show it in the timeline immediately
    ASK_FIRST = "ask_first"  # never act without an approved decision


class AutonomyContract(BaseModel):
    """Per-category autonomy levels plus hard limits that always require a human."""

    defaults: dict[str, AutonomyLevel] = Field(
        default_factory=lambda: {
            "subscriptions": AutonomyLevel.ACT,
            "utilities": AutonomyLevel.ACT_AND_NOTIFY,
            "financial": AutonomyLevel.ACT_AND_NOTIFY,
            "government": AutonomyLevel.ACT_AND_NOTIFY,
            "insurance": AutonomyLevel.ACT_AND_NOTIFY,
            "identity": AutonomyLevel.ACT_AND_NOTIFY,
            "benefits": AutonomyLevel.ACT_AND_NOTIFY,
            "memorial": AutonomyLevel.ASK_FIRST,
            "digital_legacy": AutonomyLevel.ASK_FIRST,
        }
    )
    financial_threshold_usd: float = Field(
        default=500.0,
        description="Any single action moving/forfeiting more than this always asks first",
    )
    always_ask: list[str] = Field(
        default_factory=lambda: [
            "anything irreversible that destroys data, photos, messages, or memories",
            "anything involving property, vehicles, or real estate",
            "any legal filing or signature",
        ]
    )

    def level_for(self, category: str) -> AutonomyLevel:
        return self.defaults.get(category, AutonomyLevel.ASK_FIRST)


class Case(BaseModel):
    id: str = Field(default_factory=lambda: new_id("case"))
    deceased: Person
    survivor: Survivor
    contract: AutonomyContract = Field(default_factory=AutonomyContract)
    narrative: str = Field(default="", description="The survivor's own words from intake")
    created_at: datetime = Field(default_factory=utcnow)
    status: str = "active"  # active | settled


# ---------------------------------------------------------------------------
# Structured-output targets for the intake pipeline
# ---------------------------------------------------------------------------


class DiscoveredAccount(BaseModel):
    """A single account/obligation the Archivist found in the survivor's documents."""

    institution_name: str
    institution_kind: str = Field(
        description=(
            "One of: bank, credit_card, brokerage, subscription, utility, insurance, "
            "government, telecom, digital, airline, gym, other"
        )
    )
    account_hint: str | None = Field(default=None, description="Masked identifier, e.g. 'checking ...4417'")
    evidence: str = Field(description="One line quoting/citing where in the documents this was found")
    estimated_monthly_charge_usd: float | None = None
    estimated_balance_usd: float | None = None
    notes: str | None = None


class AccountInventory(BaseModel):
    """The Archivist's complete findings for a case."""

    accounts: list[DiscoveredAccount] = Field(default_factory=list)
    open_questions: list[str] = Field(
        default_factory=list,
        description="Things the documents hint at but do not confirm, phrased for the survivor",
    )


class IntakeProfile(BaseModel):
    """Structured reading of the survivor's freeform intake message."""

    deceased_full_name: str
    deceased_date_of_death: date | None = None
    deceased_state: str | None = None
    survivor_full_name: str
    survivor_relationship: str
    survivor_is_executor: bool = False
    immediate_worries: list[str] = Field(
        default_factory=list, description="What the survivor sounds most anxious about, in their words"
    )


class PlannedTask(BaseModel):
    """One matter the Steward has decided Epilogue will carry."""

    title: str
    category: str = Field(
        description=(
            "One of: financial, subscriptions, utilities, government, insurance, "
            "identity, benefits, memorial, digital_legacy"
        )
    )
    institution_id: str | None = Field(default=None, description="simworld institution id if known")
    playbook_id: str | None = None
    why: str = Field(description="One sentence: why this matters for the family")
    risk: str = Field(default="routine", description="routine | careful | irreversible")
    estimated_minutes_saved: int = Field(default=45, description="Survivor time this saves if automated")


class TaskPlan(BaseModel):
    tasks: list[PlannedTask] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Ledger records
# ---------------------------------------------------------------------------


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    WAITING_RESPONSE = "waiting_response"  # submitted; institution owes us a reply
    NEEDS_DECISION = "needs_decision"  # blocked at the Decision Gate
    FOLLOW_UP = "follow_up"  # scheduled re-engagement (nudge, re-send)
    DONE = "done"
    DISMISSED = "dismissed"


class TaskItem(BaseModel):
    id: str = Field(default_factory=lambda: new_id("task"))
    case_id: str
    title: str
    category: str
    institution_id: str | None = None
    playbook_id: str | None = None
    why: str = ""
    risk: str = "routine"
    status: TaskStatus = TaskStatus.PENDING
    next_action_at: datetime | None = None  # sim-time when the Vigil should touch this again
    estimated_minutes_saved: int = 45
    notes: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class DecisionOption(BaseModel):
    id: str
    label: str
    consequence: str = Field(description="Plain-language outcome if this option is chosen")
    authorizes: bool = Field(
        default=False,
        description=(
            "True only if choosing this option permits Epilogue to proceed with the "
            "blocked action. A 'hold' or 'decline' option must leave this False."
        ),
    )


class Decision(BaseModel):
    id: str = Field(default_factory=lambda: new_id("dec"))
    case_id: str
    task_id: str | None = None
    question: str
    context: str = Field(description="What Epilogue knows, in warm plain language")
    options: list[DecisionOption]
    recommendation: str | None = Field(default=None, description="Option id Epilogue gently recommends")
    urgency: str = "whenever"  # whenever | this_week | today
    authorizes_amount_usd: float | None = Field(
        default=None,
        description="When the decision is about moving money, the amount it authorizes if approved",
    )
    status: str = "open"  # open | resolved
    resolution_option_id: str | None = None
    resolution_note: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    resolved_at: datetime | None = None


class AuditEvent(BaseModel):
    id: str = Field(default_factory=lambda: new_id("evt"))
    case_id: str
    actor: str  # Steward, Archivist, Scribe, Advocate, Sentinel, Vigil, Survivor
    kind: str  # tool_call | letter_sent | mail_received | decision_opened | decision_resolved | status | note
    summary: str  # human-readable line for the "Handled quietly" timeline
    detail: str = ""
    task_id: str | None = None
    at: datetime = Field(default_factory=utcnow)
    sim_date: date | None = None


class MailMessage(BaseModel):
    """Correspondence between Epilogue and the outside world (simworld or real)."""

    id: str = Field(default_factory=lambda: new_id("mail"))
    case_id: str
    direction: str  # outbound | inbound
    institution_id: str
    institution_name: str
    channel: str = "secure_message"  # secure_message | email | letter | portal_form
    subject: str
    body: str
    task_id: str | None = None
    status: str = "unread"  # unread | processed | sent
    sim_date: date | None = None
    created_at: datetime = Field(default_factory=utcnow)


class TriageResult(BaseModel):
    """Structured reading of one inbound institution message."""

    disposition: str = Field(
        description=(
            "One of: resolved (the matter is complete), needs_document (they want something we can "
            "provide), needs_action (a concrete next step Epilogue can take), needs_human (a real "
            "decision or something only the survivor can do), wait (nothing to do yet)"
        )
    )
    summary: str = Field(description="One warm plain-language line describing what happened")
    requested_items: list[str] = Field(default_factory=list)
    suggested_next_step: str | None = None
    follow_up_days: int | None = Field(
        default=None, description="If we should check back later, in how many days"
    )
