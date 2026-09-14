# Devpost submission — copy-paste kit

> Everything below is ready to paste into the Devpost submission form.

---

## Project name

**Epilogue — the agent that settles what's left behind**

## Elevator pitch (tagline field)

When someone dies, their family inherits 400+ hours of paperwork at the worst moment of their lives. Epilogue is an autonomous Strands agent that carries it for them — quietly, for months — and only speaks up when something truly needs a human heart.

## Track

**Everyday Agents**

---

## Inspiration

The brief said: *"people lose hours to small, repetitive tasks… the agent runs autonomously and only surfaces when there's a real decision to make."* We asked one question: **where in an ordinary life is that pain at its absolute maximum?**

The answer is the weeks after a death. Empathy's *Cost of Dying* research estimates settling a loved one's affairs takes **420–500 hours over 12–18 months**: notifying banks (each demanding certified documents), returning the final government benefit payment (yes — benefits paid for the month of death are clawed back), cancelling subscriptions that keep billing a dead person's card, a gym that only accepts cancellation by *written letter*, insurance claims, utilities at an empty house, and — grimly — defending the deceased against identity thieves, who target the recently dead so reliably the crime has a name: **ghosting**. The British call this workload *sadmin*. Sad admin.

It is the single most concentrated pile of exactly the busywork this hackathon exists to eliminate — and it lands on people who are grieving. Nobody builds for it, because it isn't glamorous. That's why we did.

## What it does

You tell Epilogue what happened in your own words and paste in the shoebox: statements, mail, notes. Then:

- The **Archivist** inventories every account and obligation your documents reveal, citing evidence for each.
- The **Planner** turns that into a complete matter plan (~16 matters in our demo case) using institutional **playbooks** that know the traps: joint accounts must not be closed; the month-of-death benefit must be returned; gyms ignore their own portals.
- The **Steward** works each matter end to end: the **Scribe** drafts institution-ready letters, documents get attached from a vault (certified death certificates are finite — Epilogue counts them), replies are triaged, silence is chased, channels are switched, escalations happen. For months. On its own clock.
- The **Advocate** finds money the family is *owed* — unclaimed property, prepaid refunds, entitlements — mined from the case's own account inventory. The **Steward** places deceased alerts at all three credit bureaus on day one; the **Sentinel** assesses every fraud signal against the estate.
- And the family? They see a calm dashboard that says: *"2 things need you, Sarah. Everything else is handled."* Decision cards for the genuinely human choices. A weekly plain-language note. A full audit trail with every letter, readable. Nothing else.

## How we built it

**Strands Agents SDK, used deeply, not decoratively:**

- **A cast of eight agent roles**: a Steward orchestrator with Scribe/Advocate/Sentinel specialists mounted via `Agent.as_tool()`, plus a typed intake pipeline (Intake Reader → Archivist → Planner) and a Triage agent — **structured output (Pydantic) at every stage**, so agent output is consumed programmatically, not parsed hopefully.
- **Ten custom `@tool`s** — case file, playbooks, matter ledger, correspondence with attachments, document vault, `ask_survivor`.
- **The Decision Gate**: the survivor grants a per-category **Autonomy Contract** at intake (subscriptions: act freely; money over $500: ask; memories: always ask). Every outward action passes a gate **enforced in plain Python inside the tools** — a confused model *cannot* delete a photo library, and money moves above the threshold are only honored when a survivor decision explicitly authorizes the amount; the tool refuses and instructs the model to surface a decision instead. Prompt persuades; code enforces.
- **Strands hooks** (`BeforeToolCallEvent`/`AfterToolCallEvent`) write every tool call to an audit trail, streamed live to the dashboard over SSE. Trust needs receipts.
- **The Vigil**, a background engine on a *case clock*: delivers due mail, triages replies, resumes matters the survivor unblocked, chases institutions that went silent, and writes the weekly note. The demo compresses weeks into button presses; in production the same tick runs from EventBridge Scheduler into **Amazon Bedrock AgentCore** (entrypoint included in the repo).
- **Model-agnostic** via Strands' provider abstraction: Amazon Bedrock (Claude Sonnet) by default; Anthropic/OpenAI/Ollama with one env var.
- **A deterministic simulated world**: 15 fictional institutions as scripted state machines that faithfully reproduce document demands, non-replies, clawbacks, bereavement policies, and a fraud attempt whose outcome genuinely depends on whether the agent placed the bureau alerts in time. The world is deterministic so the *agent's* judgment is what's being demonstrated — and one clean seam swaps it for real channels (email, print-and-mail APIs, portals) in production.

**Stack**: Python 3.10+, Strands Agents, FastAPI + SSE, SQLite, vanilla-JS dashboard (no build step), pytest with a `ScriptedModel` that drives the real Strands event loop offline (24 tests, <1s).

## Challenges we ran into

- **Autonomy you can trust.** "The prompt says it will ask first" is not a safety property. We moved the autonomy contract into the tools themselves — the gate returns a structured refusal that teaches the model the correct next step (`ask_survivor`, then stand down). Watching the agent hit the gate, ask a beautifully-phrased question, and stand down was the moment the product clicked.
- **Time.** Real estate settlement is weeks of silence punctuated by mail. Agents demos usually run in seconds. We made time a first-class citizen — a persistent case clock, follow-up scheduling, a delivery queue — so the demo honestly shows *months* of background persistence in minutes.
- **Testing an autonomous system without burning tokens.** We implemented the Strands `Model` interface as a deterministic `ScriptedModel` that replays tool calls and structured outputs through the genuine event loop — so CI proves the gate, ledger, world, and hooks behave, offline.
- **Tone.** Every string a survivor sees was written for someone grieving. No jargon, no cheerfulness, no nagging. This took real design time and it shows in the product.

## Accomplishments we're proud of

- A **code-enforced Decision Gate** pattern we think every consumer agent should steal.
- An agent that demonstrably **persists**: chases a stonewalling gym across three rounds and two channels until it wins the refund.
- Catching a simulated **identity-theft attempt** with alerts the agent placed on day one — protection as a feature, not a promise.
- A complete, calm product experience — not a chat window.

## What we learned

Strands' primitives (agents-as-tools, typed structured output, hooks) map remarkably well onto "serious" agent architecture: statelessness with an external system of record, defense-in-depth safety, auditability. And: the most valuable agents may be the ones you almost never talk to.

## What's next

Real-world adapters (secure email, Lob print-mail, institution portals, national death-notification schemes), multi-survivor cases, attorney/fiduciary review mode, and the same architecture applied to adjacent "paperwork avalanche" transitions: divorce, dementia diagnosis, immigration. Distribution is B2B2C — life insurers, employers, banks, and funeral homes already pay for human-powered versions of exactly this (Empathy has raised $90M; Settld operates in the UK). An agentic core drives marginal cost per case toward the price of tokens (~$5–12 on Bedrock per full case, against 400+ hours of family time).

---

## Built with (Devpost field)

`python` · `strands-agents` · `amazon-bedrock` · `claude` · `bedrock-agentcore` · `fastapi` · `sqlite` · `server-sent-events` · `pydantic` · `github-actions`

## Try it (testing instructions for judges)

```bash
git clone https://github.com/shi1720/afh-aws.git && cd afh-aws
python -m venv .venv && source .venv/bin/activate && pip install -e .
# Bedrock (default): AWS creds with Claude Sonnet access; or:
#   EPILOGUE_MODEL_PROVIDER=anthropic + ANTHROPIC_API_KEY (pip install -e ".[anthropic]")
epilogue demo    # → http://127.0.0.1:8000  → "Use the demo case" → Begin
```

Offline options: `pytest` (24 tests, no credentials) and a seeded UI preview (`python scripts/preview_state.py` — see README).
