"""Exercise account boundaries and reconstruction through the record-store contract."""
import copy

import pytest
import test_server as server_tests
from fastapi import Request

from epilogue.budget import Budget
from epilogue.domain import Decision, DecisionOption, TaskItem
from epilogue.ledger import Ledger

webapp = server_tests.webapp


class Records:
    def __init__(self):
        self.rows = {}
        self.fail = False

    def all(self):
        return copy.deepcopy(list(self.rows.values()))

    def put(self, table, key, row):
        if self.fail:
            raise ConnectionError('record store unavailable')
        self.rows[table, key] = {'table': table, 'row': copy.deepcopy(row)}


def test_failed_remote_save_is_not_acknowledged_locally(case):
    records = Records()
    ledger = Ledger(':memory:', records=records)
    ledger.save_case(case)
    task = TaskItem(case_id=case.id, title='Saved task', category='financial')
    ledger.save_task(task)
    task.title = 'An uncommitted change'
    records.fail = True
    with pytest.raises(ConnectionError):
        ledger.save_task(task)
    assert ledger.get_task(task.id).title == 'Saved task'
    assert Ledger(':memory:', records=records).get_task(task.id).title == 'Saved task'


def test_private_accounts_survive_context_reload_and_reset(webapp, monkeypatch, case):
    client, server, _ = webapp
    records = {}
    monkeypatch.setattr(server.store(), 'records',
                        lambda uid, generation: records.setdefault((uid, generation), Records()), raising=False)
    monkeypatch.setattr(server, 'hosted', lambda: True)
    def signed_in(request: Request):
        return {'uid': request.headers.get('x-test-user', 'alice'), 'name': 'Test account'}
    server.app.dependency_overrides[server.identity] = signed_in
    alice = {'X-Test-User': 'alice', 'X-Epilogue-Request': '1'}
    bob = {'X-Test-User': 'bob', 'X-Epilogue-Request': '1'}
    assert client.get('/api/state', headers=alice).json()['case'] is None
    ctx = server.CONTEXTS[server.account_key('alice')]
    ctx.ledger.save_case(case)
    ctx.ledger.kv_set('intake_planned', 'true')
    task = TaskItem(case_id=case.id, title='Private matter', category='financial')
    ctx.ledger.save_task(task)
    decision = Decision(case_id=case.id, task_id=task.id, question='Private choice?', context='Private context',
                        options=[DecisionOption(id='yes', label='Proceed', consequence='Continue')])
    ctx.ledger.save_decision(decision)
    budget = Budget(server.store(), ctx.uid)
    reservation = budget.reserve(100000)
    budget.settle(reservation, 40000)
    server.CONTEXTS.clear()  # simulate a new process loading the durable records
    restored = client.get('/api/state', headers=alice).json()
    assert restored['case']['id'] == case.id
    assert restored['tasks'][0]['title'] == 'Private matter'
    assert restored['budget']['spent_usd'] == .04
    assert client.get('/api/state', headers=bob).json()['case'] is None
    assert client.get('/api/mail', headers=bob).json()['mail'] == []
    assert client.get('/api/export', headers=bob).json()['case'] is None
    assert client.post(f'/api/decisions/{decision.id}/resolve', json={'option_id':'yes'}, headers=bob).status_code == 404
    assert client.post('/api/reset', headers=bob).status_code == 200
    assert client.get('/api/state', headers=alice).json()['case']['id'] == case.id
    assert client.post('/api/reset', headers=alice).status_code == 200
    server.CONTEXTS.clear()
    reset = client.get('/api/state', headers=alice).json()
    assert reset['case'] is None
    assert reset['budget']['remaining_usd'] == 2.96
    # Replacing a case does not erase the old generation's durable records.
    assert records[server.account_key('alice'), 'initial'].all()
    server.app.dependency_overrides.clear()
