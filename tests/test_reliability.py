import time

import pytest
import test_server as server_tests
from fastapi import HTTPException

from epilogue.budget import Budget

webapp = server_tests.webapp


def wait_finished(client):
    for _ in range(300):
        state = client.get('/api/state').json()
        if state['status'] == 'idle':
            return state
        time.sleep(.01)
    raise AssertionError('Worker did not finish')


def test_bad_input_is_clear_and_does_not_start_work(webapp):
    client, server, _ = webapp
    for body in ({'narrative':' '}, {'narrative':'x'*12001}, {'narrative':'a valid narrative','documents':'x'*80001}):
        result = client.post('/api/case', json=body)
        assert result.status_code == 422
        assert isinstance(result.json()['detail'], str)
    assert server.STATE.status == 'idle'
    for days in (0, 15, '3', 1.5):
        assert client.post('/api/clock/advance', json={'days':days}).status_code == 422


def test_failed_intake_is_durable_and_retryable(webapp, monkeypatch):
    client, server, model = webapp
    original = model.structured['AccountInventory']
    def fail(_):
        raise RuntimeError('Sensitive provider failure sk-proj-should-not-appear')
    model.structured['AccountInventory'] = fail
    seed = client.get('/api/seed').json()
    assert client.post('/api/case',json=seed).status_code == 200
    failed = wait_finished(client)
    assert failed['case'] is not None  # earlier progress is retained
    assert failed['error']
    assert 'Sensitive' not in str(failed['error'])
    assert 'sk-proj' not in str(failed['error'])
    model.structured['AccountInventory'] = original
    assert client.post('/api/retry').status_code == 200
    resumed = wait_finished(client)
    assert resumed['case']['id'] == failed['case']['id']
    assert resumed['error'] is None
    assert len(resumed['tasks']) == 15
    assert len({t['id'] for t in resumed['tasks']}) == 15


def test_work_failure_does_not_erase_case(webapp, monkeypatch):
    client, server, model = webapp
    seed = client.get('/api/seed').json()
    client.post('/api/case', json=seed)
    before = wait_finished(client)
    def fail(*args):
        raise TimeoutError('API timed out')
    monkeypatch.setattr(server.STATE.vigil, 'tick', fail)
    client.post('/api/clock/advance', json={'days':1})
    after = wait_finished(client)
    assert after['case']['id'] == before['case']['id']
    assert after['tasks'] == before['tasks']
    assert 'too long' in after['error']['message']


def test_decision_validation_and_duplicate_resolution(webapp, monkeypatch):
    client, server, _ = webapp
    from epilogue.preview import seed_preview
    monkeypatch.setenv('EPILOGUE_PREVIEW','1')
    seed_preview(server.STATE.ledger)
    decision = next(d for d in client.get('/api/state').json()['decisions'] if d['status'] == 'open')
    path = f"/api/decisions/{decision['id']}/resolve"
    assert client.post(path,json={'option_id':'made_up'}).status_code == 422
    assert server.STATE.ledger.get_decision(decision['id']).status == 'open'
    assert client.post(path,json={'option_id':decision['options'][0]['id']}).status_code == 200
    assert client.post(path,json={'option_id':decision['options'][1]['id']}).status_code == 409


def test_no_cached_private_state_or_cross_origin_posts(webapp):
    client, _, _ = webapp
    assert 'no-store' in client.get('/api/state').headers['cache-control']
    assert client.post('/api/reset',headers={'Origin':'https://attacker.example'}).status_code == 403
    assert client.get('/api/export').headers['content-disposition'].endswith('"epilogue-case.json"')


def test_reset_never_refills_allowance(webapp):
    client, server, _ = webapp
    budget = Budget(server.store(), 'local')
    reservation = budget.reserve(100000)
    budget.settle(reservation, 50000)
    assert client.post('/api/reset').status_code == 200
    assert client.get('/api/state').json()['budget']['remaining_usd'] == 2.95


def test_durable_lock_prevents_overlapping_workers(webapp):
    _, server, _ = webapp
    first = server.STATE
    other = server.AppState()
    first.acquire('working')
    with pytest.raises(HTTPException) as exc:
        other.acquire('working')
    assert exc.value.status_code == 409
    first.finish()
    other.acquire('working')
    other.finish()


def test_auth_is_required_for_all_private_endpoints(webapp, monkeypatch):
    client, server, _ = webapp
    monkeypatch.setenv('EPILOGUE_AUTH_MODE','firebase')
    for path in ('/api/state','/api/mail','/api/export','/api/account','/api/feed'):
        assert client.get(path).status_code == 401
    for path in ('/api/reset','/api/pause','/api/retry'):
        assert client.post(path,headers={'X-Epilogue-Request':'1'}).status_code == 401
        assert client.post(path).status_code == 403
    assert client.get('/api/seed').status_code == 200


def test_health_static_and_legacy_access_code(webapp, monkeypatch):
    client, _, _ = webapp
    assert client.get('/api/health').json()['status'] == 'ok'
    assert client.get('/static/app.js').status_code == 200
    monkeypatch.setenv('EPILOGUE_ACCESS_CODE','private-code')
    assert client.get('/api/meta').json()['access_code_required']
    assert client.post('/api/reset').status_code == 401
    assert client.post('/api/reset',headers={'X-Epilogue-Code':'private-code'}).status_code == 200
