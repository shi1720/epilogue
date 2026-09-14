"""PacedModel — run any Strands model within a provider's rate budget.

Free-tier keys (Gemini's is 5 requests/minute) are a lovely way to try
Epilogue at zero cost, but an agent can spend that budget in seconds.
PacedModel wraps any ``strands.models.Model`` and:

1. reserves send slots on a token-bucket schedule (a minimum interval
   between calls, shared across every agent in the process), and
2. when the provider still answers 429/503, sleeps out the provider's own
   ``retry in Ns`` hint and tries again — as long as no tokens have been
   streamed yet, so a retry can never duplicate output.

Epilogue already lives on a slow clock; with pacing it also budgets itself,
which is exactly the discipline you want from an autonomous system that
someone else is paying for.
"""

from __future__ import annotations

import asyncio
import re
import threading
import time
from typing import Any

from strands.models.model import Model

_TRANSIENT = ("429", "503", "unavailable", "throttl", "overload", "resource_exhausted", "resource exhausted")
_RETRY_HINT = re.compile(r"retry in ([0-9.]+)\s*s", re.IGNORECASE)


def _is_transient(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _TRANSIENT)


def _suggested_delay(exc: Exception, fallback: float) -> float:
    match = _RETRY_HINT.search(str(exc))
    return min(float(match.group(1)) + 1.0, 120.0) if match else fallback


class PacedModel(Model):
    """Wrap a model so all calls in the process share one rate budget."""

    def __init__(self, inner: Model, min_interval_seconds: float, max_retries: int = 8) -> None:
        self.inner = inner
        self.interval = min_interval_seconds
        self.max_retries = max_retries
        self._lock = threading.Lock()
        self._next_slot = 0.0

    async def _wait_turn(self) -> None:
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next_slot)
            self._next_slot = slot + self.interval
        wait = slot - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)

    # -- Model interface ---------------------------------------------------

    def get_config(self) -> Any:
        return self.inner.get_config()

    def update_config(self, **model_config: Any) -> None:
        self.inner.update_config(**model_config)

    async def stream(self, *args: Any, **kwargs: Any):
        attempt = 0
        while True:
            await self._wait_turn()
            started = False
            try:
                async for event in self.inner.stream(*args, **kwargs):
                    started = True
                    yield event
                return
            except Exception as exc:  # noqa: BLE001
                # Never retry once output has streamed (it would duplicate),
                # and never swallow a real error.
                if started or not _is_transient(exc) or attempt >= self.max_retries:
                    raise
                attempt += 1
                await asyncio.sleep(_suggested_delay(exc, fallback=min(10.0 * attempt, 60.0)))

    async def structured_output(self, *args: Any, **kwargs: Any):
        attempt = 0
        while True:
            await self._wait_turn()
            emitted = False
            try:
                async for event in self.inner.structured_output(*args, **kwargs):
                    emitted = True
                    yield event
                return
            except Exception as exc:  # noqa: BLE001
                if emitted or not _is_transient(exc) or attempt >= self.max_retries:
                    raise
                attempt += 1
                await asyncio.sleep(_suggested_delay(exc, fallback=min(10.0 * attempt, 60.0)))
