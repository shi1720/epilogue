# Demo video — script & production kit

**Target length:** 4 minutes 30 seconds (hard cap 5:00).
**Format:** slides (open + close) + live screen recording (middle). No camera needed.
**Voiceover:** read the SAY column verbatim — it's paced at ~140 words/min and lands at ~4:25.

## Recording setup (do this first)

1. `epilogue demo` with a real model configured (Bedrock or Anthropic). Browser at `http://127.0.0.1:8000`, window ~1440×900, 100% zoom, bookmarks bar hidden.
2. Do one full **rehearsal run** so you know the rhythm, then `epilogue reset` (or `rm -rf data/`) and restart for the take.
3. Record screen + mic separately if possible; re-record any flubbed line — sentences are short on purpose.
4. Slides: `docs/media/slides.pptx` (Slides 1–3 open the video, 4–6 close it).
5. Timings below assume the model takes 30–60s for intake — the script covers the wait; if your run is faster, breathe and let the feed scroll.

---

## PART 1 — The problem (slides, 0:00–0:50)

**[SLIDE 1: title — "Epilogue. The agent that settles what's left behind."]**

> **SAY:** "This is Epilogue — a project by Shivam Gupta, built on the Strands Agents SDK. It's an agent for the hardest week of ordinary life."

**[SLIDE 2: "420 hours." with the sub-stats]**

> **SAY:** "When someone dies, their family inherits a second job. Researchers estimate it at more than four hundred hours over a year or more. Notify every bank — each wants its own certified documents. Return the final Social-Security-style payment, because benefits for the month of death get clawed back. Cancel a dozen subscriptions that keep billing a dead man's card. There's even a name for what comes next: 'ghosting' — identity thieves specifically target the recently deceased, before the credit bureaus find out."

**[SLIDE 3: "Who it's for" — the sandwich-generation caregiver]**

> **SAY:** "It lands on people like Sarah — grieving, back at work, two states away. The hackathon brief asks for agents that handle repetitive tasks and only surface for real decisions. We asked: where is that pain at its absolute worst? And we built for that."

## PART 2 — Live demo (screen recording, 0:50–3:50)

**[SCREEN: intake page. Click "Use the demo case" — the textareas fill. Scroll them slowly.]**

> **SAY:** "This is the whole onboarding. Sarah writes what happened in her own words, and pastes in the shoebox — her dad's bank statement, his card statement, the mail from the house. Watch what she asks for: 'don't delete anything that can't be undone without asking me.' Remember that line."

**[SCREEN: click "Begin". The live feed starts streaming: Archivist, Planner, then letters going out.]**

> **SAY:** "One click, and Epilogue goes to work — live, right now, on Amazon Bedrock. The Archivist reads every document and inventories fourteen accounts and obligations, with evidence for each. The Planner turns them into a complete plan using institutional playbooks — domain knowledge that knows the traps: gyms only accept written letters; the month-of-death benefit must go back. And without being asked, day one's letters are already going out — the bank, the card, and deceased alerts at all three credit bureaus, because day one is when thieves strike."

**[SCREEN: dashboard loads. Pause on the hero: "Nothing needs you right now, Sarah."]**

> **SAY:** "And this is the product. Not a chat window. A single sentence: nothing needs you right now. Everything else — sixteen matters — is handled."

**[SCREEN: click "+3 days" on the case clock. Mail arrives in the feed; work happens.]**

> **SAY:** "Estate work runs on a slow clock, so for the demo we compress it. Three days pass. The bank replies — it wants a certified death certificate. Epilogue sends one; it's tracking that Sarah only has five. StreamFlix comes back with something no script anticipated: her dad's profiles, his watch history, a list called 'Dad's Westerns'. That's not admin. That's a real decision — so it goes to Sarah."

**[SCREEN: advance again (+3 days / +1 week as rhythm allows). Point at decision cards appearing.]**

> **SAY:** "More time passes, and the inbox fills with only what truly needs her voice. The benefits agency wants eighteen-hundred dollars returned — that's over her threshold, so Epilogue prepared everything and then stopped. This is the Decision Gate: her autonomy contract, enforced in code, inside the tools. Even a confused model cannot move that money or touch those photos — the tool itself refuses."

**[SCREEN: resolve the photos decision ("Export everything"). The agent resumes live in the feed.]**

> **SAY:** "Sarah answers in one tap, and the agent picks the matter back up within seconds — exporting all twenty-two thousand photos before stopping the billing. Nothing irreversible ever happens without her."

**[SCREEN: scroll the timeline — the gym saga; the blocked fraud alert; open the weekly note.]**

> **SAY:** "Scroll the record and you find the texture of the real thing. The gym ignored the online cancellation — so Epilogue chased it, learned written notice was required, sent the letter, and won back the dues charged after death. Here: someone tried to open a credit card in her father's name — declined automatically, because of the alerts placed on day one. And every week, Sarah gets a note in plain language. No dashboards required. It ends: 'there is no hurry.'"

## PART 3 — How & why (slides, 3:50–4:30)

**[SLIDE 4: architecture diagram]**

> **SAY:** "Under the hood: six Strands agents. A Steward orchestrator with specialists mounted as tools. Typed structured output at every stage. Strands hooks feed a full audit trail — trust needs receipts. The agents are stateless; the ledger is the system of record — which is exactly what lets this deploy on Bedrock AgentCore with a scheduler as its heartbeat. And the simulated institutions are deterministic on purpose: what you just watched was the agent's judgment, not a script."

**[SLIDE 5: business case]**

> **SAY:** "Is this real? Three point four million American families face this every year. Companies charging for human-powered versions have raised ninety million dollars. An agentic core does a full case for about the price of a sandwich — distributed through the insurers, employers, and banks that already pay for bereavement support."

**[SLIDE 6: closing — wordmark + repo link]**

> **SAY:** "The hardest week of ordinary life deserves an agent for humans. This is Epilogue. Thank you."

---

## Shot checklist

- [ ] Intake: seed filled, scroll documents, click Begin
- [ ] Live feed during intake (Archivist/Planner lines visible)
- [ ] Hero line "Nothing needs you right now, Sarah"
- [ ] Clock +3 days → bank reply + StreamFlix decision appears
- [ ] Decision Gate moment ($1,847 card) on screen while narrating
- [ ] Resolve photos decision → live resumption in feed
- [ ] Timeline: gym letters + fraud-blocked entry (click "read" on one letter)
- [ ] Weekly note open on screen
- [ ] Slides 1–3 and 4–6

## If the live model stalls on camera

Cut, let the tick finish, resume recording on the next beat — the script's beats are independent. The dashboard state persists (`data/epilogue.db`), so you can also re-record any single beat after the fact.
