"""Epilogue's custom Strands tools.

These are the hands of the Steward: reading the case file, consulting
playbooks, working the matter ledger, corresponding with institutions, and —
when something genuinely needs a human heart — opening a decision for the
survivor. Every tool is a plain function decorated with ``@strands.tool``,
built as a closure over the case :class:`~epilogue.runtime.Runtime` so the
same definitions serve any number of concurrent cases.

Note how ``submit_to_institution`` and ``ask_survivor`` interact: the Decision
Gate (enforced in code, not prompt) refuses outward actions that exceed the
survivor's autonomy contract and tells the model exactly how to proceed —
surface a decision and stand down. That contract between tools is what turns
"an LLM with function calling" into an agent a grieving family can trust.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from strands import tool

from .domain import AccountInventory, Decision, DecisionOption, TaskItem, TaskStatus
from .planning import ALIASES
from .playbooks import PLAYBOOKS, playbook_for_kind, render_playbook
from .runtime import Runtime
from .simworld import INSTITUTIONS

_STATUS_HELP = ", ".join(s.value for s in TaskStatus)


def _named_institution(title):
    matches = {key for key, aliases in ALIASES.items() if any(alias in title.lower() for alias in aliases)}
    return next(iter(matches)) if len(matches) == 1 else None


def _title_key(title):
    return ''.join(char for char in title.casefold() if char.isalnum())


def build_case_tools(rt: Runtime) -> list:
    """Build the ledger/correspondence/decision tools bound to one case."""

    case_id = rt.case.id

    def identify(task):
        # A uniquely named supported provider can repair an omitted model field.
        # Ambiguous and unknown names remain unassigned; they cannot borrow a channel.
        if not task.institution_id and (key := _named_institution(task.title)):
            task.institution_id = key
            if INSTITUTIONS[key].kind == 'digital':
                task.category, task.risk = 'digital_legacy', 'irreversible'
            rt.ledger.save_task(task)
        return task

    @tool
    def get_case_file() -> str:
        """Read the full case brief: who died, who survives them, today's date,
        the autonomy contract, document vault, and overall progress. Read this
        first when starting a work cycle."""
        open_decisions = rt.ledger.decisions_for_case(case_id, status="open")
        lines = [rt.case_brief()]
        if open_decisions:
            lines.append("\nDecisions currently waiting on the survivor (do NOT duplicate these):")
            for d in open_decisions:
                lines.append(f"  - {d.id} (matter {d.task_id}): {d.question}")
        return "\n".join(lines)

    @tool
    def get_playbook(kind_or_id: str) -> str:
        """Look up the institutional playbook for a kind of matter.

        Args:
            kind_or_id: A playbook id (e.g. 'bank_notification') or an institution
                kind (e.g. 'bank', 'gym', 'credit_bureau', 'subscription').
        """
        pb = PLAYBOOKS.get(kind_or_id) or playbook_for_kind(kind_or_id)
        if pb is None:
            return f"No playbook found for '{kind_or_id}'. Known: {', '.join(PLAYBOOKS)}"
        return render_playbook(pb)

    @tool
    def list_matters(status: str = "all") -> str:
        """List the matters (tasks) on this case, one line each.

        Args:
            status: Filter by status, or 'all'. Statuses: pending, in_progress,
                waiting_response, needs_decision, follow_up, done, dismissed.
        """
        tasks = rt.ledger.tasks_for_case(case_id)
        if status != "all":
            tasks = [t for t in tasks if t.status.value == status]
        if not tasks:
            return "No matters match."
        lines = []
        for t in tasks:
            due = f" next_action={t.next_action_at.date()}" if t.next_action_at else ""
            inst = f" @{t.institution_id}" if t.institution_id else ""
            lines.append(f"{t.id} [{t.status.value}] ({t.category}{inst}) {t.title}{due}")
        return "\n".join(lines)

    @tool
    def get_matter(task_id: str) -> str:
        """Read one matter in full: status, playbook, notes, recent correspondence,
        and any survivor decision on file.

        Args:
            task_id: The matter's id, e.g. 'task_ab12cd34ef'.
        """
        t = rt.ledger.get_task(task_id)
        if t is None:
            return f"No matter with id {task_id}."
        identify(t)
        lines = [
            f"{t.id}: {t.title}",
            f"  category={t.category} risk={t.risk} status={t.status.value} institution={t.institution_id}",
            f"  why: {t.why}",
        ]
        if t.next_action_at:
            lines.append(f"  next action scheduled: {t.next_action_at.date()}")
        if t.notes:
            lines.append("  notes: " + " | ".join(t.notes[-6:]))
        approved = rt.ledger.resolved_decision_for_task(t.id)
        if approved:
            opt = next((o for o in approved.options if o.id == approved.resolution_option_id), None)
            authorizes = bool(opt and opt.authorizes)
            lines.append(
                f"  SURVIVOR DECISION ON FILE: chose '{opt.label if opt else approved.resolution_option_id}'"
                + (" (authorizes action)" if authorizes else " (does NOT authorize action — honor it)")
                + (f" — note: {approved.resolution_note}" if approved.resolution_note else "")
            )
        pending = rt.ledger.open_decision_for_task(t.id)
        if pending:
            lines.append(f"  A decision is OPEN and waiting on the survivor: {pending.question}")
        if not t.institution_id:
            lines.append("  No institution channel is assigned. Research and prepare next steps; do not "
                         "send this matter to an unrelated institution or claim it was contacted.")
        mail = [m for m in rt.ledger.mail_for_case(case_id, limit=200) if m.task_id == t.id][:4]
        for m in mail:
            arrow = "→" if m.direction == "outbound" else "←"
            lines.append(f"  {arrow} [{m.sim_date}] {m.institution_name}: {m.subject}")
        return "\n".join(lines)

    @tool
    def create_matter(
        title: str,
        category: str,
        institution_id: str = "",
        why: str = "",
        risk: str = "routine",
        estimated_minutes_saved: int = 45,
    ) -> str:
        """Open a new matter on the ledger (a follow-on discovered mid-case, e.g. an
        unclaimed-funds claim the Advocate found).

        Args:
            title: Short human-readable title.
            category: One of financial, subscriptions, utilities, government,
                insurance, identity, benefits, memorial, digital_legacy.
            institution_id: simworld institution id if the matter involves one.
            why: One sentence on why this matters for the family.
            risk: routine | careful | irreversible.
            estimated_minutes_saved: Survivor minutes this saves when automated.
        """
        # Strands may execute two tool calls from the same model turn concurrently.
        with rt.ledger.atomic():
            for existing in rt.ledger.tasks_for_case(case_id):
                if _title_key(existing.title) == _title_key(title):
                    identify(existing)
                    return f"Already on file as {existing.id} ({existing.status.value}). Review and update that matter; do not duplicate it."
            institution_id = institution_id or _named_institution(title) or ''
            if institution_id and institution_id not in INSTITUTIONS:
                return "That institution has no simulated channel. Leave its ID empty and prepare manual next steps."
            if institution_id and INSTITUTIONS[institution_id].kind == 'digital':
                category, risk = 'digital_legacy', 'irreversible'
            task = TaskItem(
                case_id=case_id,
                title=title,
                category=category,
                institution_id=institution_id or None,
                why=why,
                risk=risk,
                estimated_minutes_saved=estimated_minutes_saved,
            )
            rt.ledger.save_task(task)
            rt.ledger.record(case_id, "Steward", "status", f"Opened new matter: {title}", task_id=task.id)
            return f"Created {task.id}."

    @tool
    def update_matter(task_id: str, status: str = "", note: str = "", follow_up_days: int = 0) -> str:
        """Update a matter's status, add a note, and/or schedule a follow-up.

        Args:
            task_id: The matter to update.
            status: New status if changing (pending, in_progress, waiting_response,
                needs_decision, follow_up, done, dismissed). Leave empty to keep.
            note: A short progress note for the record.
            follow_up_days: If > 0, the Vigil will bring this matter back in that
                many days (sets the next-action date).
        """
        t = rt.ledger.get_task(task_id)
        if t is None:
            return f"No matter with id {task_id}."
        if status:
            try:
                t.status = TaskStatus(status)
            except ValueError:
                return f"Invalid status '{status}'. Valid: {_STATUS_HELP}"
        if note:
            t.notes.append(f"[{rt.ledger.sim_today()}] {note}")
        if follow_up_days > 0:
            due = rt.ledger.sim_today() + timedelta(days=follow_up_days)
            t.next_action_at = datetime.combine(due, datetime.min.time(), tzinfo=timezone.utc)
            if not status:
                t.status = TaskStatus.FOLLOW_UP
        rt.ledger.save_task(t)
        if t.status == TaskStatus.DONE:
            rt.ledger.record(case_id, "Steward", "status", f"Settled: {t.title}", detail=note, task_id=t.id)
        return f"Updated {t.id}: status={t.status.value}" + (
            f", follow-up in {follow_up_days}d" if follow_up_days else ""
        )

    @tool
    def submit_to_institution(
        task_id: str,
        institution_id: str,
        subject: str,
        body: str,
        channel: str = "secure_message",
        attachments: list[str] | None = None,
        moves_money_usd: float = 0,
    ) -> str:
        """Send correspondence to an institution on the family's behalf. This is an
        OUTWARD-FACING action and passes through the Decision Gate.

        Args:
            task_id: The matter this correspondence belongs to.
            institution_id: The institution's id (see the matter or case file).
            subject: Subject line.
            body: The full message or letter body. Write it properly — the Scribe
                can draft it for you first.
            channel: secure_message | email | letter | portal_form. Some
                institutions only honor written 'letter' notices — check playbooks.
            attachments: Document names from the vault, e.g.
                ['certified_death_certificate'] or ['death_certificate_copy'].
                Certified copies are finite — use photocopies unless certified is
                explicitly required.
            moves_money_usd: If this action moves, repays, or forfeits money,
                the dollar amount. A payment in this simulated world only happens
                when this field is set; mentioning money in a letter sends no funds.
                The gate requires explicit survivor authorization above their threshold.
        """
        attachments = attachments or []
        t = rt.ledger.get_task(task_id)
        if t is None:
            return f"No matter with id {task_id}. Create or look up the matter first."
        identify(t)
        inst = INSTITUTIONS.get(institution_id)
        if inst is None:
            return (
                f"Unknown institution '{institution_id}' — nothing was sent and no documents were "
                f"used. Known institutions: {', '.join(sorted(INSTITUTIONS))}."
            )
        if t.institution_id != institution_id:
            return ("This institution does not match the matter, or the matter has no supported channel. "
                    "Nothing was sent. Use a matter assigned to this exact institution; otherwise "
                    "prepare instructions for the family without claiming contact was made.")
        if inst.kind == "credit_bureau" and "certified_death_certificate" in attachments:
            return (
                "This simulated bureau accepts 'death_certificate_copy'. Nothing was sent. "
                "Use that copy instead and preserve certified originals for the bank and insurer."
            )
        # The destination's capabilities outrank model-supplied risk labels.
        if inst.kind == "digital":
            t.category, t.risk = "digital_legacy", "irreversible"
            rt.ledger.save_task(t)
        gate = rt.gate_check(t, f"submit to {institution_id}: {subject}", moves_money_usd)
        if not gate.allowed:
            # Only park the matter as needs_decision when a decision actually exists
            # for the survivor to answer; otherwise the Vigil keeps driving it until
            # the Steward asks properly (no silent dead-ends).
            if rt.ledger.open_decision_for_task(t.id) is not None:
                t.status = TaskStatus.NEEDS_DECISION
                rt.ledger.save_task(t)
            return gate.reason
        # Validate the whole attachment list BEFORE consuming anything: certified
        # copies are finite, and a failed send must never burn one.
        vault = rt.vault_status()
        for doc in set(attachments):
            available = vault.get(doc)
            if available is None:
                return (
                    f"Unknown document '{doc}' — nothing was sent. Vault contents: {vault}. "
                    f"Use 'death_certificate_copy' if a photocopy suffices."
                )
            if available != -1 and attachments.count(doc) > available:
                return (
                    f"Not enough '{doc}' left in the vault ({available} remaining) — nothing was "
                    f"sent. Use 'death_certificate_copy' if a photocopy suffices."
                )
        for doc in attachments:
            rt.vault_take(doc)
        receipt = rt.world.submit(case_id, task_id, institution_id, channel, subject, body, attachments,
                                  payment_amount_usd=moves_money_usd)
        if receipt.startswith("ERROR"):
            return receipt
        pb = (
            PLAYBOOKS.get(t.playbook_id)
            if t.playbook_id
            else (playbook_for_kind(inst.kind) if inst else None)
        )
        wait_days = (pb.typical_response_days if pb else 7) + 3
        t.status = TaskStatus.WAITING_RESPONSE
        t.next_action_at = datetime.combine(
            rt.ledger.sim_today() + timedelta(days=wait_days), datetime.min.time(), tzinfo=timezone.utc
        )
        rt.ledger.save_task(t)
        rt.ledger.record(
            case_id,
            "Scribe",
            "letter_sent",
            f"Sent to {inst.name if inst else institution_id}: “{subject}”"
            + (f" (attached: {', '.join(attachments)})" if attachments else ""),
            detail=body,
            task_id=task_id,
        )
        payment_note = ""
        stage = rt.world.get_stage(institution_id, task_id)
        due = 1847 if institution_id == "fed_benefits" and stage == "await_repayment" else (
            19.20 if institution_id == "clearline_wireless" and stage == "awaiting_payment" else 0
        )
        if due:
            payment_note = (
                f" No funds were transferred; ${due:,.2f} remains due. To simulate paying this bill, "
                "first obtain any survivor approval required by the gate, then submit with "
                f"moves_money_usd={due}. A letter asking for instructions does not settle the balance."
            )
        return f"{receipt} {gate.reason} Follow-up auto-scheduled in {wait_days} days if no reply.{payment_note}"

    @tool
    def ask_survivor(
        task_id: str,
        question: str,
        context: str,
        options: list[DecisionOption],
        recommendation: str = "",
        urgency: str = "whenever",
        authorizes_amount_usd: float = 0,
    ) -> str:
        """Surface a real decision to the survivor. Use this ONLY when a matter
        genuinely needs a human: irreversible outcomes, meaningful money, or
        anything touching memories. Never ask about routine mechanics.

        Args:
            task_id: The matter blocked on this decision.
            question: The decision, phrased warmly and plainly in one sentence.
            context: 2-4 sentences of what Epilogue knows, so the survivor can
                decide in under a minute. Plain language, no jargon.
            options: 2-3 options, each with an id (short slug), a label, a one-line
                consequence, and authorizes (true ONLY for options that permit
                Epilogue to proceed with the action; a 'hold' or 'no' option must
                have authorizes=false — the Decision Gate honors this exactly).
            recommendation: The option id Epilogue gently recommends, if any.
            urgency: whenever | this_week | today.
            authorizes_amount_usd: If the decision is about moving/repaying/forfeiting
                money, the dollar amount an approval authorizes. The Decision Gate
                will only permit money moves explicitly authorized this way — state
                the amount in the question so the survivor knows what they approve.
        """
        existing = rt.ledger.open_decision_for_task(task_id)
        if existing:
            return f"A decision is already open for this matter ({existing.id}). Do not duplicate it."
        options = [DecisionOption.model_validate(o) for o in options]
        if not any(o.authorizes for o in options):
            return (
                "Nothing was asked: none of the options has authorizes=true, so approval could "
                "never unblock the matter. Mark authorizes=true on each option that permits "
                "Epilogue to proceed (and leave it false on hold/decline options), then ask again."
            )
        t = rt.ledger.get_task(task_id)
        decision = Decision(
            case_id=case_id,
            task_id=task_id,
            question=question,
            context=context,
            options=options,
            recommendation=recommendation or None,
            urgency=urgency,
            authorizes_amount_usd=authorizes_amount_usd or None,
        )
        rt.ledger.save_decision(decision)
        if t is not None:
            t.status = TaskStatus.NEEDS_DECISION
            rt.ledger.save_task(t)
        rt.ledger.record(
            case_id,
            "Steward",
            "decision_opened",
            f"Asked {rt.case.survivor.full_name.split()[0]}: {question}",
            detail=context,
            task_id=task_id,
        )
        return (
            f"Decision {decision.id} is now in the survivor's inbox. Stand down on this matter; "
            f"the Vigil will resume it once they answer."
        )

    @tool
    def check_document_vault() -> str:
        """See which documents the family has placed in the vault and how many
        certified copies remain."""
        return "\n".join(f"{doc}: {'unlimited' if n == -1 else n}" for doc, n in rt.vault_status().items())

    @tool
    def current_date() -> str:
        """Today's date on the case clock."""
        today = rt.ledger.sim_today()
        return f"{today.isoformat()} ({today.strftime('%A')})"

    return [
        get_case_file,
        get_playbook,
        list_matters,
        get_matter,
        create_matter,
        update_matter,
        submit_to_institution,
        ask_survivor,
        check_document_vault,
        current_date,
    ]


def build_advocate_tools(rt: Runtime) -> list:
    """Research tools for the Advocate (benefits & recovered-money specialist)."""

    @tool
    def search_benefit_records() -> str:
        """Search for money owed to this family: unclaimed property (simulated state
        registry), refundable prepayments mined from the case's account inventory,
        and employer/veteran leads from the intake narrative."""
        case = rt.case
        lines: list[str] = []

        # Unclaimed property — a simworld registry fixture, keyed to the state.
        state = (case.deceased.state or "").upper()
        if state == "OH":
            lines.append(
                f"UNCLAIMED PROPERTY (simulated OH registry): 1 record matches '{case.deceased.full_name}' "
                "at a former address — utility deposit, $312.00. Claimable by the estate via "
                "institution 'ohio_unclaimed'."
            )
        else:
            lines.append(f"UNCLAIMED PROPERTY (simulated registry, {state or 'state unknown'}): no records matched.")

        # Refundable prepayments — mined from what the Archivist actually found.
        inv_raw = rt.ledger.kv_get(f"inventory:{case.id}")
        if inv_raw:
            inventory = AccountInventory.model_validate_json(inv_raw)
            refundable = [
                a
                for a in inventory.accounts
                if any(k in f"{a.evidence} {a.notes or ''}".lower() for k in ("annual", "prepaid", "renew"))
            ]
            if refundable:
                lines.append("REFUNDABLE PREPAYMENTS found in this case's account inventory:")
                lines += [f"  - {a.institution_name}: {a.evidence}" for a in refundable]
            else:
                lines.append("REFUNDABLE PREPAYMENTS: none evident in the account inventory.")
        else:
            lines.append("REFUNDABLE PREPAYMENTS: no account inventory on file yet — run intake first.")

        # Leads from the survivor's own words.
        narrative = case.narrative.lower()
        if "retired" in narrative or "pension" in narrative:
            lines.append(
                "EMPLOYER BENEFITS: a pension/retirement is referenced at intake — confirm survivor "
                "annuity elections and any unpaid final benefit with the plan administrator."
            )
        if "no veteran" in narrative or "not a veteran" in narrative:
            lines.append("VETERAN STATUS: family reports no service — VA burial allowance not applicable.")
        elif "veteran" in narrative or "served in" in narrative:
            lines.append("VETERAN STATUS: possible service record — check VA burial allowance and survivor pension.")

        lines.append(
            "ALSO CHECK: charges processed after the date of death on any account (dues, subscriptions) "
            "are generally refundable on written request."
        )
        return "\n".join(lines)

    return [search_benefit_records]
