"""Offline benchmark contracts. No Mininet, D1 service or paid provider calls."""
import asyncio
from copy import deepcopy
import threading

import pytest

from agent import benchmark, judge, server, store, tools
from agent.tests.test_server import client, body
from agent.tests.test_store import database


class Provider:
    async def create_judgment(self, payload):
        return {"model": judge.MODEL, "answers": {"diagnosis_correctness": {"type": "choice", "choice": "correct",
                "confidence": 1.0, "probabilities": {v: float(v == "correct") for v in judge.VERDICTS}}},
                "usage": {"input_tokens": 12, "output_tokens": 0}}

    async def create_response(self, payload):
        return {"status": "completed", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": "The diagnosis identifies the expected type and location."}]}],
            "usage": {"input_tokens": 12, "output_tokens": 12}}


@pytest.fixture
def harness(monkeypatch):
    runs, cells, events = {}, {}, []
    def create(item, initial):
        runs[item["id"]] = deepcopy(item)
        for cell in initial:
            cells[item["id"], cell["id"]] = deepcopy(cell)
    monkeypatch.setattr(store, "create_benchmark", create)
    monkeypatch.setattr(store, "save_benchmark", lambda item: runs.update({item["id"]: deepcopy(item)}))
    monkeypatch.setattr(store, "save_benchmark_cell", lambda rid, cell: cells.update({(rid, cell["id"]): deepcopy(cell)}))
    monkeypatch.setattr(store, "save_benchmark_cells", lambda rid, batch: cells.update({(rid, c["id"]): deepcopy(c) for c in batch}))
    monkeypatch.setattr(store, "get_benchmark_cell", lambda rid, cid: deepcopy(cells.get((rid, cid))))
    monkeypatch.setattr(store, "save_benchmark_evaluation", lambda rid, cid, value: cells[rid, cid].update(evaluation=deepcopy(value)))
    def save_chat(rid, cell, title, user, assistant, history):
        assert "Benchmark" in title
        assert f"Trial {cell['trial']}/" in title
        assert history[0] == user and "benchmark" not in user
        assert assistant["settings"]["model"] == cell["model"]
        assert assistant["benchmark"]["trial"] == cell["trial"]
        cells[rid, cell["id"]] = deepcopy(cell)
    monkeypatch.setattr(store, "save_benchmark_chat", save_chat)
    def update_evaluation(cid, mid, value):
        for cell in cells.values():
            if cell.get("conversation_id") == cid and cell.get("message_id") == mid:
                cell["evaluation"] = deepcopy(value)
                return True
        return False
    monkeypatch.setattr(store, "update_evaluation", update_evaluation)
    def load(fault, topology):
        events.append(("load", topology, fault))
        return {"ok": True, "scenario_id": fault, "topology": topology}
    monkeypatch.setattr(benchmark.fault_control, "load_scenario", load)
    monkeypatch.setattr(benchmark.fault_control, "reset_scenario", lambda: events.append(("reset",)) or {"ok": True})
    monkeypatch.setattr(tools, "refresh_tools", lambda: None)
    return runs, cells, events


def test_catalogue_filters_efforts():
    options = benchmark.variants()
    for model in ("gpt-4.1-mini", "gpt-4.1-nano"):
        assert [v["effort"] for v in options if v["model"] == model] == ["none"]
    assert len(options) == 26
    assert len(options) * 15 == 390
    assert {v["effort"] for v in options if v["model"] == "gpt-6.1-sol"} == set(benchmark.EFFORTS)


def test_scenarios_wait_for_all_variants_and_histories_are_isolated(monkeypatch, harness):
    runs, cells, events = harness
    histories, active, maximum = [], 0, 0
    second_started = asyncio.Event()
    diagnosis_provider = object()  # Has no judge API; grading must use the other client.
    async def diagnose(client, history, model, effort, state, **kwargs):
        nonlocal active, maximum
        assert client is diagnosis_provider
        active += 1
        maximum = max(maximum, active)
        topology = manager.active["current"]["topology"]
        fault = manager.active["current"]["scenario"]
        histories.append(deepcopy(history))
        events.append(("diagnose", topology, fault, model, effort))
        assert history == [{"role": "user", "content": benchmark.PROMPTS[fault]}]
        assert "evaluation" not in kwargs and "rubric" not in kwargs
        if len(histories) == 1:
            await asyncio.wait_for(second_started.wait(), timeout=2)
        elif len(histories) == 2:
            second_started.set()
        await asyncio.sleep(.01)
        state["content"] = "The fault type and location are identified."
        history.append({"role": "assistant", "content": state["content"]})
        active -= 1
        yield {}
    monkeypatch.setattr(benchmark, "diagnose", diagnose)
    async def exercise():
        nonlocal manager
        manager = benchmark.Benchmark(diagnosis_provider, Provider())
        item = await manager.start([{"model": "gpt-6.1-sol", "effort": "low"},
                                    {"model": "gpt-4.1-mini", "effort": "none"}], 2, repeats=1)
        await manager.task
        saved = runs[item["id"]]
        assert saved["status"] == "completed" and saved["finished"] == saved["total"] == 30
        assert manager.active is None
        assert len(histories) == 30 and all(len(history) == 1 for history in histories)
        assert maximum == 2
        assert events[-1] == ("reset",)
        assert [event[:3] for event in events[:-1]] == [
            event for topology in benchmark.topology_control.TOPOLOGIES for fault in benchmark.SCENARIOS
            for event in [("load", topology["id"], fault), ("diagnose", topology["id"], fault),
                          ("diagnose", topology["id"], fault)]]
        assert all(cell["status"] == "completed" for cell in cells.values())
        assert all(cell["evaluation"]["verdict"] == "correct" for cell in cells.values())
        assert len({cell["conversation_id"] for cell in cells.values()}) == 30
        assert all(cell.get("message_id") for cell in cells.values())
    manager = None
    asyncio.run(exercise())


def test_probe_cancellation_holds_lock_until_native_cleanup(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = []
    def execute(name, arguments):
        calls.append(name)
        if name == "first":
            entered.set()
            assert release.wait(5)
        return {"ok": True}
    monkeypatch.setattr(tools, "_execute", execute)
    async def exercise():
        manager = benchmark.Benchmark(Provider(), Provider())
        first = asyncio.create_task(manager.probe("first", "{}"))
        assert await asyncio.to_thread(entered.wait, 5)
        first.cancel()
        second = asyncio.create_task(manager.probe("second", "{}"))
        await asyncio.sleep(.02)
        assert calls == ["first"] and not first.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        result = await second
        assert calls == ["first", "second"] and result["queue_wait_seconds"] > 0
    try:
        asyncio.run(exercise())
    finally:
        release.set()


def test_stop_during_setup_waits_then_resets_without_diagnosing(monkeypatch, harness):
    runs, cells, events = harness
    entered, release = threading.Event(), threading.Event()
    def load(fault, topology):
        entered.set()
        assert release.wait(5)
        return {"ok": True, "scenario_id": fault, "topology": topology}
    monkeypatch.setattr(benchmark.fault_control, "load_scenario", load)
    async def diagnose(*args, **kwargs):
        pytest.fail("Stop during setup must not start a diagnosis")
        yield {}
    monkeypatch.setattr(benchmark, "diagnose", diagnose)
    async def exercise():
        manager = benchmark.Benchmark(Provider(), Provider())
        item = await manager.start([{"model": "gpt-4.1-mini", "effort": "none"}], 1)
        assert await asyncio.to_thread(entered.wait, 5)
        manager.stop()
        assert manager.active is not None and manager.active["status"] == "stopping"
        release.set()
        await manager.task
        assert manager.active is None and runs[item["id"]]["status"] == "cancelled"
        assert events == [("reset",)] and all(c["status"] == "skipped" for c in cells.values())
    try:
        asyncio.run(exercise())
    finally:
        release.set()


def test_judge_failure_is_error_not_incorrect(monkeypatch, harness):
    runs, cells, _ = harness
    async def diagnose(client, history, model, effort, state, **kwargs):
        state["content"] = "A completed diagnosis."
        yield {}
    monkeypatch.setattr(benchmark, "diagnose", diagnose)
    provider = Provider()
    async def refusal(payload):
        return {"answers": []}
    provider.create_judgment = refusal
    async def exercise():
        manager = benchmark.Benchmark(provider, provider)
        item = await manager.start([{"model": "gpt-4.1-mini", "effort": "none"}], 1)
        await manager.task
        assert runs[item["id"]]["status"] == "completed"
        assert all(c["status"] == "error" and "verdict" not in c["evaluation"] for c in cells.values())
    asyncio.run(exercise())


def test_setup_failure_aborts_without_model_calls_and_resets(monkeypatch, harness):
    runs, cells, events = harness
    monkeypatch.setattr(benchmark.fault_control, "load_scenario", lambda *args: {"ok": False, "error": "Setup failed."})
    async def diagnose(*args, **kwargs):
        pytest.fail("A failed setup must not call a model")
        yield {}
    monkeypatch.setattr(benchmark, "diagnose", diagnose)
    async def exercise():
        manager = benchmark.Benchmark(Provider(), Provider())
        item = await manager.start([{"model": "gpt-4.1-mini", "effort": "none"}], 1)
        await manager.task
        assert runs[item["id"]]["status"] == "error"
        assert events == [("reset",)]
        assert manager.active is None and all(c["status"] == "skipped" for c in cells.values())
    asyncio.run(exercise())


def test_cleanup_failure_blocks_chat_until_network_reload(monkeypatch, harness):
    runs, _, _ = harness
    monkeypatch.setattr(benchmark.topology_control, "error", None)
    monkeypatch.setattr(benchmark.fault_control, "load_scenario", lambda *args: {"ok": False, "error": "Setup failed."})
    monkeypatch.setattr(benchmark.fault_control, "reset_scenario", lambda: {"ok": False, "error": "Reset failed."})
    async def exercise():
        manager = benchmark.Benchmark(Provider(), Provider())
        item = await manager.start([{"model": "gpt-4.1-mini", "effort": "none"}], 1)
        await manager.task
        assert runs[item["id"]]["status"] == "error"
        assert benchmark.topology_control.error == "Reset failed."
        assert manager.active is None
    asyncio.run(exercise())


def test_explanation_is_deduplicated_and_saved(monkeypatch, harness):
    _, cells, _ = harness
    evaluation = judge.prepare({"topology": "main6s8h", "scenario": "F1"}, "Symptom", [])
    evaluation.update(status="completed", answer="Diagnosis", raw_result={}, label="Correct", criteria_text="Correct.")
    cells["run", "cell"] = {"id": "cell", "status": "completed", "evaluation": evaluation}
    provider = Provider()
    calls = []
    create_response = provider.create_response
    async def respond(payload):
        calls.append(deepcopy(payload))
        await asyncio.sleep(.01)
        return await create_response(payload)
    provider.create_response = respond
    async def exercise():
        manager = benchmark.Benchmark(provider, provider)
        await asyncio.gather(manager.explain("run", "cell"), manager.explain("run", "cell"))
        await asyncio.gather(*manager.explanations.values())
        await manager.explain("run", "cell")
        assert len(calls) == 1 and "tools" not in calls[0]
        assert cells["run", "cell"]["evaluation"]["explanation"]["status"] == "completed"
        assert cells["run", "cell"]["status"] == "completed"
    asyncio.run(exercise())


def test_persistence_and_restart_recovery(database):
    store.initialize()
    run = {"id": "run", "status": "running", "system_prompt": "Saved instructions"}
    cell = {"id": "cell", "status": "grading", "content": "Diagnosis", "tools": [{"name": "ping"}],
            "evaluation": {"rubric": "Ground truth", "status": "pending", "explanation": {"status": "pending"}}}
    store.create_benchmark(run, [cell])
    assert store.get_benchmark("run")["cells"][0] == cell
    summary = store.get_benchmark("run", False)["cells"][0]
    assert "content" not in summary and "tools" not in summary and "rubric" not in summary["evaluation"]
    assert "system_prompt" not in store.benchmark_listing()[0]
    store.interrupt_benchmarks()
    saved = store.get_benchmark("run")
    assert saved["status"] == "interrupted" and saved["cells"][0]["status"] == "interrupted"
    assert saved["cells"][0]["evaluation"]["explanation"]["status"] == "error"
    store.save_benchmark_evaluation("run", "cell", {"status": "completed", "verdict": "correct"})
    assert store.get_benchmark_cell("run", "cell")["status"] == "interrupted"


def test_results_page_and_active_benchmark_exclusion(client):
    assert client.get("/results.html").status_code == 200
    assert client.get("/results").status_code == 200
    page = client.get("/results").text
    assert 'link.href = `/?conversation=' in page
    assert 'id="repeats"' in page and 'id="cell-details"' in page
    assert 'get("conversation")' in client.get("/").text
    assert len(client.get("/api/benchmarks/config").json()["variants"]) == 26
    server.app.state.benchmark.active = {"id": "active", "status": "running"}
    try:
        assert client.post("/api/benchmarks", json={"variants": [{"model": "gpt-4.1-mini", "effort": "none"}]}).status_code == 409
        assert client.post("/api/scenario/reset").status_code == 409
        assert client.post("/api/topology/load", json={"topology": "main6s8h"}).status_code == 409
        cid = client.post("/api/conversations").json()["id"]
        assert client.post("/api/chat", json=body(cid)).status_code == 409
    finally:
        server.app.state.benchmark.active = None


@pytest.mark.parametrize("variants", [[], [{"model": "gpt-4.1-mini", "effort": "low"}],
                                    [{"model": "unknown", "effort": "low"}],
                                    [{"model": "gpt-4.1-mini", "effort": "none"}] * 2])
def test_invalid_selection_never_starts(client, variants):
    assert client.post("/api/benchmarks", json={"variants": variants}).status_code == 422
    assert server.app.state.benchmark.active is None


def test_benchmark_chat_and_matrix_share_assessment(database):
    store.initialize()
    evaluation = judge.prepare({"topology": "main6s8h", "scenario": "F1"}, "Symptom", [])
    cell = {"id": "cell", "status": "grading", "conversation_id": "chat", "message_id": "answer",
            "evaluation": evaluation}
    store.create_benchmark({"id": "run", "status": "running"}, [cell])
    user = {"role": "user", "content": "Symptom"}
    assistant = {"role": "assistant", "id": "answer", "content": "Diagnosis", "tools": [],
                 "settings": {"model": "gpt-4.1-mini", "effort": "none", "topology": "main6s8h", "scenario": "F1"},
                 "benchmark": {"run_id": "run", "cell_id": "cell"}, "evaluation": evaluation}
    history = [user, {"role": "assistant", "content": "Diagnosis"}]
    store.save_benchmark_chat("run", cell, "Benchmark · Main F1 · GPT-4.1 Mini / none", user, assistant, history)
    assert store.listing()[0]["id"] == "chat"
    assert store.get("chat")["history"] == history
    assert store.get("chat")["messages"][1]["settings"] == assistant["settings"]
    evaluated = {**evaluation, "status": "completed", "verdict": "correct", "explanation": {"status": "completed", "content": "Explanation"}}
    assert store.update_evaluation("chat", "answer", evaluated)
    assert store.get_benchmark_cell("run", "cell")["evaluation"] == evaluated
    # A finishing coordinator with an older snapshot must retain the explanation.
    cell["status"] = "completed"
    store.save_benchmark_cell("run", cell)
    assert store.get_benchmark_cell("run", "cell")["evaluation"] == evaluated
    assert store.get("chat")["messages"][1]["evaluation"] == evaluated


def test_cost_totals_include_diagnosis_judge_and_explanation():
    cells = [{"model": "gpt-6.1-sol", "status": "completed", "stats": {"cost_usd": .03, "usage_complete": True},
              "evaluation": {"status": "completed", "cost_usd": .002,
                             "explanation": {"status": "completed", "cost_usd": .01}}},
             {"model": "gpt-4.1-mini", "status": "completed", "stats": {"cost_usd": .001, "usage_complete": True},
              "evaluation": {"status": "completed", "cost_usd": .002}},
             {"model": "gpt-6.1-sol", "status": "skipped"}]
    result = benchmark.run_costs(cells)
    assert result["cost"]["total_usd"] == pytest.approx(.045)
    assert result["costs_by_model"]["gpt-6.1-sol"]["total_usd"] == pytest.approx(.042)
    assert result["costs_by_model"]["gpt-4.1-mini"]["total_usd"] == pytest.approx(.003)
    assert result["cost"]["incomplete"] is False


def test_incomplete_cost_keeps_known_usage_and_does_not_double_count_reasoning():
    cells = [{"status": "cancelled", "stats": {"model_calls": 2, "cost_usd": .012,
              "usage_complete": False, "reasoning_tokens": 2000}},
             {"status": "completed", "stats": {"cost_usd": .01},
              "evaluation": {"status": "error", "cost_usd": None}}]
    summary = benchmark.cost_summary(cells)
    assert summary["total_usd"] == pytest.approx(.022)
    assert summary["incomplete"] is True
    assert benchmark.cost_summary([{"status": "pending", "evaluation": {"explanation": None}}])["incomplete"] is False


def test_matrix_summary_costs_match_full_export(database):
    store.initialize()
    cell = {"id": "cell", "model": "gpt-6.1-sol", "status": "completed", "tools": [{"large": "trace"}],
            "stats": {"cost_usd": .01, "model_calls": 3, "usage_complete": False, "requests": [{"id": "request"}]},
            "evaluation": {"status": "completed", "cost_usd": .002, "rubric": "Expected answer",
                           "explanation": {"status": "completed", "cost_usd": .003, "content": "A long explanation"}}}
    store.create_benchmark({"id": "run", "status": "paused"}, [cell])
    full, summary = store.get_benchmark("run"), store.get_benchmark("run", False)
    assert benchmark.public_run(summary)["cost"] == benchmark.public_run(full)["cost"]
    assert benchmark.public_run(summary)["cost"]["total_usd"] == pytest.approx(.015)
    assert benchmark.public_run(summary)["cost"]["incomplete"] is True
    assert "content" not in summary["cells"][0]["evaluation"]["explanation"]
    assert "requests" not in summary["cells"][0]["stats"]
    assert "tools" not in summary["cells"][0]


def test_pause_safely_finishes_cleanup_then_redo_starts_fresh(monkeypatch, harness):
    runs, cells, events = harness
    entered, release = threading.Event(), threading.Event()
    def load(fault, topology):
        entered.set()
        assert release.wait(5)
        return {"ok": True, "scenario_id": fault, "topology": topology}
    monkeypatch.setattr(benchmark.fault_control, "load_scenario", load)
    async def exercise():
        manager = benchmark.Benchmark(Provider(), Provider())
        variants = [{"model": "gpt-6.1-sol", "effort": "low"}]
        first = await manager.start(variants, 1)
        assert await asyncio.to_thread(entered.wait, 5)
        manager.stop(paused=True)
        assert manager.active["status"] == "pausing"
        with pytest.raises(RuntimeError, match="already running"):
            await manager.start(variants, 1)
        release.set()
        await manager.task
        assert runs[first["id"]]["status"] == "paused" and events == [("reset",)]
        assert manager.active is None and all(c["status"] == "skipped" for c in cells.values())
        # A redo creates a new ID and leaves the previous run unchanged.
        second = await manager.start(variants, 1)
        manager.stop(paused=True)
        await manager.task
        assert second["id"] != first["id"] and runs[first["id"]]["status"] == "paused"
    try:
        asyncio.run(exercise())
    finally:
        release.set()


def test_pause_api_keeps_network_reserved_until_cleanup(client):
    manager = server.app.state.benchmark
    manager.active = {"id": "active", "status": "running", "variants": [{"model": "gpt-6.1-sol", "effort": "low"}]}
    try:
        assert client.post("/api/benchmarks/active/pause").json() == {"status": "pausing"}
        assert client.get("/api/benchmarks/config").json()["active_run"]["status"] == "pausing"
        assert client.post("/api/scenario/reset").status_code == 409
    finally:
        manager.active = None


def graded_trials(outcomes):
    base = "main6s8h:F1:gpt-6.1-sol:low"
    return [{"id": f"{base}:trial:{number}", "matrix_cell_id": base, "trial": number,
             "topology": "main6s8h", "scenario": "F1", "model": "gpt-6.1-sol", "effort": "low",
             "status": "completed", "conversation_id": f"chat-{number}",
             "stats": {"cost_usd": .01, "usage_complete": True},
             "evaluation": {"status": "completed", "verdict": outcome, "cost_usd": .002}}
            for number, outcome in enumerate(outcomes, 1)]


@pytest.mark.parametrize("outcomes,expected,distribution", [
    (["correct", "incorrect", "correct"], "correct", {"correct": 2, "partial": 0, "incorrect": 1}),
    (["correct", "partially_correct", "incorrect"], None, {"correct": 1, "partial": 1, "incorrect": 1}),
    (["correct", "incorrect", "correct", "incorrect"], None, {"correct": 2, "partial": 0, "incorrect": 2}),
    (["mostly_correct", "partially_correct", "correct"], "partial", {"correct": 1, "partial": 2, "incorrect": 0}),
    (["correct", "correct", "partially_correct", "incorrect"], "correct", {"correct": 2, "partial": 1, "incorrect": 1}),
])
def test_matrix_uses_unique_most_frequent_symbol_and_ties(outcomes, expected, distribution):
    cells = benchmark.aggregate_cells(graded_trials(outcomes))
    assert len(cells) == 1
    cell = cells[0]
    assert cell["status"] == "completed" and cell["verdict"] == expected
    assert cell["distribution"] == distribution
    assert cell["graded"] == cell["finished"] == cell["total"] == len(outcomes)
    assert cell["cost"]["total_usd"] == pytest.approx(.012 * len(outcomes))
    assert [trial["conversation_id"] for trial in cell["trials"]] == [f"chat-{n}" for n in range(1, len(outcomes) + 1)]
    if expected is None:
        assert "Inconclusive" in cell["label"]


def test_unfinished_or_failed_trials_do_not_become_incorrect_votes():
    trials = graded_trials(["correct", "correct", "incorrect"])
    trials[-1].update(status="pending", evaluation=None)
    cell = benchmark.aggregate_cells(trials)[0]
    assert cell["status"] == "running" and cell["verdict"] is None
    assert cell["distribution"] == {"correct": 2, "partial": 0, "incorrect": 0}
    trials[-1].update(status="error", evaluation={"status": "error"})
    cell = benchmark.aggregate_cells(trials)[0]
    assert cell["status"] == "incomplete" and cell["verdict"] is None
    assert cell["graded"] == 2 and cell["finished"] == 3


def test_repeats_reapply_scenario_and_publish_independent_chats(monkeypatch, harness):
    runs, cells, events = harness
    histories = []
    async def diagnose(client, history, model, effort, state, **kwargs):
        histories.append(history)
        assert len(history) == 1 and history[0]["role"] == "user"
        state["content"] = "A complete diagnosis"
        state["stats"] = {"model_calls": 1, "cost_usd": .01, "usage_complete": True}
        await kwargs["on_usage"]()
        history.append({"role": "assistant", "content": state["content"]})
        yield {}
    monkeypatch.setattr(benchmark, "diagnose", diagnose)
    async def exercise():
        manager = benchmark.Benchmark(Provider(), Provider())
        item = await manager.start([{"model": "gpt-6.1-sol", "effort": "low"}], 1)
        await manager.task
        saved = runs[item["id"]]
        assert saved["repeats"] == 3 and saved["cell_count"] == 15
        assert saved["total"] == saved["finished"] == 45
        assert len(histories) == len({id(history) for history in histories}) == 45
        assert len({cell["conversation_id"] for cell in cells.values()}) == 45
        assert [event for event in events if event[0] == "load"] == [
            ("load", topology["id"], fault) for topology in benchmark.topology_control.TOPOLOGIES
            for fault in benchmark.SCENARIOS for _ in range(3)]
        public = benchmark.public_run({**saved, "cells": list(cells.values())})
        assert public["graded"] == public["finished"] == public["total"] == 45
        assert len(public["cells"]) == 15 and all(cell["distribution"]["correct"] == 3 for cell in public["cells"])
    asyncio.run(exercise())


def test_repeated_results_survive_db_reads_with_distinct_chat_links(database):
    store.initialize()
    trials = graded_trials(["correct", "incorrect", "correct"])
    store.create_benchmark({"id": "run", "status": "completed", "repeats": 3, "total": 3}, trials)
    full = benchmark.public_run(store.get_benchmark("run"))
    summary = benchmark.public_run(store.get_benchmark("run", False))
    assert full["cells"] == summary["cells"]
    assert summary["cells"][0]["distribution"]["correct"] == 2
    assert summary["cost"]["total_usd"] == pytest.approx(.036)
    assert store.get_benchmark_cell("run", trials[1]["id"])["conversation_id"] == "chat-2"


def test_legacy_single_trial_benchmarks_still_display(database):
    store.initialize()
    trial = graded_trials(["incorrect"])[0]
    trial["id"] = trial.pop("matrix_cell_id")
    trial.pop("trial")
    store.create_benchmark({"id": "legacy", "status": "completed", "total": 1}, [trial])
    public = benchmark.public_run(store.get_benchmark("legacy", False))
    assert public["repeats"] == public["cell_count"] == 1
    assert public["cells"][0]["verdict"] == "incorrect"
    assert public["cells"][0]["trials"][0]["conversation_id"] == "chat-1"


@pytest.mark.parametrize("repeats", [0, -1, 51, 1.5, True, "3"])
def test_invalid_repeat_count_never_starts(client, repeats):
    response = client.post("/api/benchmarks", json={"variants": [{"model": "gpt-4.1-mini", "effort": "none"}], "repeats": repeats})
    assert response.status_code == 422 and server.app.state.benchmark.active is None


def test_start_api_passes_selected_repeats_and_defaults_to_three(client, monkeypatch):
    received = []
    async def start(selected, concurrency, repeats):
        received.append((selected, concurrency, repeats))
        return {"id": "new", "repeats": repeats}
    monkeypatch.setattr(server.app.state.benchmark, "start", start)
    variants = [{"model": "gpt-6.1-sol", "effort": "low"}]
    assert client.post("/api/benchmarks", json={"variants": variants, "concurrency": 2, "repeats": 4}).json()["repeats"] == 4
    assert client.post("/api/benchmarks", json={"variants": variants}).json()["repeats"] == 3
    assert received == [(variants, 2, 4), (variants, 3, 3)]
