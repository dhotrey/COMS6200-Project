"""The sweep's agent-side paths: diagnosis, preflight, judge and results-page publishing.

No network, no model provider, no D1 and no diagnostic commands.
"""
import copy

import pytest

from agent import benchmark, config, loop, store
from experiments import sweep, sweep_publish


def response(*output):
    return {"id": "response-test", "model": "gpt-5.6-luna", "status": "completed", "output": list(output),
            "usage": {"input_tokens": 1000, "output_tokens": 50, "total_tokens": 1050,
                      "input_tokens_details": {"cached_tokens": 800},
                      "output_tokens_details": {"reasoning_tokens": 20}}}


def message(text):
    return {"type": "message", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": text, "annotations": []}]}


class FakeClient:
    def __init__(self, *responses, error=None, decision="correct"):
        self.results = iter(responses)
        self.error = error
        self.decision = decision
        self.requests = []
        self.decisions = []
        self.closed = False

    async def stream_events(self, payload):
        self.requests.append(copy.deepcopy(payload))
        if self.error:
            raise self.error
        result = next(self.results)
        for item in result["output"]:
            if item["type"] == "message":
                yield {"type": "response.output_text.delta", "delta": item["content"][0]["text"]}
        yield {"type": "response.completed", "response": result}

    async def create_judgment(self, payload):
        self.decisions.append(payload)
        probabilities = {value: 0.0 for value in ("correct", "mostly_correct", "partially_correct", "incorrect")}
        probabilities[self.decision] = 1.0
        return {"answers": {"diagnosis_correctness": {
            "type": "choice", "choice": self.decision, "confidence": 1.0,
            "probabilities": probabilities}},
                "usage": {"input_tokens": 2000, "output_tokens": 10}}

    async def close(self):
        self.closed = True


@pytest.fixture
def gateway(monkeypatch):
    def install(client):
        monkeypatch.setattr(config, "make_client", lambda: client)

    monkeypatch.setattr(config, "configured", lambda: True)
    monkeypatch.setattr("logfire.configure", lambda **kwargs: None)

    async def execute(name, arguments):
        return {"name": name, "arguments": {}, "ok": True, "data": {"switches": 5}, "error": None,
                "invalid": False, "duration_seconds": 0.1}

    monkeypatch.setattr(loop, "execute_tool", execute)
    return install


def test_new_conversation_one_turn(gateway):
    call = {"type": "function_call", "name": "get_topology", "call_id": "c1", "arguments": "{}"}
    client = FakeClient(response(call), response(message("A drop rule on s4 blocks h1 to h5.")))
    gateway(client)
    result = sweep.llm_diagnosis("h1 can no longer reach h5.", "gpt-5.6-luna", "medium")
    assert result["status"] == "completed" and result["error"] is None
    assert result["diagnosis_text"] == "A drop rule on s4 blocks h1 to h5."
    assert [row["tool"] for row in result["tool_trace"]] == ["get_topology"]
    assert result["tools"][0]["data"] == {"switches": 5} and result["tools"][0]["call_id"] == "c1"
    stats = result["stats"]
    assert (stats["input_tokens"], stats["cached_tokens"], stats["tool_calls"]) == (2000, 1600, 1)
    assert stats["cost_usd"] > 0
    first = client.requests[0]
    assert first["input"] == [{"role": "user", "content": "h1 can no longer reach h5."}], "fresh conversation"
    assert first["store"] is False and first["model"] == "gpt-5.6-luna"
    assert first["reasoning"] == {"effort": "medium"}
    assert client.closed


def test_models_without_reasoning_get_no_reasoning_fields(gateway):
    for model in ("gpt-4.1-mini", "gpt-4.1-nano"):
        client = FakeClient(response(message("x")))
        gateway(client)
        assert sweep.llm_diagnosis("h1 can no longer reach h5.", model, "none")["status"] == "completed"
        assert "reasoning" not in client.requests[0] and "include" not in client.requests[0], model


@pytest.mark.parametrize(("error", "status"), [
    (RuntimeError("Gateway request failed with status 502."), "infrastructure"),
    (RuntimeError("Gateway request failed with status 429."), "infrastructure"),
    # After the preflight, a 400 is the provider rejecting this conversation: the model's own limit.
    (RuntimeError("Gateway request failed with status 400."), "model_error"),
    (RuntimeError("Model request limit reached."), "model_error"),
    (TimeoutError(), "timeout"),
])
def test_failures_are_classified(gateway, error, status):
    client = FakeClient(error=error)
    gateway(client)
    result = sweep.llm_diagnosis("h1 can no longer reach h5.", "gpt-5.6-luna", "medium")
    assert result["status"] == status, result
    assert client.closed


def test_study_models_and_efforts():
    models, efforts, prices = sweep.model_efforts("medium")
    assert set(sweep.DEFAULT_MODELS) <= set(models)
    assert sweep.DEFAULT_MODELS == ("gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol", "gpt-6-astra",
                                    "gpt-4.1-mini", "gpt-4.1-nano")
    study = {model: efforts[model] for model in sweep.DEFAULT_MODELS}
    assert study["gpt-4.1-mini"] == study["gpt-4.1-nano"] == "none"
    assert {study[m] for m in sweep.DEFAULT_MODELS[:4]} == {"medium"}
    assert set(sweep.DEFAULT_MODELS) <= set(prices) and sweep.check_models(study) == []
    assert sweep.check_models({"gpt-3.5-turbo": "none"}) == [
        "gpt-3.5-turbo is not in agent/config.py MODELS", "gpt-3.5-turbo has no PRICES entry in agent/config.py"]
    assert sweep.check_models({"gpt-4.1-nano": "medium"}) == ["gpt-4.1-nano does not support effort medium"]


def test_preflight_uses_the_loop_without_tools(monkeypatch):
    sent = []

    class Client(FakeClient):
        async def stream_events(self, payload):
            sent.append(payload)
            if payload["model"] == "gpt-4.1-nano":
                raise RuntimeError("Gateway request failed with status 400.")
            yield {"type": "response.completed", "response": response(message("OK"))}

    monkeypatch.setattr(config, "make_client", lambda: Client())
    results = sweep.preflight({"gpt-5.6-sol": "medium", "gpt-4.1-nano": "none"})
    assert results == {"gpt-5.6-sol": None, "gpt-4.1-nano": "RuntimeError: Gateway request failed with status 400."}
    assert all(payload["tool_choice"] == "none" for payload in sent), "preflight must not run tools"
    assert sent[0]["reasoning"] == {"effort": "medium"} and "reasoning" not in sent[1]


def test_judge_grades_with_the_topology_rubric(monkeypatch):
    client = FakeClient(decision="partially_correct")
    monkeypatch.setattr(config, "configured", lambda: True)
    monkeypatch.setattr(config, "make_judge_client", lambda: client)
    evaluation = sweep.judge_diagnosis("ring5s5h", "F3", "h1 can no longer reach h5.", "A drop rule on s2.")
    assert (evaluation["status"], evaluation["verdict"]) == ("completed", "partially_correct")
    assert evaluation["rubric_path"] == "judge/ring5s5h/Fault3.md" and evaluation["model"] == "jev-1.13.0"
    assert evaluation["cost_usd"] == pytest.approx(2000 * .042 / 1e6)
    assert client.decisions[0]["state"]["agent_diagnosis"] == "A drop rule on s2." and client.closed

    silent = FakeClient()
    monkeypatch.setattr(config, "make_judge_client", lambda: silent)
    empty = sweep.judge_diagnosis("ring5s5h", "F3", "h1 can no longer reach h5.", "  ")
    assert (empty["status"], empty["verdict"], empty["label"]) == ("completed", "incorrect", "Incorrect (no answer)")
    assert silent.decisions == [], "no judge call for an empty answer"


def _plan():
    _, efforts, prices = sweep.model_efforts("medium")
    plan = sweep.build_config(run_id="t-sweep", models=list(sweep.DEFAULT_MODELS), efforts=efforts,
                              scenarios=("F1", "F2"), target_rounds=2)
    plan["prices"] = {m: prices.get(m) for m in plan["efforts"]}
    return plan


def _detail(topology, scenario, model, round_number, **fields):
    llm = model is not None
    return {"trial_id": f"{topology}-r{round_number:02d}-{model or 'baseline'}-{scenario}", "round": round_number,
            "topology": topology, "scenario": scenario, "method": "llm" if llm else "baseline", "model": model,
            "effort": "medium" if llm else None, "attempt": 1, "status": "completed", "turn_status": "completed",
            "prompt": "h1 can no longer reach h5.", "diagnosis_text": "answer", "tools": [{"name": "ping"}],
            "stats": {"cost_usd": .01, "usage_complete": True, "model_calls": 2},
            "score": {"family_correct": 1, "location_correct": 1}, "outcome": "success",
            "evaluation": {"status": "completed", "verdict": "correct", "label": "Correct", "cost_usd": .001},
            **fields}


def test_published_sweep_renders_through_the_results_page_code():
    plan = _plan()
    cells = {cell["id"]: cell for cell in sweep_publish.planned_cells(plan)}
    assert len(cells) == 3 * 2 * 7 * 2, "topologies x faults x (baseline + 6 models) x rounds"
    details = [
        _detail("ring5s5h", "F1", "gpt-5.6-sol", 1),
        _detail("ring5s5h", "F1", "gpt-5.6-sol", 2,
                evaluation={"status": "completed", "verdict": "partially_correct", "label": "Partially correct"}),
        _detail("ring5s5h", "F1", None, 1),
        {**_detail("ring5s5h", "F2", None, 1), "status": "excluded", "reason": "gate failed",
         "evaluation": None, "diagnosis_text": "", "tools": []},
    ]
    for detail in details:
        cell = sweep_publish.trial_cell(plan, detail)
        assert cell["id"] in cells, cell["id"]
        cells[cell["id"]] = cell
    run = {**sweep_publish.run_payload(plan, details, "paused"), "cells": list(cells.values())}
    public = benchmark.public_run(run)
    by_id = {cell["id"]: cell for cell in public["cells"]}
    sol = by_id["ring5s5h:F1:gpt-5.6-sol:medium"]
    assert sol["distribution"] == {"correct": 1, "partial": 1, "incorrect": 0} and sol["status"] == "completed"
    baseline = by_id["ring5s5h:F1:scripted-baseline:none"]
    assert baseline["distribution"]["correct"] == 1 and baseline["total"] == 2
    assert by_id["ring5s5h:F2:scripted-baseline:none"]["status"] in {"running", "incomplete"}
    assert public["variants"][0] == sweep_publish.BASELINE_VARIANT
    assert [v["model"] for v in public["variants"][1:]] == list(sweep.DEFAULT_MODELS)
    assert public["mode"] == "sweep" and public["repeats"] == 2 and public["concurrency"] == 1
    assert public["cost"]["judge_usd"] == pytest.approx(.002)

    excluded = sweep_publish.trial_cell(plan, details[3])
    assert excluded["status"] == "error" and "Excluded" in excluded["error"] and "conversation_id" not in excluded
    completed = sweep_publish.trial_cell(plan, details[0])
    title, user, assistant, history = sweep_publish.chat_messages(plan, details[0], completed)
    assert title.startswith("Sweep · Ring F1 · GPT-5.6 Sol / medium · Round 1")
    assert assistant["id"] == completed["message_id"] and assistant["benchmark"]["cell_id"] == completed["id"]
    assert history == [user, {"role": "assistant", "content": "answer"}]
    again = sweep_publish.trial_cell(plan, details[0])
    assert again["conversation_id"] == completed["conversation_id"], "republishing reuses the same chat"


def test_publisher_creates_then_updates_and_never_raises(monkeypatch, tmp_path, capsys):
    plan = _plan()
    calls = []
    existing = {}
    monkeypatch.setattr(store, "initialize", lambda: calls.append(("initialize",)))
    monkeypatch.setattr(store, "get_benchmark", lambda run_id, detail=True: existing.get(run_id))

    def create(run, cells):
        calls.append(("create", run["id"], len(cells)))
        existing[run["id"]] = {**run, "cells": cells}

    monkeypatch.setattr(store, "create_benchmark", create)
    monkeypatch.setattr(store, "save_benchmark", lambda run: calls.append(("save", run["status"], run["finished"])))
    monkeypatch.setattr(store, "add_benchmark_cells", lambda run_id, cells: calls.append(("add", len(cells))))
    monkeypatch.setattr(store, "get", lambda cid: None)
    monkeypatch.setattr(store, "save_benchmark_chat", lambda *args: calls.append(("chat", args[1]["id"])))
    monkeypatch.setattr(store, "save_benchmark_cell", lambda run_id, cell: calls.append(("cell", cell["id"])))
    sweep.save_plan(tmp_path, plan)

    publisher = sweep_publish.Publisher(tmp_path, plan)
    publisher.start()
    assert calls[:2] == [("initialize",), ("create", "sweep-t-sweep", 84)]
    record = _detail("main6s8h", "F1", "gpt-4.1-nano", 1, effort="none")
    sweep.append_record(tmp_path, record)
    publisher.trial(record)
    assert ("chat", "main6s8h:F1:gpt-4.1-nano:none:trial:1") in calls and calls[-1] == ("save", "running", 1)

    # A third round started beyond the target adds rows instead of recreating the run.
    plan["rounds"] = [{"topology": "tree5s8h", "round": n, "trials": []} for n in (1, 2, 3)]
    sweep_publish.ensure_run(plan, [record], "paused")
    assert ("add", 2 * 7) in calls

    monkeypatch.setattr(store, "get", lambda cid: {"id": cid})
    sweep_publish.publish_trial(plan, record)
    assert calls[-1] == ("cell", "main6s8h:F1:gpt-4.1-nano:none:trial:1"), "existing chat: update the row only"

    def broken(*args):
        raise RuntimeError("D1 unavailable")

    monkeypatch.setattr(store, "save_benchmark_cell", broken)
    publisher.trial(record)
    publisher.trial(record)
    publisher.finish()
    output = capsys.readouterr().out
    assert output.count("Warning: results page") == 1 and "python3 -m experiments.sweep publish" in output
