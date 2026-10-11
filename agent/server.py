"""Local FastAPI server. One active diagnostic turn protects shared probe state."""
import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager

import logfire
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from faults import state as fault_state

from . import config, topology_control, fault_control, store, tools
from .loop import run

busy = False
network_changing = False
DEV_STARTED = time.time_ns()


@asynccontextmanager
async def lifespan(app):
    await asyncio.to_thread(store.initialize)
    logfire.configure(service_name="network-agent", send_to_logfire="if-token-present",
                      console=False)
    app.state.client = config.make_client() if config.configured() else None
    if app.state.client:
        logfire.instrument_httpx(app.state.client.http, capture_all=False, capture_headers=False,
                                 capture_request_body=False, capture_response_body=False)
    try:
        yield
    finally:
        try:
            if app.state.client:
                await app.state.client.close()
        finally:
            await asyncio.to_thread(store.close)


app = FastAPI(lifespan=lifespan)


@app.get("/")
def index():
    return FileResponse(config.ROOT / "index.html")


@app.get("/api/config")
def settings():
    payload = {"configured": config.configured(), "models": config.MODELS,
               "dev_mode": config.dev_mode(),
               "default_model": config.MODELS[0]["id"],
               "default_effort": config.MODELS[0]["efforts"][0]}
    payload.update(config.runtime_limits())
    return payload


@app.get("/api/dev-version")
def dev_version():
    if not config.dev_mode():
        raise HTTPException(404, "Development reload is disabled")
    return {"version": f"{DEV_STARTED}:{(config.ROOT / 'index.html').stat().st_mtime_ns}",
            "busy": busy or network_changing}


@app.get("/api/conversations")
def conversations():
    return store.listing()


@app.post("/api/conversations")
def create():
    return store.create()


@app.get("/api/conversations/{cid}")
def conversation(cid: str):
    item = store.get(cid)
    if not item:
        raise HTTPException(404, "Conversation not found")
    return {**{k: v for k, v in item.items() if k != "history"},
            "settings": conversation_settings(item)}


def conversation_settings(item: dict) -> dict | None:
    """Operator-only metadata lives in message payloads, never provider history."""
    for message in item["messages"]:
        if message.get("settings"):
            return message["settings"]
    # Older chats have model statistics but no recorded network selection.
    for message in item["messages"]:
        stats = message.get("stats") or {}
        if stats.get("model"):
            return {"model": stats["model"], "effort": stats.get("effort")}
    return None


def network_settings() -> dict:
    try:
        active_fault = fault_state.active_state() or {}
    except fault_state.StateError as exc:
        raise HTTPException(409, "Cannot read the current fault state; reload the network.") from exc
    return {"topology": topology_control.active.TOPOLOGY,
            "scenario": active_fault.get("scenario_id")}


@app.delete("/api/conversations/{cid}")
async def delete(cid: str):
    if busy:
        raise HTTPException(409, "Stop the current turn before deleting a conversation")
    await asyncio.to_thread(store.delete, cid)
    return {"ok": True}


class RenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=80)


@app.patch("/api/conversations/{cid}")
def rename(cid: str, body: RenameRequest):
    title = " ".join(body.title.split())
    if not title:
        raise HTTPException(422, "Title cannot be empty")
    item = store.rename(cid, title[:80])
    if not item:
        raise HTTPException(404, "Conversation not found")
    return item


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: str
    message: str = Field(min_length=1, max_length=16000)
    model: str
    effort: str


class LoadScenarioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: str = Field(min_length=2, max_length=2)
    topology: str | None = None


class LoadTopologyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topology: str


async def change_network(function, *args):
    """Reserve network access before yielding; finish cleanup on disconnect."""
    global network_changing
    if busy or network_changing:
        raise HTTPException(409, "Wait for the current diagnosis or network change to finish")
    network_changing = True
    worker = asyncio.create_task(asyncio.to_thread(function, *args))
    cancelled = False
    try:
        # As with diagnostic tool threads, cancellation cannot stop setup.
        # Retain the reservation until it finishes, even after repeated cancels.
        while not worker.done():
            try:
                await asyncio.sleep(.05)
            except asyncio.CancelledError:
                cancelled = True
        if cancelled:
            if not worker.cancelled():
                worker.exception()  # Consume a setup error after disconnect.
            raise asyncio.CancelledError
        try:
            return worker.result()
        except RuntimeError as exc:
            code = 503 if "root" in str(exc).lower() else 409
            raise HTTPException(code, str(exc)) from exc
    finally:
        try:
            tools.refresh_tools()
        finally:
            network_changing = False


def require_topology(name: str | None) -> None:
    if name is not None and name not in topology_control.active.SPECS:
        raise HTTPException(422, "topology must be main6s8h, ring5s5h or tree5s8h")


def _scenario_http(result: dict) -> dict:
    if result.get("ok"):
        return result
    message = result.get("error") or "scenario change failed"
    status_code = 503 if "root" in message.lower() else 409
    raise HTTPException(status_code, message)


@app.get("/api/scenario")
def scenario_status():
    return fault_control.public_status()


@app.post("/api/topology/load")
async def topology_load(body: LoadTopologyRequest):
    require_topology(body.topology)
    def load():
        topology_control.load_topology(body.topology)
        return fault_control.reset_scenario()
    return _scenario_http(await change_network(load))


@app.post("/api/scenario/load")
async def scenario_load(body: LoadScenarioRequest):
    require_topology(body.topology)
    scenario = body.scenario.strip().upper()
    if scenario not in fault_control.RUNNABLE:
        raise HTTPException(422, "scenario must be F1–F5")
    args = (scenario,) if body.topology is None else (scenario, body.topology)
    return _scenario_http(await change_network(fault_control.load_scenario, *args))


@app.post("/api/scenario/reset")
async def scenario_reset():
    return _scenario_http(await change_network(fault_control.reset_scenario))


@app.post("/api/chat")
async def chat(body: ChatRequest):
    global busy
    if network_changing:
        raise HTTPException(409, "Wait for the topology or fault change to finish")
    if topology_control.error:
        raise HTTPException(409, "Reload a topology before diagnosing: " + topology_control.error)
    if not app.state.client:
        raise HTTPException(503, "Configure Cloudflare credentials in the root .env and restart the server.")
    if not body.message.strip():
        raise HTTPException(422, "Message cannot be empty")
    option = next((m for m in config.MODELS if m["id"] == body.model), None)
    if not option or body.effort not in option["efforts"]:
        raise HTTPException(422, "Unsupported model or reasoning effort")
    item = await asyncio.to_thread(store.get, body.conversation_id)
    if item is None:
        raise HTTPException(404, "Conversation not found")
    if busy or network_changing:
        raise HTTPException(409, "Another diagnostic turn is running. Wait for it to finish.")
    # D1 lookup yielded: setup may have failed while the conversation was read.
    if topology_control.error:
        raise HTTPException(409, "Reload a topology before diagnosing: " + topology_control.error)
    settings = {"model": body.model, "effort": body.effort, **network_settings()}
    saved_settings = conversation_settings(item)
    if item["messages"] and saved_settings != settings:
        raise HTTPException(409, "This chat's settings or network differ. Start a new conversation to change them.")
    busy = True

    async def events():
        global busy
        state = {"content": "", "tools": [], "stats": {}}
        user = {"role": "user", "content": body.message.strip()}
        history = [*item["history"], user]
        completed = False
        try:
            yield "data: " + json.dumps({"type": "settings", "settings": settings}) + "\n\n"
            with logfire.span("chat turn", conversation_id=body.conversation_id) as span:
                async for event in run(app.state.client, history, body.model, body.effort, state):
                    yield "data: " + json.dumps(event) + "\n\n"
                completed = True
                state["stats"]["status"] = "completed"
                span.set_attributes(state["stats"])
        except asyncio.CancelledError:
            state["stats"].update(status="cancelled", usage_complete=False)
            raise
        except Exception as exc:
            # Do not expose SDK request headers or upstream error bodies.
            message = str(exc) if isinstance(exc, (RuntimeError, TimeoutError)) else "Request failed; check gateway configuration and server logs."
            if not message:
                message = "Turn time limit reached."
            logging.getLogger(__name__).warning("Chat failed: %s", type(exc).__name__)
            state["stats"].update(status="error", usage_complete=False)
            state["content"] += "\n\n" + message
            yield "data: " + json.dumps({"type": "error", "message": message}) + "\n\n"
        finally:
            if not completed:
                # Discard incomplete provider tool-call pairs, retain visible chat for follow-up.
                history = [*item["history"], user]
                if state["content"]:
                    history.append({"role": "assistant", "content": state["content"]})
            assistant = {"role": "assistant", **state, "settings": settings}
            try:
                await asyncio.to_thread(
                    store.save, body.conversation_id, user, assistant, history
                )
            finally:
                busy = False
        yield "data: " + json.dumps({"type": "stats", "stats": state["stats"]}) + "\n\n"
        yield 'data: {"type":"done"}\n\n'

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
