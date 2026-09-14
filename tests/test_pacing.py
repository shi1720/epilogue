"""PacedModel: spacing, retry-on-transient, no retry after output."""

import asyncio
import time

import pytest

from epilogue.pacing import PacedModel


class FlakyModel:
    """Fails transiently N times, then streams two events."""

    def __init__(self, failures: int = 0, error: str = "429 rate limit, retry in 0.01s") -> None:
        self.failures = failures
        self.error = error
        self.calls = 0

    def get_config(self):
        return {"model_id": "flaky"}

    def update_config(self, **kw):
        pass

    async def stream(self, *a, **k):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError(self.error)
        yield {"messageStart": {"role": "assistant"}}
        yield {"messageStop": {"stopReason": "end_turn"}}

    async def structured_output(self, *a, **k):
        yield {"output": None}


async def _drain(gen):
    return [e async for e in gen]


def test_calls_are_spaced_by_the_interval():
    inner = FlakyModel()
    paced = PacedModel(inner, min_interval_seconds=0.15)
    start = time.monotonic()
    asyncio.run(_drain(paced.stream()))
    asyncio.run(_drain(paced.stream()))
    asyncio.run(_drain(paced.stream()))
    elapsed = time.monotonic() - start
    assert elapsed >= 0.30  # three calls, two enforced gaps


def test_transient_errors_are_retried_with_provider_hint():
    inner = FlakyModel(failures=2)
    paced = PacedModel(inner, min_interval_seconds=0.0)
    events = asyncio.run(_drain(paced.stream()))
    assert inner.calls == 3 and len(events) == 2


def test_real_errors_raise_immediately():
    inner = FlakyModel(failures=1, error="invalid api key")
    paced = PacedModel(inner, min_interval_seconds=0.0)
    with pytest.raises(RuntimeError, match="invalid api key"):
        asyncio.run(_drain(paced.stream()))
    assert inner.calls == 1
