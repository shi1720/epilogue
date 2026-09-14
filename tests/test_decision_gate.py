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
        context="…",
        options=[DecisionOption(id="repay", label="Repay it", consequence="Closes the matter", authorizes=True)],
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
        options=[
            DecisionOption(id="export", label="Export", consequence="Safe", authorizes=True),
            DecisionOption(id="hold", label="Not yet", consequence="Wait"),
        ],
        status="resolved",
        resolution_option_id="export",
    )
    runtime.ledger.save_decision(d)
    assert runtime.gate_check(t, "export then downgrade").allowed is True


def test_a_no_keeps_the_gate_shut(runtime):
    """A resolved decision is not an authorization: choosing 'hold' must leave
    the gate closed — the exact failure mode the product exists to prevent."""
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
        options=[
            DecisionOption(id="export", label="Export", consequence="Safe", authorizes=True),
            DecisionOption(id="hold", label="Hold — let me think", consequence="Nothing changes"),
        ],
        status="resolved",
        resolution_option_id="hold",
    )
    runtime.ledger.save_decision(d)
    gate = runtime.gate_check(t, "export then downgrade")
    assert gate.allowed is False
    assert "honor it" in gate.reason


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
    # With no decision on file the matter is NOT parked as needs_decision —
    # the Vigil keeps driving it until the Steward asks properly (no dead-ends).
    assert runtime.ledger.get_task(t.id).status.value == "pending"


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
            {"id": "keep", "label": "Keep it on", "consequence": "~$60/mo, pipes protected", "authorizes": True},
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


def test_bureaus_preserve_certified_originals(runtime):
    task = TaskItem(case_id=runtime.case.id, title="Credit alert", category="identity",
                    institution_id="equifax_sim")
    runtime.ledger.save_task(task)
    submit = _tool(build_case_tools(runtime), "submit_to_institution")
    result = submit(task_id=task.id, institution_id="equifax_sim", subject="Deceased alert",
                    body="Please place the alert.", attachments=["certified_death_certificate"])
    assert "Nothing was sent" in result
    assert runtime.vault_status()["certified_death_certificate"] == 5
    assert runtime.ledger.mail_for_case(runtime.case.id) == []
    result = submit(task_id=task.id, institution_id="equifax_sim", subject="Deceased alert",
                    body="Please place the alert.", attachments=["death_certificate_copy"])
    assert "Delivered" in result
    assert runtime.vault_status()["certified_death_certificate"] == 5


def test_repayment_requires_explicit_amount_and_survivor_approval(runtime):
    task = TaskItem(case_id=runtime.case.id, title="Benefit repayment", category="government",
                    institution_id="fed_benefits")
    runtime.ledger.save_task(task)
    runtime.world.set_stage('fed_benefits', task.id, 'await_repayment')
    submit = _tool(build_case_tools(runtime), 'submit_to_institution')
    args = dict(task_id=task.id, institution_id='fed_benefits', subject='Repayment of $1,847',
                body='Please provide instructions to repay the $1,847 returned benefit.')
    submit(**args)
    assert runtime.world.get_stage('fed_benefits', task.id) == 'await_repayment'
    assert 'BLOCKED' in submit(**args, moves_money_usd=1847)
    assert runtime.world.get_stage('fed_benefits', task.id) == 'await_repayment'
    runtime.ledger.save_decision(Decision(
        case_id=runtime.case.id, task_id=task.id, question='Repay $1,847?', context='Return overpayment',
        options=[DecisionOption(id='repay', label='Repay', consequence='Return funds', authorizes=True)],
        status='resolved', resolution_option_id='repay', authorizes_amount_usd=1847))
    assert 'Delivered' in submit(**args, moves_money_usd=1847)
    assert runtime.world.get_stage('fed_benefits', task.id) == 'done'


def test_unmapped_matters_cannot_send_to_an_unrelated_institution(runtime):
    task = TaskItem(case_id=runtime.case.id, title='An unsupported provider', category='financial')
    runtime.ledger.save_task(task)
    submit = _tool(build_case_tools(runtime), 'submit_to_institution')
    result = submit(task_id=task.id, institution_id='daily_ledger_news', subject='Request details',
                    body='Please provide the account information.', attachments=['certified_death_certificate'])
    assert 'Nothing was sent' in result
    assert runtime.ledger.mail_for_case(runtime.case.id) == []
    assert runtime.vault_status()['certified_death_certificate'] == 5


def test_followup_institution_omissions_and_duplicate_titles_are_repaired(runtime):
    tools = build_case_tools(runtime)
    create = _tool(tools, 'create_matter')
    create(title='Request PixelVault refund', category='benefits')
    task = runtime.ledger.tasks_for_case(runtime.case.id)[0]
    assert task.institution_id == 'pixelvault'
    assert task.risk == 'irreversible'
    assert task.category == 'digital_legacy'
    result = create(title='Request PixelVault refund!', category='benefits')
    assert task.id in result
    assert len(runtime.ledger.tasks_for_case(runtime.case.id)) == 1


def test_existing_named_matter_gets_correct_channel_without_bypassing_gate(runtime):
    task = TaskItem(case_id=runtime.case.id, title='Request PixelVault refund', category='benefits')
    runtime.ledger.save_task(task)
    submit = _tool(build_case_tools(runtime), 'submit_to_institution')
    result = submit(task_id=task.id, institution_id='pixelvault', subject='Refund request', body='Please refund.')
    assert 'BLOCKED' in result
    assert runtime.ledger.get_task(task.id).institution_id == 'pixelvault'
    assert runtime.ledger.mail_for_case(runtime.case.id) == []
