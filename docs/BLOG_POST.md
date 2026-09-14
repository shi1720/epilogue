# builder.aws.com post — ready to publish

> **Title (includes "Agents for Humans" as required):**
> **Agents for Humans: I built an agent for the hardest week of ordinary life — with Strands Agents and Amazon Bedrock**
>
> Suggested tags: `strands-agents`, `amazon-bedrock`, `generative-ai`, `agents`, `python`

---

When AWS announced the *Agents for Humans* hackathon, the brief was disarmingly simple: people lose hours to small repetitive tasks — build an agent that handles them in the background and only surfaces for real decisions.

Most of the obvious candidates (inbox triage, travel planning, meeting scheduling) have been built a hundred times. So I asked a different question: **where in an ordinary human life does "repetitive tasks" reach its absolute maximum?**

The answer changed the project. When someone dies, their family inherits an estimated **420–500 hours of administration** (Empathy's *Cost of Dying* research) over the following year: notifying every bank (each demanding certified documents), returning the final benefits payment (benefits for the month of death are clawed back — most families learn this the hard way), cancelling subscriptions that keep billing a dead person's card, coaxing a gym into honoring its own cancellation policy, filing insurance claims, keeping the lights on at an empty house. Meanwhile, identity thieves target the recently deceased so consistently that the crime has a name — *ghosting* — with hundreds of thousands of victims a year.

The British call this workload *sadmin*. It lands, in full, on people who are grieving.

So I built **Epilogue**: an autonomous agent that settles what's left behind. This post is the build story — what worked, what surprised me, and the patterns I'd reuse. The code is open source (MIT): **github.com/shi1720/afh-aws**.

## What Epilogue does

A survivor writes what happened in their own words and pastes in the "shoebox" — statements, mail, notes. From there:

1. An **Archivist** agent inventories every account and obligation the documents reveal, with cited evidence.
2. A **Planner** agent crosses that inventory with a library of **institutional playbooks** (the procedural knowledge of estate settlement: what each kind of institution will demand, how long it takes, where the traps are) and produces a complete matter plan.
3. A **Steward** agent then works those matters for weeks: drafting letters through a **Scribe** specialist, submitting them with the right documents attached, triaging replies, chasing silence, escalating channels. An **Advocate** hunts for money the family is *owed*; a **Sentinel** watches for fraud.
4. The family sees a calm dashboard whose ideal state is one sentence: *"Nothing needs you right now."* Real decisions arrive as cards; everything else becomes a weekly note.

## Strands patterns I'd use again

### 1. Agents-as-tools for real hierarchy

Strands made the orchestrator/specialist split almost free:

```python
scribe.as_tool(
    name="consult_scribe",
    description="Ask the Scribe to draft an institution-ready letter…",
)
```

The Steward stays focused on judgment and sequencing; specialists carry narrow expertise and their own system prompts. The tool descriptions became the API contract between agents.

### 2. Typed structured output everywhere the system consumes agent output

Anywhere an agent's output feeds *code* rather than a human, I used Strands structured output with Pydantic models:

```python
result = archivist(documents, structured_output_model=AccountInventory)
inventory = result.structured_output   # a real AccountInventory, not hopeful regex
```

Intake narrative → `IntakeProfile`; documents → `AccountInventory`; inventory → `TaskPlan`; every inbound institution reply → `TriageResult` (which lets the background engine route "resolved" replies mechanically — zero extra model calls on quiet news).

### 3. A Decision Gate: autonomy enforced in code, not prompt

This is the pattern I most want other builders to steal. Every consumer-agent demo claims "human in the loop." Epilogue makes it a *contract*: at intake the survivor grants per-category autonomy (subscriptions: act freely · money over $500: ask first · anything touching memories: always ask). Then every outward-facing tool checks the gate in plain Python:

```python
gate = runtime.gate_check(task, action, moves_money_usd)
if not gate.allowed:
    return ("BLOCKED BY DECISION GATE: … Use the ask_survivor tool to "
            "surface a decision, then stand down.")
```

The refusal is *instructional* — it teaches the model the correct next move. The system prompt asks the Steward to be careful; the gate **makes** it careful. Watching the agent hit the gate on a photo-library closure, compose a genuinely kind question ("Before anything changes: should I export all 22,384 of your dad's photos first?"), and stand down — that was the moment this stopped being a tech demo.

### 4. Hooks as a trust layer

A Strands `HookProvider` subscribed to `BeforeToolCallEvent`/`AfterToolCallEvent` writes every tool invocation to an audit table, which streams to the dashboard live over SSE and persists forever. Families are being asked to trust an autonomous system with their parent's affairs; trust needs receipts. Fifteen lines of hook code bought the whole transparency story.

### 5. Stateless agents over a durable ledger

Between work cycles, the agents remember *nothing*. All state — matters, notes, correspondence, decisions, even the case clock — lives in a SQLite ledger. Any Steward instance can pick up any case at any time. This is what made the AgentCore deployment story trivial: the runtime is stateless compute; EventBridge Scheduler is the heartbeat; the ledger is the system of record.

### 6. Test the loop, not the model

I implemented Strands' `Model` interface as a deterministic `ScriptedModel` that replays tool calls and structured outputs through the **real** event loop. The CI suite (24 tests, under a second, zero credentials) proves the gate blocks, the vault decrements certified copies, the world's gym ignores portal cancellations, and a full matter lifecycle settles. The live model then only has to supply judgment — the machine around it is already proven.

## The part nobody warns you about: time

Estate settlement is weeks of silence punctuated by mail. Agent demos run in seconds. Reconciling those was the most interesting engineering problem in the project: Epilogue runs on a persistent **case clock**, with follow-up scheduling ("the bank typically answers in 7 days; chase on day 10"), a delivery queue for the simulated world, and a background engine — the **Vigil** — that does *literally nothing* on a quiet day. No model calls. A grieving family shouldn't pay for idle intelligence, and an agent that knows when to do nothing is rarer than one that can do everything.

For the demo, the clock compresses: a button press advances days and you watch weeks of persistence — including a three-round fight with a gym that "loses" portal cancellations until it receives a written letter — in about a minute.

## Costs

A full case — intake, ~16 matters, ~8 weeks of simulated correspondence — lands around 1–2M tokens: **roughly $5–12 on Claude Sonnet via Amazon Bedrock**, against 400+ hours of a family's time. The frugality is architectural: typed triage keeps routine mail cheap, mechanical routing skips the model entirely when nothing needs judgment, and quiet days are free.

## What I'd build next

Real-world adapters behind the same seam the simulator uses (secure email, print-and-mail APIs, institution portals, national death-notification schemes), a fiduciary review mode for attorneys, and the same architecture — inventory, playbooks, quiet persistence, decision gate — pointed at the other paperwork avalanches: divorce, dementia diagnosis, immigration.

The hardest week of ordinary life deserves an agent for humans.

*Epilogue was built by Shivam Gupta for the AWS Agents for Humans hackathon (Everyday Agents track), on the Strands Agents SDK and Amazon Bedrock. Code, tests, demo, and an AgentCore entrypoint: github.com/shi1720/afh-aws — MIT licensed. The demo case and all institutions in it are fictional.*
