"""Test fixtures, including a deterministic ScriptedModel.

The ScriptedModel implements the Strands ``Model`` interface and replays a
queue of scripted actions (tool calls and text turns). This lets the test
suite drive the *real* Strands event loop — real tool dispatch, real hooks,
real structured output plumbing — with zero network and zero flakiness.
"""

from __future__ import annotations

import json
from collections import deque
from typing import Any

import pytest
from strands.models.model import Model

from epilogue.domain import Case, Person, Survivor
from epilogue.ledger import Ledger
from epilogue.runtime import Runtime
from epilogue.simworld import SimWorld


class ScriptedModel(Model):
    """Replays scripted turns: ("tool", name, input_dict) or ("text", message).

    Each agent invocation consumes turns until a "text" turn (which ends the
    invocation with end_turn). ``structured`` maps output-model class names to
    instances (or callables receiving the prompt messages) for
    ``structured_output`` calls.
    """

    def __init__(self, turns: list | None = None, structured: dict | None = None) -> None:
        self.turns = deque(turns or [])
        self.structured = structured or {}
        self.calls: list[dict] = []

    def get_config(self) -> Any:
        return {"model_id": "scripted"}

    def update_config(self, **model_config: Any) -> None:  # pragma: no cover
        pass

    def _structured_answer(self, messages, tool_specs) -> tuple[str, dict] | None:
        """If a structured-output tool is among the specs, answer it from the script.

        Strands registers the target Pydantic model as a tool and (if needed)
        forces it on a second pass; a scripted model simply answers on sight.
        A callable script value receives the conversation messages, so answers
        can key off content instead of call order (immune to delivery-order
        differences across platforms).
        """
        for spec in tool_specs or []:
            for key, value in self.structured.items():
                if key in spec.get("name", ""):
                    if isinstance(value, deque):
                        value = value.popleft()
                    if callable(value):
                        value = value(messages)
                    return spec["name"], json.loads(value.model_dump_json())
        return None

    async def stream(self, messages, tool_specs=None, system_prompt=None, tool_choice=None, **kwargs):
        self.calls.append({"messages": messages, "system_prompt": system_prompt})
        structured = self._structured_answer(messages, tool_specs)
        turn = (
            ("tool", *structured)
            if structured
            else (self.turns.popleft() if self.turns else ("text", "Done."))
        )
        yield {"messageStart": {"role": "assistant"}}
        if turn[0] == "tool":
            _, name, tool_input = turn
            yield {
                "contentBlockStart": {
                    "start": {"toolUse": {"toolUseId": f"scripted_{len(self.calls)}", "name": name}}
                }
            }
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(tool_input)}}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"contentBlockDelta": {"delta": {"text": turn[1]}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):
        key = output_model.__name__
        if key not in self.structured:
            raise AssertionError(f"No scripted structured output for {key}")
        value = self.structured[key]
        if callable(value):
            value = value(prompt)
        if isinstance(value, deque):
            value = value.popleft()
        yield {"output": value}


@pytest.fixture()
def ledger(tmp_path):
    return Ledger(tmp_path / "test.db")


@pytest.fixture()
def case(ledger):
    c = Case(
        deceased=Person(
            full_name="James Mitchell",
            date_of_death=__import__("datetime").date(2026, 8, 30),
            state="OH",
        ),
        survivor=Survivor(full_name="Sarah Mitchell", relationship="daughter", is_executor=True),
        narrative="My dad passed away. Please don't delete his photos without asking.",
    )
    ledger.save_case(c)
    return c


@pytest.fixture()
def runtime(ledger, case):
    return Runtime(ledger=ledger, world=SimWorld(ledger), case=case)
