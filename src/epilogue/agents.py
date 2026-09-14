"""Epilogue's agents, built on the Strands Agents SDK.

The cast:

* **Steward** — the orchestrator. Owns the case, works the matter ledger,
  corresponds with institutions, and decides (within the Decision Gate)
  what runs quietly and what goes to the survivor. The specialists below
  are mounted on the Steward as tools via ``Agent.as_tool()``.
* **Scribe** — drafts institution-ready correspondence with the right
  formalities and a humane tone.
* **Advocate** — hunts for money the family is owed: unclaimed property,
  refunds, benefits.
* **Sentinel** — assesses identity-theft and fraud signals against the
  deceased's estate ("ghosting" fraud).
* **Archivist** — at intake, reads the family's documents and inventories
  every account and obligation (typed output: ``AccountInventory``).
* **Triage** — classifies each inbound institution reply into a typed
  ``TriageResult`` so the Vigil can route it mechanically.

Intake runs as a typed pipeline (structured output at every stage) rather
than free-form conversation: documents → inventory → plan are each Pydantic
models the rest of the system consumes programmatically.
"""

from __future__ import annotations

from strands import Agent
from strands.agent.conversation_manager import SlidingWindowConversationManager

from .audit import AuditHook
from .domain import AccountInventory, IntakeProfile, TaskItem, TaskPlan, TriageResult
from .playbooks import PLAYBOOKS, render_playbook
from .runtime import Runtime
from .simworld import INSTITUTIONS
from .tools import build_advocate_tools, build_case_tools

# ---------------------------------------------------------------------------
# Specialists
# ---------------------------------------------------------------------------


def build_scribe(model, rt: Runtime) -> Agent:
    c = rt.case
    return Agent(
        model=model,
        name="Scribe",
        description="Drafts institution-ready letters and messages for the estate",
        callback_handler=None,
        system_prompt=f"""You are the Scribe for Epilogue, drafting correspondence on behalf of the
estate of {c.deceased.full_name} (date of death: {c.deceased.date_of_death}). The executor and
personal representative is {c.survivor.full_name}, the deceased's {c.survivor.relationship}.

When asked for a draft, return ONLY the finished letter/message body — no commentary.
Rules:
- Formal but human. Institutions respond faster to precise, complete first letters.
- Always identify: the deceased's full name, date of death, the account (masked), and the
  executor's name and capacity, so no round-trip is wasted on identification.
- State exactly what is requested and what is enclosed.
- Anticipate the institution's known requirements (the request will tell you the playbook).
- Never invent account numbers, balances, or facts not given to you.
- One page maximum. Sign as: {c.survivor.full_name}, Personal Representative of the Estate.""",
    )


def build_advocate(model, rt: Runtime) -> Agent:
    return Agent(
        model=model,
        name="Advocate",
        description="Finds money and benefits the family is owed",
        callback_handler=None,
        tools=build_advocate_tools(rt),
        system_prompt="""You are the Advocate for Epilogue. Your job: make sure a grieving family
receives every dollar and benefit they are entitled to. Use your search tool, then report
findings as a short actionable list: what exists, how much, which institution to contact, and
whether it is worth pursuing (do not chase amounts under $20). Be precise; never inflate.""",
    )


def build_sentinel(model, rt: Runtime) -> Agent:
    c = rt.case
    return Agent(
        model=model,
        name="Sentinel",
        description="Assesses fraud and identity-theft signals against the estate",
        callback_handler=None,
        system_prompt=f"""You are the Sentinel for Epilogue, protecting the identity and estate of the
late {c.deceased.full_name}. Identity thieves target the recently deceased ("ghosting") in the
window before credit bureaus are notified. When given a signal (a bureau alert, an unexpected
charge, an application in the deceased's name), assess: is this contained, does it need action,
does it indicate compromise elsewhere? Reply with a short assessment: THREAT LEVEL (contained /
action needed / urgent), what happened in plain language, and concrete next steps if any.""",
    )


def build_triage(model) -> Agent:
    return Agent(
        model=model,
        name="Triage",
        description="Classifies inbound institution correspondence",
        callback_handler=None,
        system_prompt="""You read one piece of inbound correspondence addressed to an estate and
classify it precisely so an autonomous steward can route it. Be literal about what the
institution actually asks for. 'needs_human' is reserved for choices with real consequences —
preferences, money above routine, anything irreversible, signatures only a person can give.""",
    )


# ---------------------------------------------------------------------------
# The Steward
# ---------------------------------------------------------------------------

STEWARD_PROMPT_TEMPLATE = """You are the Steward of Epilogue, an autonomous administrator that settles
the affairs of someone who has died, so their family doesn't have to spend hundreds of hours on
paperwork while grieving. You are working for {survivor_first} ({relationship} of the deceased).
{deceased_name} died on {dod}. Treat every action as if {survivor_first} were watching: precise,
warm, and honest.

HOW YOU WORK
1. Begin each work cycle by reading the matter at hand (get_matter) — and get_case_file if you
   need the wider picture. Consult get_playbook before first contact with any kind of institution;
   playbooks contain the traps (e.g. gyms require WRITTEN letters; joint accounts must not be
   closed; benefits paid for the month of death must be returned).
2. Do the work end to end: draft correspondence (consult_scribe writes institution-ready letters —
   give it the playbook facts and account details), submit it (submit_to_institution), and record
   progress (update_matter with a note). Attach documents thoughtfully: certified death
   certificates are finite; use 'death_certificate_copy' unless certified is explicitly required.
3. You operate on a slow clock. Institutions take days. After you submit, a follow-up is
   auto-scheduled; when a matter comes back to you still unanswered, escalate sensibly: re-send,
   switch channel (portal → letter), or invoke the playbook's escalation step. Silence is never a
   reason to give up — persistence is most of this job.
4. Money owed TO the family matters as much as accounts to close: consult_advocate when the case
   starts and when refunds appear. Open new matters (create_matter) for anything worth pursuing.
5. For fraud or identity signals, consult_sentinel and act on its assessment.
6. When a matter is finished, mark it done with a note that would make sense to {survivor_first}.

THE DECISION GATE — WHEN TO INVOLVE {survivor_first_upper}
{survivor_first} granted you an autonomy contract (in the case file). You NEVER interrupt them for
mechanics: routine cancellations, document submissions, status chasing. You MUST surface a
decision (ask_survivor) when:
  - an action is irreversible or touches memories (photos, messages, profiles, anything sentimental),
  - meaningful money is moved, repaid, or forfeited (the gate enforces the threshold — declare
    moves_money_usd honestly),
  - an institution offers a genuine choice (transfer vs close, keep vs cancel),
  - only a human can act (wet-ink signatures, notarization) — surface it with everything prepared.
Craft decisions kindly: one plain question, short context, 2-3 options with consequences, and your
recommendation. If the Decision Gate blocks you, that is the system working: ask, then stand down.
While a decision is open, never nag and never proceed on that matter.

STYLE
- Notes and decision text are read by a grieving person. Plain words, no jargon, no cheerfulness.
- Never fabricate. If you don't know an account detail, say so in the letter and ask.
- One matter per work cycle: finish your actions on it, then stop.

Today on the case clock: {sim_today}."""


def build_steward(model, rt: Runtime, session_manager=None) -> Agent:
    c = rt.case
    scribe = build_scribe(model, rt)
    advocate = build_advocate(model, rt)
    sentinel = build_sentinel(model, rt)
    specialist_tools = [
        scribe.as_tool(
            name="consult_scribe",
            description=(
                "Ask the Scribe to draft an institution-ready letter or message. Provide: the "
                "institution and its playbook requirements, the account details you know (masked), "
                "what to request, and any documents that will be enclosed. Returns the finished body "
                "text to use with submit_to_institution."
            ),
        ),
        advocate.as_tool(
            name="consult_advocate",
            description=(
                "Ask the Advocate to search for money and benefits the family is owed (unclaimed "
                "property, refunds, employer/veteran benefits). Returns an actionable findings list."
            ),
        ),
        sentinel.as_tool(
            name="consult_sentinel",
            description=(
                "Give the Sentinel a fraud or identity signal (e.g. a credit-bureau alert) and get a "
                "threat assessment with next steps."
            ),
        ),
    ]
    return Agent(
        model=model,
        name="Steward",
        agent_id=f"steward_{c.id}",
        description="Epilogue's orchestrating agent for one family's case",
        system_prompt=STEWARD_PROMPT_TEMPLATE.format(
            survivor_first=c.survivor.full_name.split()[0],
            survivor_first_upper=c.survivor.full_name.split()[0].upper(),
            relationship=c.survivor.relationship,
            deceased_name=c.deceased.full_name,
            dod=c.deceased.date_of_death,
            sim_today=rt.ledger.sim_today().isoformat(),
        ),
        tools=[*build_case_tools(rt), *specialist_tools],
        hooks=[AuditHook(rt.ledger, c.id)],
        conversation_manager=SlidingWindowConversationManager(window_size=40),
        session_manager=session_manager,
        callback_handler=None,
    )


# ---------------------------------------------------------------------------
# Intake pipeline (typed, three stages)
# ---------------------------------------------------------------------------


def read_intake(model, narrative: str) -> IntakeProfile:
    """Stage 1: read the survivor's own words into a typed profile."""
    reader = Agent(
        model=model,
        name="IntakeReader",
        system_prompt=(
            "You read a grieving family member's intake message and extract the facts precisely. "
            "Do not infer facts that are not stated."
        ),
        callback_handler=None,
    )
    result = reader(
        f"Extract the intake profile from this message:\n\n{narrative}",
        structured_output_model=IntakeProfile,
    )
    return result.structured_output


def run_archivist(model, rt: Runtime, documents: str) -> AccountInventory:
    """Stage 2: inventory every account and obligation visible in the documents."""
    archivist = Agent(
        model=model,
        name="Archivist",
        system_prompt=(
            "You are the Archivist for Epilogue. You read a family's uploaded documents — bank and "
            "card statements, mail, notes — and inventory EVERY account, subscription, obligation, "
            "and asset they reveal. Cite one line of evidence per finding. Do not invent accounts; "
            "list uncertainties as open questions instead."
        ),
        callback_handler=None,
    )
    inventory = archivist(
        f"Inventory all accounts and obligations from these documents:\n\n{documents}",
        structured_output_model=AccountInventory,
    ).structured_output
    rt.ledger.record(
        rt.case.id,
        "Archivist",
        "status",
        f"Read the family's documents: found {len(inventory.accounts)} accounts and obligations",
        detail="\n".join(
            f"- {a.institution_name} ({a.institution_kind}): {a.evidence}" for a in inventory.accounts
        ),
    )
    return inventory


def run_planner(model, rt: Runtime, profile: IntakeProfile, inventory: AccountInventory) -> list[TaskItem]:
    """Stage 3: turn the inventory into the matter plan, guided by playbooks."""
    known_institutions = "\n".join(
        f"- {i.id}: {i.name} (kind: {i.kind}) {('— ' + i.notes) if i.notes else ''}"
        for i in INSTITUTIONS.values()
    )
    playbook_digest = "\n\n".join(render_playbook(pb) for pb in PLAYBOOKS.values())
    planner = Agent(
        model=model,
        name="Planner",
        system_prompt=(
            "You are the Planner for Epilogue. Given an account inventory for a deceased person's "
            "estate, produce the complete matter plan: one task per institution/obligation, plus "
            "standard matters the playbooks call for even if no document showed them (credit bureau "
            "deceased alerts at ALL THREE bureaus as separate matters, a benefits/owed-money scan). "
            "Choose categories carefully — anything holding photos/messages/memories is "
            "digital_legacy with risk=irreversible; loyalty points are subscriptions; the benefits "
            "scan is category benefits. Map each matter to a known institution id when one matches. "
            "Estimate minutes saved honestly (playbooks give baselines)."
        ),
        callback_handler=None,
    )
    plan = planner(
        f"""Survivor profile:\n{profile.model_dump_json(indent=2)}\n
Account inventory:\n{inventory.model_dump_json(indent=2)}\n
Known institutions (use these ids):\n{known_institutions}\n
Playbooks:\n{playbook_digest}\n
Produce the complete matter plan.""",
        structured_output_model=TaskPlan,
    ).structured_output
    tasks: list[TaskItem] = []
    for planned in plan.tasks:
        task = TaskItem(
            case_id=rt.case.id,
            title=planned.title,
            category=planned.category,
            institution_id=planned.institution_id or None,
            playbook_id=planned.playbook_id,
            why=planned.why,
            risk=planned.risk,
            estimated_minutes_saved=planned.estimated_minutes_saved,
        )
        rt.ledger.save_task(task)
        tasks.append(task)
    rt.ledger.record(
        rt.case.id,
        "Planner",
        "status",
        f"Planned the road ahead: {len(tasks)} matters to settle",
        detail="\n".join(f"- [{t.category}] {t.title}" for t in tasks),
    )
    return tasks


def triage_mail(model, mail_subject: str, mail_body: str, institution_name: str) -> TriageResult:
    return build_triage(model)(
        f"Correspondence from {institution_name}:\nSubject: {mail_subject}\n\n{mail_body}",
        structured_output_model=TriageResult,
    ).structured_output
