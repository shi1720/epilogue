"""The Decision Gate: code-enforced autonomy, independent of the model."""

from epilogue.domain import Decision, DecisionOption, TaskItem
from epilogue.tools import build_case_tools


def _tool(tools, name):
    return {t.tool_name: t for t in tools}[name]


def test_gate_blocks_irreversible_without_decision(runtime):
    t = TaskItem(
        case_id=runtime.case.id,
        title="Photo library",
        category="digital_legacy",
        institution_id="pixelvault",
        risk="irreversible",
    )
    runtime.ledger.save_task(t)
    gate = runtime.gate_check(t, "close the account")
    assert not gate.allowed
    assert "ask_survivor" in gate.reason


def test_gate_blocks_large_money_moves(runtime):
    t = TaskItem(case_id=runtime.case.id, title="Repay benefit", category="government", risk="careful")
    runtime.ledger.save_task(t)
    assert runtime.gate_check(t, "repay", moves_money_usd=1847.0).allowed is False
    assert runtime.gate_check(t, "small fee", moves_money_usd=20.0).allowed is True


def test_money_moves_need_an_explicit_amount_authorization(runtime):
    """A resolved decision about something else must NOT authorize money moves —
    only a decision that explicitly authorizes at least the amount does."""
    t = TaskItem(case_id=runtime.case.id, title="Repay benefit", category="government", risk="careful")
    runtime.ledger.save_task(t)
    d = Decision(
        case_id=runtime.case.id, task_id=t.id, question="Proceed with the paperwork?", context="…",
        options=[DecisionOption(id="yes", label="Yes", consequence="…")],
        status="resolved", resolution_option_id="yes",
    )
    runtime.ledger.save_decision(d)
    assert runtime.gate_check(t, "repay", moves_money_usd=1847.0).allowed is False

    d2 = Decision(
        case_id=runtime.case.id, task_id=t.id, question="Repay $1,847 from the estate account?",
        context="…", options=[DecisionOption(id="repay", label="Repay it", consequence="Closes the matter")],
        status="resolved", resolution_option_id="repay", authorizes_amount_usd=1847.0,
    )
    runtime.ledger.save_decision(d2)
    assert runtime.gate_check(t, "repay", moves_money_usd=1847.0).allowed is True
    # …but not more than what was authorized.
    assert runtime.gate_check(t, "repay more", moves_money_usd=5000.0).allowed is False


def test_gate_opens_after_survivor_decides(runtime):
    t = TaskItem(
        case_id=runtime.case.id,
        title="Photo library",
        category="digital_legacy",
        institution_id="pixelvault",
        risk="irreversible",
    )
    runtime.ledger.save_task(t)
    d = Decision(
        case_id=runtime.case.id,
        task_id=t.id,
        question="Export first?",
        context="…",
        options=[DecisionOption(id="export", label="Export", consequence="Safe")],
        status="resolved",
        resolution_option_id="export",
    )
    runtime.ledger.save_decision(d)
    assert runtime.gate_check(t, "export then downgrade").allowed is True


def test_submit_tool_enforces_gate_and_instructs_model(runtime):
    tools = build_case_tools(runtime)
    t = TaskItem(
        case_id=runtime.case.id,
        title="Photo library",
        category="digital_legacy",
        institution_id="pixelvault",
        risk="irreversible",
    )
    runtime.ledger.save_task(t)
    out = _tool(tools, "submit_to_institution")(
        task_id=t.id,
        institution_id="pixelvault",
        subject="Close account",
        body="Please close it.",
    )
    assert "BLOCKED BY DECISION GATE" in out
    # No outbound mail was created; the world never heard about it.
    assert runtime.ledger.mail_for_case(runtime.case.id) == []
    # And the matter now shows as needing the survivor.
    assert runtime.ledger.get_task(t.id).status.value == "needs_decision"


def test_ask_survivor_creates_decision_and_dedupes(runtime):
    tools = build_case_tools(runtime)
    t = TaskItem(case_id=runtime.case.id, title="Utility choice", category="utilities")
    runtime.ledger.save_task(t)
    ask = _tool(tools, "ask_survivor")
    out = ask(
        task_id=t.id,
        question="Keep the power on at the house?",
        context="The house is empty until it sells in spring.",
        options=[
            {"id": "keep", "label": "Keep it on", "consequence": "~$60/mo, pipes protected"},
            {"id": "close", "label": "Shut it off", "consequence": "Saves money, risks the house"},
        ],
        recommendation="keep",
        urgency="this_week",
    )
    assert "inbox" in out
    dup = ask(
        task_id=t.id, question="Again?", context="…", options=[{"id": "a", "label": "A", "consequence": "c"}]
    )
    assert "already open" in dup
    assert len(runtime.ledger.decisions_for_case(runtime.case.id, status="open")) == 1


def test_certified_copies_are_finite(runtime):
    tools = build_case_tools(runtime)
    t = TaskItem(
        case_id=runtime.case.id, title="Bank", category="financial", institution_id="first_harbor_bank"
    )
    runtime.ledger.save_task(t)
    submit = _tool(tools, "submit_to_institution")
    for _ in range(5):
        out = submit(
            task_id=t.id,
            institution_id="first_harbor_bank",
            subject="Docs",
            body="Enclosed.",
            attachments=["certified_death_certificate"],
        )
        assert "Delivered" in out
    out = submit(
        task_id=t.id,
        institution_id="first_harbor_bank",
        subject="Docs",
        body="Enclosed.",
        attachments=["certified_death_certificate"],
    )
    assert "Not enough" in out and "nothing was sent" in out


def test_failed_submissions_never_burn_certified_copies(runtime):
    """A typo'd institution or unknown document must not consume finite documents."""
    tools = build_case_tools(runtime)
    t = TaskItem(case_id=runtime.case.id, title="Bank", category="financial", institution_id="first_harbor_bank")
    runtime.ledger.save_task(t)
    submit = _tool(tools, "submit_to_institution")

    out = submit(
        task_id=t.id, institution_id="bank_of_narnia", subject="Docs", body="Enclosed.",
        attachments=["certified_death_certificate"],
    )
    assert "Unknown institution" in out
    assert runtime.vault_status()["certified_death_certificate"] == 5

    out = submit(
        task_id=t.id, institution_id="first_harbor_bank", subject="Docs", body="Enclosed.",
        attachments=["certified_death_certificate", "no_such_document"],
    )
    assert "Unknown document" in out
    assert runtime.vault_status()["certified_death_certificate"] == 5
