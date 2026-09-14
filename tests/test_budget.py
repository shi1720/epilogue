from concurrent.futures import ThreadPoolExecutor

import pytest
from strands.models.model import Model

from epilogue.budget import Budget, BudgetExceeded, BudgetModel, RunPaused
from epilogue.storage import LocalStore


@pytest.fixture()
def store(tmp_path):
    return LocalStore(tmp_path / 'accounts.db')


def test_concurrent_reservations_never_exceed_allowance(store):
    budget = Budget(store, 'alice')
    def reserve(_):
        try:
            return budget.reserve(200_000)
        except BudgetExceeded:
            return None
    with ThreadPoolExecutor(max_workers=12) as pool:
        ids = [r for r in pool.map(reserve, range(40)) if r]
    assert len(ids) == 15
    assert budget.summary()['remaining_usd'] == 0
    for token in ids:
        budget.settle(token, 10_000)
        budget.settle(token, 10_000)
    assert budget.summary()['spent_usd'] == .15
    assert budget.summary()['requests'] == 15


def test_accounts_are_separate_but_host_limit_is_shared(store, monkeypatch):
    monkeypatch.setenv('EPILOGUE_GLOBAL_BUDGET_USD', '0.1')
    alice, bob = Budget(store, 'alice'), Budget(store, 'bob')
    token = alice.reserve(90_000)
    assert bob.summary()['remaining_usd'] == 3
    with pytest.raises(BudgetExceeded, match='host'):
        bob.reserve(20_000)
    alice.settle(token, 10_000)
    bob.reserve(20_000)


def test_reservations_survive_process_restart(tmp_path):
    path = tmp_path / 'persistent.db'
    first = Budget(LocalStore(path), 'alice')
    reservation = first.reserve(75_000)
    second = Budget(LocalStore(path), 'alice')
    assert second.summary()['reserved_usd'] == .075
    second.settle(reservation)  # uncertain usage is conservatively charged
    assert second.summary()['spent_usd'] == .075


class UsageModel(Model):
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail
    def get_config(self):
        return {'model_id':'gpt-4.1-mini'}
    def update_config(self, **kwargs):
        pass
    async def stream(self, *args, **kwargs):
        self.calls += 1
        if self.fail:
            raise ConnectionError('Connection dropped')
        yield {'metadata': {'usage': {'inputTokens':1000, 'cacheReadInputTokens':500, 'outputTokens':200}}}
    async def structured_output(self, *args, **kwargs):
        yield {}


@pytest.mark.asyncio
async def test_all_token_types_are_reconciled(store):
    budget = Budget(store, 'alice')
    model = BudgetModel(UsageModel(), budget)
    events = [e async for e in model.stream([{'role':'user','content':[{'text':'hello'}]}])]
    assert events
    assert budget.summary()['spent_usd'] == .000570
    assert budget.summary()['reserved_usd'] == 0
    assert budget.summary()['input_tokens'] == 1000
    assert budget.summary()['output_tokens'] == 200


@pytest.mark.asyncio
async def test_network_failure_keeps_conservative_charge(store):
    budget = Budget(store, 'alice')
    model = BudgetModel(UsageModel(fail=True), budget)
    with pytest.raises(ConnectionError):
        _ = [e async for e in model.stream([])]
    assert budget.summary()['spent_usd'] > 0
    assert budget.summary()['reserved_usd'] == 0


@pytest.mark.asyncio
async def test_no_model_call_after_budget_or_pause(store):
    budget = Budget(store, 'alice')
    inner = UsageModel()
    budget.reserve(3_000_000)
    with pytest.raises(BudgetExceeded):
        _ = [e async for e in BudgetModel(inner, budget).stream([])]
    with pytest.raises(RunPaused):
        _ = [e async for e in BudgetModel(inner, budget, lambda: True).stream([])]
    assert inner.calls == 0
