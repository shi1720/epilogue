from epilogue.demo_case import SEED_DOCUMENTS
from epilogue.domain import AccountInventory, PlannedTask, TaskItem, TaskPlan
from epilogue.planning import complete_plan
from epilogue.tools import build_case_tools


def test_incomplete_model_plan_cannot_drop_demo_obligations():
    plan = complete_plan(TaskPlan(tasks=[PlannedTask(title='Cancel PixelVault',category='subscriptions',
        institution_id='pixelvault',risk='routine',why='Stop billing')]), AccountInventory(), SEED_DOCUMENTS)
    by_institution = {task.institution_id:task for task in plan.tasks}
    assert {'beacon_mutual','fed_benefits','equifax_sim','experian_sim','transunion_sim'} <= by_institution.keys()
    assert by_institution['pixelvault'].category == 'digital_legacy'
    assert by_institution['pixelvault'].risk == 'irreversible'
    assert len(plan.tasks) == 15
    assert all(task.category == 'identity' for task in plan.tasks[:3])


def test_destination_enforces_photo_gate_even_when_mislabeled(runtime):
    task = TaskItem(case_id=runtime.case.id,title='Ordinary subscription',category='subscriptions',
                    risk='routine',institution_id='pixelvault')
    runtime.ledger.save_task(task)
    submit = next(t for t in build_case_tools(runtime) if t.tool_name == 'submit_to_institution')
    result = submit(task_id=task.id,institution_id='pixelvault',subject='Delete account',body='Close everything')
    assert 'BLOCKED' in result
    assert not runtime.ledger.mail_for_case(runtime.case.id)


def test_invalid_money_amounts_fail_closed(runtime):
    task = TaskItem(case_id=runtime.case.id,title='Bank',category='financial')
    for amount in (-100, float('nan'),float('inf')):
        assert not runtime.gate_check(task, 'payment', amount).allowed
