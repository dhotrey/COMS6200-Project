"""API persistence and failed/interrupted turn cleanup, all offline."""
import asyncio
import json
import sys

import pytest
from fastapi.testclient import TestClient

from agent import server, store


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
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_DB_PATH", str(tmp_path / "chat.sqlite3"))
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
    # Reopening the SQLite connection reads durable messages and model history.
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
