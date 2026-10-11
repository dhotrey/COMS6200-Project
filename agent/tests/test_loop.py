"""Exercise complete turns without network access or diagnostic commands."""
import asyncio
import copy
import json

import pytest

from agent import loop


def response(*output, tokens=(10, 5, 2, 1)):
    inp, out, cached, reasoning = tokens
    return {"id": "response-test", "model": "gpt-5.6-luna", "status": "completed",
            "output": list(output), "usage": {
                "input_tokens": inp, "output_tokens": out, "total_tokens": inp + out,
                "input_tokens_details": {"cached_tokens": cached},
                "output_tokens_details": {"reasoning_tokens": reasoning}}}


def call(cid="call-1"):
    return {"type": "function_call", "name": "get_topology", "call_id": cid, "arguments": "{}"}


def message(text):
    return {"type": "message", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": text, "annotations": []}]}


class FakeClient:
    def __init__(self, *responses):
        self.results = iter(responses)
        self.requests = []

    async def stream_events(self, payload):
        self.requests.append(copy.deepcopy(payload))
        result = next(self.results)
        for item in result["output"]:
            if item["type"] == "message":
                for part in item["content"]:
                    if part["type"] == "output_text":
                        yield {"type": "response.output_text.delta", "delta": part["text"]}
        yield {"type": "response.completed", "response": result}


@pytest.mark.parametrize("model,prices", [
    ("gpt-5.6-luna", (.2, .02, 1.2)),
    ("gpt-6.1-sol", (2, .1, 10)),
    ("gpt-6-luna", (.1, .01, .5)),
])
def test_multiround_usage_and_tool_pairing(monkeypatch, model, prices):
    async def execute(name, arguments):
        return {"name": name, "ok": True, "data": {"switches": []}, "duration_seconds": 2}

    monkeypatch.setattr(loop, "execute_tool", execute)
    client = FakeClient(response(call()), response(message("Done"), tokens=(20, 7, 3, 2)))
    history = [{"role": "user", "content": "Check the network"}]
    state = {"content": "", "tools": [], "stats": {}}

    async def collect():
        return [event async for event in loop.run(client, history, model, "medium", state)]

    events = asyncio.run(collect())
    stats = state["stats"]
    assert (stats["input_tokens"], stats["output_tokens"], stats["total_tokens"]) == (30, 12, 42)
    assert (stats["cached_tokens"], stats["reasoning_tokens"]) == (5, 3)
    inp, cached, out = prices
    assert stats["cost_usd"] == pytest.approx((25 * inp + 5 * cached + 12 * out) / 1e6)
    assert all(request["model"] == model for request in client.requests)
    assert stats["model_calls"] == 2 and stats["tool_calls"] == 1
    assert len(stats["requests"]) == 2 and stats["duration_seconds"] >= 0
    assert stats["first_token_seconds"] is not None
    assert state["content"] == "Done"
    observation = client.requests[1]["input"][2]
    assert observation["call_id"] == "call-1"
    assert json.loads(observation["output"]) == {"ok": True, "data": {"switches": []}, "error": None}
    assert [e["type"] for e in events] == ["tool_start", "tool_end", "stats", "text"]


def test_tool_budget_never_executes_excess_calls(monkeypatch):
    monkeypatch.setenv("MAX_TOOL_CALLS", "1")
    executed = []

    async def execute(name, arguments):
        executed.append(name)
        return {"ok": True, "data": {}}

    monkeypatch.setattr(loop, "execute_tool", execute)
    client = FakeClient(response(call("one"), call("two")), response())
    state = {"content": "", "tools": [], "stats": {}}
    history = []

    async def collect():
        return [event async for event in loop.run(client, history, "gpt-5.6-luna", "medium", state)]

    asyncio.run(collect())
    assert len(executed) == 1
    assert client.requests[1]["tool_choice"] == "none"
    outputs = [item for item in history if item["type"] == "function_call_output"]
    assert [item["call_id"] for item in outputs] == ["one", "two"]
    assert json.loads(outputs[1]["output"])["error"] == "Tool budget reached"


def test_zero_token_budget_does_not_stop_later_rounds(monkeypatch):
    monkeypatch.setenv("MAX_TURN_TOKENS", "0")
    monkeypatch.setenv("MAX_TOOL_CALLS", "2")

    async def execute(name, arguments):
        return {"ok": True, "data": {}, "invalid": False}

    monkeypatch.setattr(loop, "execute_tool", execute)
    client = FakeClient(
        response(call("one"), tokens=(20000, 20000, 0, 0)),
        response(message("Done"), tokens=(20000, 20000, 0, 0)),
    )
    state = {"content": "", "tools": [], "stats": {}}
    history = []

    async def collect():
        return [event async for event in loop.run(client, history, "gpt-5.6-luna", "medium", state)]

    events = asyncio.run(collect())
    assert state["content"] == "Done"
    assert state["stats"]["total_tokens"] == 80000
    assert client.requests[1]["max_output_tokens"] == 8192
    assert "error" not in {event["type"] for event in events}


def test_positive_token_budget_still_stops_later_rounds(monkeypatch):
    monkeypatch.setenv("MAX_TURN_TOKENS", "30")

    async def execute(name, arguments):
        return {"ok": True, "data": {}, "invalid": False}

    monkeypatch.setattr(loop, "execute_tool", execute)
    client = FakeClient(response(call("one"), tokens=(20, 20, 0, 0)), response(message("Done")))
    state = {"content": "", "tools": [], "stats": {}}

    async def collect():
        return [event async for event in loop.run(client, [], "gpt-5.6-luna", "medium", state)]

    with pytest.raises(RuntimeError, match="Turn token budget reached"):
        asyncio.run(collect())
