"""API persistence and failed/interrupted turn cleanup, all offline."""
import asyncio
import json
import os
import sqlite3
import sys
import threading

import pytest
from fastapi.testclient import TestClient

from agent import server, store


class SQLiteD1:
    """D1-compatible persistence double for offline API tests.

    The TestClient thread and ``asyncio.to_thread`` share this connection.
    SQLite raises "cannot commit transaction - SQL statements in progress"
    when those calls overlap, which the full suite can trigger even though
    the same test passes alone. One lock keeps the statements ordered.
    """

    def __init__(self):
        self.connection = sqlite3.connect(":memory:", check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._lock = threading.Lock()

    def query(self, sql, params=None):
        with self._lock, self.connection:
            cursor = self.connection.execute(sql, params or [])
            return [dict(row) for row in cursor.fetchall()]

    def batch(self, statements):
        results = []
        with self._lock, self.connection:
            for sql, params in statements:
                cursor = self.connection.execute(sql, params)
                results.append([dict(row) for row in cursor.fetchall()])
        return results

    def close(self):
        with self._lock:
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
    monkeypatch.setattr(server, "network_changing", False)
    monkeypatch.setattr(server.fault_state, "active_state", lambda: None)
    backend_options = ({"loop_factory": _wakeful_loop_factory}
                       if sys.version_info >= (3, 14) else {})
    with TestClient(server.app, backend_options=backend_options) as client:
        yield client


def body(cid):
    return {"conversation_id": cid, "message": "Check the network", "model": "gpt-5.6-luna", "effort": "medium"}


def test_missing_credentials_and_conversation_crud(client):
    cfg = client.get("/api/config").json()
    assert cfg["configured"] is False
    assert cfg["default_model"] == cfg["models"][0]["id"] == "gpt-6.1-sol"
    assert cfg["default_effort"] == cfg["models"][0]["efforts"][0] == "low"
    mini = next(m for m in cfg["models"] if m["id"] == "gpt-4.1-mini")
    assert mini["efforts"] == ["none"] and not mini.get("deprecated")
    assert cfg["max_tool_calls"] == 14
    assert cfg["max_turn_seconds"] == 300
    assert cfg["tool_delay_min_seconds"] == 0
    assert cfg["tool_delay_max_seconds"] == 0
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


@pytest.mark.parametrize("model,effort", [
    ("gpt-5.6-luna", "medium"),
    ("gpt-6.1-sol", "medium"),
    ("gpt-6-luna", "none"),
    ("gpt-4.1-mini", "none"),
])
def test_completed_turn_persists_text_and_statistics(client, monkeypatch, model, effort):
    seen = []

    async def fake_run(provider, history, model, effort, state):
        seen.append((model, effort))
        state["content"] = "Network looks healthy."
        state["stats"].update(total_tokens=42, duration_seconds=.5)
        history.append({"role": "assistant", "content": state["content"]})
        yield {"type": "text", "text": state["content"]}

    monkeypatch.setattr(server, "run", fake_run)
    monkeypatch.setattr(server.app.state, "client", object())
    cid = client.post("/api/conversations").json()["id"]
    result = client.post("/api/chat", json={**body(cid), "model": model, "effort": effort})
    assert result.status_code == 200
    assert seen == [(model, effort)]
    events = [json.loads(line[6:]) for line in result.text.splitlines() if line.startswith("data: ")]
    assert events[-1] == {"type": "done"}
    # Rechecking D1 reads durable messages and provider history.
    store.initialize()
    saved = store.get(cid)
    assert saved["title"] == "Check the network"
    assert saved["messages"][1]["stats"]["total_tokens"] == 42
    assert saved["messages"][1]["stats"]["status"] == "completed"
    assert saved["messages"][1]["evaluation"]["status"] == "skipped"
    assert saved["history"][-1]["content"] == "Network looks healthy."
    assert server.busy is False
    server.app.state.client = None


@pytest.mark.parametrize("model,effort", [
    ("gpt-6.1-sol", "none"),
    ("gpt-4.1-mini", "medium"),
])
def test_rejects_unsupported_effort(client, monkeypatch, model, effort):
    monkeypatch.setattr(server.app.state, "client", object())
    cid = client.post("/api/conversations").json()["id"]
    result = client.post("/api/chat", json={
        **body(cid), "model": model, "effort": effort,
    })
    assert result.status_code == 422
    assert store.get(cid)["messages"] == []
    server.app.state.client = None


@pytest.mark.parametrize("changed", ["model", "effort", "topology", "scenario"])
def test_started_chat_keeps_settings_and_network(client, monkeypatch, changed):
    network = {"topology": "ring5s5h", "scenario": "F1"}
    monkeypatch.setattr(server, "network_settings", lambda: dict(network))
    monkeypatch.setattr(server.app.state, "client", object())
    seen = []

    async def fake_run(provider, history, model, effort, state):
        seen.append((model, effort))
        # Fault/operator metadata must never enter the model's input.
        assert all("settings" not in message for message in history)
        assert "F1" not in json.dumps(history)
        state["content"] = "Inspecting link status."
        history.append({"role": "assistant", "content": state["content"]})
        yield {"type": "text", "text": state["content"]}

    monkeypatch.setattr(server, "run", fake_run)
    cid = client.post("/api/conversations").json()["id"]
    assert client.post("/api/chat", json=body(cid)).status_code == 200
    expected = {"model": body(cid)["model"], "effort": "medium", **network}
    reopened = client.get(f"/api/conversations/{cid}").json()
    assert reopened["settings"] == expected
    assert reopened["messages"][1]["settings"] == expected
    assert "F1" not in json.dumps(store.get(cid)["history"])
    assert client.post("/api/chat", json=body(cid)).status_code == 200
    request = body(cid)
    if changed == "model":
        request["model"] = "gpt-6.1-sol"
    elif changed == "effort":
        request["effort"] = "high"
    elif changed == "topology":
        network["topology"] = "tree5s8h"
    else:
        network["scenario"] = "F2"
    rejected = client.post("/api/chat", json=request)
    assert rejected.status_code == 409
    assert "new conversation" in rejected.json()["detail"]
    assert len(store.get(cid)["messages"]) == 4
    new_cid = client.post("/api/conversations").json()["id"]
    assert client.post("/api/chat", json={**request, "conversation_id": new_cid}).status_code == 200
    assert len(seen) == 3
    assert server.busy is False
    server.app.state.client = None


def test_legacy_chat_is_readable_but_requires_new_chat(client, monkeypatch):
    cid = client.post("/api/conversations").json()["id"]
    user = {"role": "user", "content": "Previous diagnosis"}
    assistant = {"role": "assistant", "content": "Old result",
                 "stats": {"model": "gpt-5.6-luna", "effort": "medium"}}
    store.save(cid, user, assistant, [user, {"role": "assistant", "content": "Old result"}])
    assert client.get(f"/api/conversations/{cid}").json()["settings"] == assistant["stats"]
    monkeypatch.setattr(server.app.state, "client", object())
    assert client.post("/api/chat", json=body(cid)).status_code == 409
    server.app.state.client = None


def test_model_catalogue_groups_legacy_models(client):
    models = client.get("/api/config").json()["models"]
    assert [m["id"] for m in models if not m.get("deprecated")] == [
        "gpt-6.1-sol", "gpt-6-luna", "gpt-6-astra",
        "gpt-4.1-mini", "gpt-4.1-nano",
    ]
    assert {m["id"] for m in models if m.get("deprecated")} == {
        "gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol",
    }


def test_picker_defaults_follow_catalogue_order(client, monkeypatch):
    models = [dict(server.config.MODELS[1], efforts=["high", "none"]),
              server.config.MODELS[0]]
    monkeypatch.setattr(server.config, "MODELS", models)
    cfg = client.get("/api/config").json()
    assert cfg["default_model"] == "gpt-6-luna"
    assert cfg["default_effort"] == "high"


def test_development_version_tracks_ui_and_server_changes(client, monkeypatch, tmp_path):
    monkeypatch.setenv("COMS6200_AGENT_DEV", "0")
    assert client.get("/api/config").json()["dev_mode"] is False
    assert client.get("/api/dev-version").status_code == 404
    monkeypatch.setenv("COMS6200_AGENT_DEV", "1")
    assert client.get("/api/config").json()["dev_mode"] is True
    page = tmp_path / "index.html"
    page.write_text("Preview")
    monkeypatch.setattr(server.config, "ROOT", tmp_path)
    first = client.get("/api/dev-version").json()
    assert first["busy"] is False
    stamp = page.stat().st_mtime_ns + 1_000_000_000
    os.utime(page, ns=(stamp, stamp))
    edited = client.get("/api/dev-version").json()
    assert edited["version"] != first["version"]
    monkeypatch.setattr(server, "DEV_STARTED", server.DEV_STARTED + 1)
    monkeypatch.setattr(server, "busy", True)
    restarted = client.get("/api/dev-version").json()
    assert restarted["version"] != edited["version"]
    assert restarted["busy"] is True


@pytest.mark.parametrize("failure", [RuntimeError("Tool failed"), asyncio.CancelledError()])
def test_failed_or_cancelled_turn_drops_unpaired_tools(client, monkeypatch, failure):
    monkeypatch.setattr(server, "network_settings", lambda: {"topology": "main6s8h", "scenario": "F1"})
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
    assert saved["messages"][1]["evaluation"]["status"] == "skipped"
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
    assert 'id="load-scenario"' not in page
    assert 'id="reset-scenario"' in page


def test_load_topology_and_fault_passes_selection(client, monkeypatch):
    seen = []
    monkeypatch.setattr(server.fault_control, "load_scenario", lambda sid, topology:
        seen.append((topology, sid)) or {"ok": True, "topology": topology, "scenario_id": sid})
    for topology in ("main6s8h", "ring5s5h", "tree5s8h"):
        response = client.post("/api/scenario/load", json={"topology": topology, "scenario": "f3"})
        assert response.status_code == 200
        assert response.json()["topology"] == topology
    assert seen == [(t, "F3") for t in ("main6s8h", "ring5s5h", "tree5s8h")]
    assert client.post("/api/scenario/load", json={"topology": "unknown", "scenario": "F1"}).status_code == 422
    assert client.post("/api/topology/load", json={"topology": "unknown"}).status_code == 422


def test_healthy_topology_load_resets_fault(client, monkeypatch):
    seen = []
    monkeypatch.setattr(server.topology_control, "load_topology", lambda name: seen.append(name))
    monkeypatch.setattr(server.fault_control, "reset_scenario", lambda:
        seen.append("reset") or {"ok": True, "active": False})
    assert client.post("/api/topology/load", json={"topology": "tree5s8h"}).status_code == 200
    assert seen == ["tree5s8h", "reset"]
    monkeypatch.setattr(server, "network_changing", True)
    assert client.post("/api/topology/load", json={"topology": "ring5s5h"}).status_code == 409
    assert client.post("/api/scenario/reset").status_code == 409
    assert client.post("/api/chat", json=body("unused")).status_code == 409
    assert seen == ["tree5s8h", "reset"]


def test_failed_topology_load_blocks_diagnosis(client, monkeypatch):
    monkeypatch.setattr(server.topology_control, "error", "setup failed")
    assert client.post("/api/chat", json=body("unused")).status_code == 409


def test_network_change_lock_survives_disconnect(monkeypatch):
    import threading
    started, finish = threading.Event(), threading.Event()
    monkeypatch.setattr(server, "busy", False)
    monkeypatch.setattr(server, "network_changing", False)

    def setup():
        started.set()
        finish.wait(timeout=2)
        return {"ok": True}

    async def check():
        task = asyncio.create_task(server.change_network(setup))
        try:
            for _ in range(200):
                if started.is_set():
                    break
                await asyncio.sleep(.01)
            assert started.is_set()
            assert server.network_changing is True
            task.cancel()
            await asyncio.sleep(.01)
            task.cancel()
            await asyncio.sleep(.01)
            assert not task.done()
            assert server.network_changing is True
        finally:
            finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert server.network_changing is False
    asyncio.run(check())
