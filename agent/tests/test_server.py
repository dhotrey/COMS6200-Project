"""API persistence and failed/interrupted turn cleanup, all offline."""
import asyncio
import json
import sqlite3
import sys

import pytest
from fastapi.testclient import TestClient

from agent import server, store


class SQLiteD1:
    """D1-compatible persistence double for offline API tests."""

    def __init__(self):
        self.connection = sqlite3.connect(":memory:", check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")

    def query(self, sql, params=None):
        with self.connection:
            cursor = self.connection.execute(sql, params or [])
            return [dict(row) for row in cursor.fetchall()]

    def batch(self, statements):
        results = []
        with self.connection:
            for sql, params in statements:
                cursor = self.connection.execute(sql, params)
                results.append([dict(row) for row in cursor.fetchall()])
        return results

    def close(self):
        self.connection.close()


def _wakeful_loop_factory():
    """Keep Python 3.14's selector loop responsive to cross-thread callbacks.

    The TestClient/AnyIO portal and FastAPI's sync endpoint adapter communicate
    through ``call_soon_threadsafe``.  On the Python 3.14 runtime used by the
    project tests, a selector with no scheduled timers can sleep past those
    callbacks, leaving the TestClient fixture blocked during startup.  A tiny
    timer gives the selector a bounded wake-up interval while preserving the
    normal asyncio loop behavior for the application under test.
    """
    loop = asyncio.new_event_loop()

    def wake():
        loop.call_later(0.01, wake)

    loop.call_soon(wake)
    return loop


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(store, "_database", SQLiteD1())
    monkeypatch.setattr(server.config, "configured", lambda: False)
    monkeypatch.setattr(server.config, "make_client", lambda: pytest.fail("Unexpected provider client"))
    monkeypatch.setattr(server.logfire, "configure", lambda **_: None)
    monkeypatch.setattr(server, "busy", False)
    backend_options = ({"loop_factory": _wakeful_loop_factory}
                       if sys.version_info >= (3, 14) else {})
    with TestClient(server.app, backend_options=backend_options) as client:
        yield client


def body(cid):
    return {"conversation_id": cid, "message": "Check the network", "model": "gpt-5.6-luna", "effort": "medium"}


def test_missing_credentials_and_conversation_crud(client):
    assert client.get("/api/config").json()["configured"] is False
    cid = client.post("/api/conversations").json()["id"]
    assert client.post("/api/chat", json=body(cid)).status_code == 503
    assert store.get(cid)["messages"] == []
    assert client.get("/api/conversations").json()[0]["id"] == cid
    assert "history" not in client.get(f"/api/conversations/{cid}").json()
    renamed = client.patch(
        f"/api/conversations/{cid}", json={"title": "  Link down notes  "}
    )
    assert renamed.status_code == 200
    assert renamed.json() == {"id": cid, "title": "Link down notes"}
    assert client.get("/api/conversations").json()[0]["title"] == "Link down notes"
    assert client.patch("/api/conversations/missing", json={"title": "Gone"}).status_code == 404
    assert client.delete(f"/api/conversations/{cid}").status_code == 200
    assert client.get(f"/api/conversations/{cid}").status_code == 404


def test_completed_turn_persists_text_and_statistics(client, monkeypatch):
    async def fake_run(provider, history, model, effort, state):
        state["content"] = "Network looks healthy."
        state["stats"].update(total_tokens=42, duration_seconds=.5)
        history.append({"role": "assistant", "content": state["content"]})
        yield {"type": "text", "text": state["content"]}

    monkeypatch.setattr(server, "run", fake_run)
    monkeypatch.setattr(server.app.state, "client", object())
    cid = client.post("/api/conversations").json()["id"]
    result = client.post("/api/chat", json=body(cid))
    assert result.status_code == 200
    events = [json.loads(line[6:]) for line in result.text.splitlines() if line.startswith("data: ")]
    assert events[-1] == {"type": "done"}
    # Rechecking D1 reads durable messages and provider history.
    store.initialize()
    saved = store.get(cid)
    assert saved["title"] == "Check the network"
    assert saved["messages"][1]["stats"]["total_tokens"] == 42
    assert saved["messages"][1]["stats"]["status"] == "completed"
    assert saved["history"][-1]["content"] == "Network looks healthy."
    assert server.busy is False
    server.app.state.client = None


@pytest.mark.parametrize("failure", [RuntimeError("Tool failed"), asyncio.CancelledError()])
def test_failed_or_cancelled_turn_drops_unpaired_tools(client, monkeypatch, failure):
    async def fake_run(provider, history, model, effort, state):
        history.append({"type": "function_call", "call_id": "unfinished", "name": "ping", "arguments": "{}"})
        state["content"] = "Investigating."
        yield {"type": "text", "text": state["content"]}
        raise failure

    monkeypatch.setattr(server, "run", fake_run)
    monkeypatch.setattr(server.app.state, "client", object())
    cid = store.create()["id"]

    async def consume():
        result = await server.chat(server.ChatRequest(**body(cid)))
        try:
            return [event async for event in result.body_iterator]
        except asyncio.CancelledError:
            return []

    asyncio.run(consume())
    saved = store.get(cid)
    assert [item["role"] for item in saved["history"]] == ["user", "assistant"]
    assert saved["messages"][1]["stats"]["status"] == ("cancelled" if isinstance(failure, asyncio.CancelledError) else "error")
    assert saved["messages"][1]["stats"]["usage_complete"] is False
    assert server.busy is False
    server.app.state.client = None


def test_chat_request_forbids_scenario_field(client):
    payload = body("unused")
    payload["scenario"] = "F1"
    assert client.post("/api/chat", json=payload).status_code == 422


def test_load_endpoint_reset_and_unknown_scenario(client, monkeypatch):
    monkeypatch.setattr(
        server.fault_control,
        "load_scenario",
        lambda sid: {
            "ok": True,
            "active": True,
            "scenario_id": sid,
            "runnable": ["F1"],
            "error": None,
        },
    )
    loaded = client.post("/api/scenario/load", json={"scenario": "F1"})
    assert loaded.status_code == 200
    assert loaded.json()["scenario_id"] == "F1"
    assert "ground_truth" not in loaded.json()
    assert client.post("/api/scenario/load", json={"scenario": "F9"}).status_code == 422
    monkeypatch.setattr(server, "busy", True)
    assert client.post("/api/scenario/load", json={"scenario": "F1"}).status_code == 409
    monkeypatch.setattr(server, "busy", False)
    monkeypatch.setattr(
        server.fault_control,
        "reset_scenario",
        lambda: {
            "ok": True,
            "active": False,
            "scenario_id": None,
            "runnable": ["F1"],
            "error": None,
        },
    )
    reset = client.post("/api/scenario/reset")
    assert reset.status_code == 200
    assert reset.json()["active"] is False


@pytest.mark.parametrize("scenario", ["F1", "F2", "F3", "F4", "F5"])
def test_load_endpoint_accepts_each_catalogue_scenario(client, monkeypatch, scenario):
    seen = []
    monkeypatch.setattr(
        server.fault_control,
        "load_scenario",
        lambda sid: seen.append(sid) or {
            "ok": True,
            "active": True,
            "scenario_id": sid,
            "runnable": ["F1", "F2", "F3", "F4", "F5"],
            "error": None,
        },
    )
    for raw in (scenario, scenario.lower()):
        loaded = client.post("/api/scenario/load", json={"scenario": raw})
        assert loaded.status_code == 200
        assert loaded.json()["scenario_id"] == scenario
    assert seen == [scenario, scenario]


def test_picker_offers_every_catalogue_scenario(client):
    page = client.get("/").text
    for scenario in ("F1", "F2", "F3", "F4", "F5"):
        assert f'<option value="{scenario}">' in page
    assert 'id="load-scenario" disabled' not in page
