"""Offline grading contracts, isolation, persistence and explanation lifecycle."""
import asyncio
import copy
import json
import time
from unittest.mock import AsyncMock

import pytest

from agent import judge, server, store
from agent.tests.test_server import client, body  # shared offline D1/API fixture


def assessment(answer="The s3–s1 link is down at s3 port 1."):
    result = judge.prepare({"topology": "main6s8h", "scenario": "F1"},
                           "Why can h1 not reach h5?", [])
    result["answer"] = answer
    return result


def decision(verdict="correct"):
    return {"model": "gpt-6-luna", "answers": [{"type": "choice", "name": "diagnosis_correctness",
            "choice": verdict, "confidence": .91, "probabilities": [{"value": verdict, "probability": .91}]}],
            "usage": {"input_tokens": 100, "output_tokens": 0, "input_tokens_details": {"cached_tokens": 20}}}


class Provider:
    def __init__(self):
        self.decisions = []
        self.responses = []
        self.hold_judge = False
        self.hold_explanation = False
        self.verdict = "correct"

    async def create_decision(self, payload):
        self.decisions.append(copy.deepcopy(payload))
        while self.hold_judge:
            await asyncio.sleep(.01)
        return decision(self.verdict)

    async def create_response(self, payload):
        self.responses.append(copy.deepcopy(payload))
        while self.hold_explanation:
            await asyncio.sleep(.01)
        return {"id": "explain-1", "status": "completed", "model": "gpt-6.1-sol",
                "output": [{"type": "message", "content": [{"type": "output_text", "text": "The diagnosis identifies the down link and its exact port."}]}],
                "usage": {"input_tokens": 50, "output_tokens": 20}}

    async def close(self):
        pass


@pytest.mark.parametrize("topology", sorted(judge.TOPOLOGIES))
@pytest.mark.parametrize("fault", [f"F{i}" for i in range(1, 6)])
def test_rubric_capture_and_typed_choice(topology, fault):
    result = judge.prepare({"topology": topology, "scenario": fault}, "Test prompt", [])
    result["answer"] = "Test answer"
    payload = judge.decision_payload(result)
    assert result["status"] == "pending"
    assert result["rubric_path"] == f"judge/{topology}/Fault{fault[1:]}.md"
    assert len(result["rubric_sha256"]) == 64
    question = payload["questions"][0]
    assert question["type"] == "choice" and payload["model"] == "gpt-6-luna"
    assert [c["value"] for c in question["choices"]] == list(judge.VERDICTS)
    assert "## Judge output" not in question["instructions"]
    assert "Missing optional observations is not an error" in question["instructions"]
    evidence = json.loads(payload["input"])
    assert evidence["question"] == "Test prompt" and evidence["agent_diagnosis"] == "Test answer"


def test_missing_rubric_and_invalid_paths_are_not_graded(monkeypatch, tmp_path):
    assert judge.prepare({"scenario": None}, "", [])["status"] == "skipped"
    assert judge.prepare({"topology": "../../outside", "scenario": "F1"}, "", [])["status"] == "error"
    monkeypatch.setattr(judge.config, "REPO_ROOT", tmp_path)
    assert judge.prepare({"topology": "main6s8h", "scenario": "F1"}, "", [])["status"] == "error"


@pytest.mark.parametrize("verdict", list(judge.VERDICTS))
def test_decision_verdict_and_criteria_are_preserved(monkeypatch, verdict):
    saved = []
    monkeypatch.setattr(store, "update_evaluation", lambda cid, mid, value: saved.append(copy.deepcopy(value)))
    provider = Provider()
    provider.verdict = verdict
    result = assessment()
    asyncio.run(judge.evaluate(provider, "chat", "answer", result))
    assert result["status"] == "completed"
    assert result["label"] == judge.VERDICTS[verdict]
    assert result["criteria_text"] == result["criteria"][verdict]
    assert result["cost_usd"] == pytest.approx((80 * .1 + 20 * .01) / 1e6)
    assert result["raw_result"] == decision(verdict)
    assert saved[-1] == result
    assert all(k not in judge.public(result) for k in ("rubric", "question", "answer", "context"))


@pytest.mark.parametrize("response", [
    {"answers": [{"type": "refusal", "name": "diagnosis_correctness"}]},
    {"answers": [{"type": "choice", "name": "diagnosis_correctness", "choice": "unknown"}]},
    {"answers": []},
])
def test_invalid_results_are_errors_not_incorrect(monkeypatch, response):
    monkeypatch.setattr(store, "update_evaluation", lambda *_: True)
    provider = Provider()
    provider.create_decision = AsyncMock(return_value=response)
    result = assessment()
    asyncio.run(judge.evaluate(provider, "chat", "answer", result))
    assert result["status"] == "error" and "verdict" not in result


def finish(client, url, kind="judge"):
    for _ in range(150):
        value = client.get(url).json()
        target = value.get("explanation", {}) if kind == "explain" else value
        if target.get("status") != "pending":
            return value
        time.sleep(.01)
    pytest.fail("Offline evaluation did not finish")


def setup_diagnosis(client, monkeypatch, provider):
    monkeypatch.setattr(server.app.state, "client", provider)
    monkeypatch.setattr(server, "network_settings", lambda: {"topology": "main6s8h", "scenario": "F1"})
    seen = []
    async def run(_provider, history, model, effort, state):
        seen.append(copy.deepcopy(history))
        state["content"] = "The s3–s1 link is down at s3 port 1."
        history.append({"role": "assistant", "content": state["content"]})
        yield {"type": "text", "text": state["content"]}
    monkeypatch.setattr(server, "run", run)
    cid = client.post("/api/conversations").json()["id"]
    result = client.post("/api/chat", json=body(cid))
    assert result.status_code == 200
    frames = [json.loads(line[6:]) for line in result.text.splitlines() if line.startswith("data: ")]
    event = next(f for f in frames if f["type"] == "evaluation")
    url = f"/api/conversations/{cid}/messages/{event['message_id']}/evaluation"
    return cid, event, url, seen


def test_automatic_job_persistence_and_explanation_isolation(client, monkeypatch):
    provider = Provider()
    provider.hold_judge = True
    cid, event, url, seen = setup_diagnosis(client, monkeypatch, provider)
    assert event["evaluation"]["status"] == "pending"
    assert client.get(url).json()["status"] == "pending"
    assert client.post(url + "/explain").status_code == 409
    assert server.busy is False
    provider.hold_judge = False
    result = finish(client, url)
    assert result["verdict"] == "correct"
    assert len(provider.decisions) == 1
    assert "rubric" not in client.get(f"/api/conversations/{cid}").json()["messages"][1]["evaluation"]
    provider.hold_explanation = True
    assert client.post(url + "/explain").json()["explanation"]["status"] == "pending"
    assert client.post(url + "/explain").status_code == 200
    provider.hold_explanation = False
    result = finish(client, url, "explain")
    assert result["explanation"]["status"] == "completed" and len(provider.responses) == 1
    payload = provider.responses[0]
    assert payload["model"] == "gpt-6.1-sol" and payload["reasoning"] == {"effort": "high"}
    assert payload["store"] is False and "tools" not in payload
    evidence = json.loads(payload["input"][0]["content"])
    assert evidence["fault"] == "F1" and evidence["question"] == "Check the network"
    assert "s3 port 1" in evidence["expected_result"]
    assert evidence["decision_api_result"]["answers"][0]["choice"] == "correct"
    assert client.post(url + "/explain").json()["explanation"]["status"] == "completed"
    assert len(provider.responses) == 1
    assert client.post("/api/chat", json=body(cid)).status_code == 200
    assert seen[-1] == [{"role": "user", "content": "Check the network"},
                        {"role": "assistant", "content": "The s3–s1 link is down at s3 port 1."},
                        {"role": "user", "content": "Check the network"}]
    saved = store.get(cid)
    assert len(saved["messages"]) == 4
    assert saved["messages"][1]["evaluation"]["explanation"]["status"] == "completed"
    assert "evaluation" not in json.dumps(saved["history"])
    assert client.get(url).json()["verdict"] == "correct"


def test_saved_pending_job_recovers_without_provider_calls(client):
    cid = store.create()["id"]
    value = assessment()
    store.save(cid, {"role": "user", "content": "Question"},
               {"id": "old", "role": "assistant", "content": "Answer", "evaluation": value}, [])
    url = f"/api/conversations/{cid}/messages/old/evaluation"
    result = client.get(url).json()
    assert result["status"] == "error" and "interrupted" in result["error"]
    assert store.get(cid)["messages"][1]["evaluation"]["status"] == "error"
    assert client.get(f"/api/conversations/{cid}/messages/missing/evaluation").status_code == 404


def test_provider_failure_keeps_diagnosis_and_statistics(client, monkeypatch):
    provider = Provider()
    provider.create_decision = AsyncMock(side_effect=RuntimeError("Gateway decisions request failed with status 404."))
    cid, event, url, _ = setup_diagnosis(client, monkeypatch, provider)
    result = finish(client, url)
    assert result["status"] == "error" and "verdict" not in result
    saved = store.get(cid)["messages"][1]
    assert saved["stats"]["status"] == "completed"
    assert saved["content"] == "The s3–s1 link is down at s3 port 1."
    assert "cost_usd" not in saved["stats"]  # judge usage is never mixed into diagnosis stats
