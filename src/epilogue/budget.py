"""Reserve credit before every model request, then reconcile reported token usage.

Money is represented in integer microdollars. Reservations survive worker
crashes; an interrupted response without usage remains conservatively charged.
The hosted demo only enables explicitly priced OpenAI models, and SDK retries
are disabled so each paid request passes through the reservation gate.
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
import uuid
from typing import Any

from strands.models.model import Model

# USD / million tokens, which is also microdollars / token.
PRICES = {"gpt-4.1-mini": (0.4, 0.1, 1.6), "gpt-4.1-mini-2025-04-14": (0.4, 0.1, 1.6)}


class BudgetExceeded(Exception):
    pass


class RunPaused(Exception):
    pass


class Budget:
    def __init__(self, store, uid):
        self.store, self.uid = store, uid
        self.limit = round(float(os.environ.get("EPILOGUE_ACCOUNT_BUDGET_USD", "3")) * 1_000_000)
        self.global_limit = round(float(os.environ.get("EPILOGUE_GLOBAL_BUDGET_USD", "30")) * 1_000_000)

    def summary(self):
        row = self.store.get(self.uid)
        spent = row.get("spent", 0)
        held = sum(row.get("reservations", {}).values())
        return {"limit_usd": self.limit / 1e6, "spent_usd": spent / 1e6,
                "reserved_usd": held / 1e6, "remaining_usd": max(0, self.limit - spent - held) / 1e6,
                "requests": row.get("requests", 0), "input_tokens": row.get("input_tokens", 0),
                "output_tokens": row.get("output_tokens", 0)}

    def reserve(self, amount):
        reservation = uuid.uuid4().hex

        def apply(rows):
            account, total = rows
            for row, limit, message in (
                (account, self.limit, "Your test allowance is used up. Your case and correspondence are still available."),
                (total, self.global_limit, "The shared demo has reached its host's spending limit. Your work is saved."),
            ):
                used = row.get("spent", 0) + sum(row.get("reservations", {}).values())
                if used + amount > limit:
                    raise BudgetExceeded(message)
            for row in rows:
                row.setdefault("reservations", {})[reservation] = amount
            return reservation

        return self.store.transact([self.uid, "__budget_total"], apply)

    def settle(self, reservation, cost=None, usage=None):
        def apply(rows):
            for row in rows:
                held = row.setdefault("reservations", {}).pop(reservation, None)
                if held is None:
                    continue  # idempotent completion
                row["spent"] = row.get("spent", 0) + (held if cost is None else cost)
                row["requests"] = row.get("requests", 0) + 1
                for field, api_field in (("input_tokens", "inputTokens"), ("output_tokens", "outputTokens")):
                    row[field] = row.get(field, 0) + (usage or {}).get(api_field, 0)
        self.store.transact([self.uid, "__budget_total"], apply)


class BudgetModel(Model):
    def __init__(self, inner, budget, should_stop=lambda: False):
        self.inner, self.budget = inner, budget
        model = inner.get_config().get("model_id")
        if model not in PRICES:
            raise ValueError("Hosted credit tracking requires a priced model: gpt-4.1-mini.")
        self.prices = PRICES[model]
        self.should_stop = should_stop
        self.calls = 0
        self.lock = threading.Lock()
        self.deadline = time.monotonic() + 900

    def get_config(self):
        return self.inner.get_config()

    def update_config(self, **model_config: Any):
        raise ValueError("A metered model's configuration cannot change during a run.")

    def _reserve(self, payload):
        with self.lock:
            if self.should_stop() or time.monotonic() > self.deadline or self.calls >= 100:
                raise RunPaused("This work session paused. Your progress is saved; choose Continue to resume.")
            self.calls += 1
        # Text-only demo: UTF-8 byte length is a conservative token upper bound.
        # Add schema/protocol headroom and a fixed, provider-enforced output cap.
        size = len(json.dumps(payload, default=str, ensure_ascii=False).encode()) + 8192
        cost = math.ceil(size * self.prices[0] + 4096 * self.prices[2])
        return self.budget.reserve(cost)

    async def stream(self, *args, **kwargs):
        reservation = self._reserve([args, kwargs])
        usage = None
        cost = None
        try:
            async for event in self.inner.stream(*args, **kwargs):
                if "metadata" in event and event["metadata"].get("usage"):
                    usage = event["metadata"]["usage"]
                yield event
        except Exception as exc:
            # Explicit request rejection has no token charge; network uncertainty does.
            if getattr(exc, "status_code", None) in (400, 401, 403, 404, 429):
                cost = 0
            raise
        finally:
            if usage:
                cached = usage.get("cacheReadInputTokens", 0)
                cost = math.ceil((usage["inputTokens"] - cached) * self.prices[0]
                                 + cached * self.prices[1] + usage["outputTokens"] * self.prices[2])
            self.budget.settle(reservation, cost, usage)

    async def structured_output(self, *args, **kwargs):
        # All current agents use structured_output_model, which goes through
        # stream(). Fail closed if a future caller uses the unmetered legacy API.
        raise NotImplementedError("Use Agent(..., structured_output_model=...) for metered structured output.")
        yield  # pragma: no cover
