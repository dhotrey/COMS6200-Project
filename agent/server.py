"""Local FastAPI server. One active diagnostic turn protects shared probe state."""
import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager

import logfire
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from faults import state as fault_state

from . import config, topology_control, fault_control, store, tools, judge, benchmark
from .loop import run

busy = False
network_changing = False
DEV_STARTED = time.time_ns()


@asynccontextmanager
async def lifespan(app):
    app.state.explanation_lock = asyncio.Lock()
    await asyncio.to_thread(store.initialize)
    await asyncio.to_thread(store.interrupt_benchmarks)
    logfire.configure(service_name="network-agent", send_to_logfire="if-token-present",
                      console=False)
    app.state.client = config.make_client() if config.configured() else None
    app.state.benchmark = benchmark.Benchmark(app.state.client)
    if app.state.client:
        logfire.instrument_httpx(app.state.client.http, capture_all=False, capture_headers=False,
                                 capture_request_body=False, capture_response_body=False)
    try:
        yield
    finally:
        try:
            await app.state.benchmark.shutdown()
            await judge.shutdown()
            if app.state.client:
                await app.state.client.close()
        finally:
            await asyncio.to_thread(store.close)


app = FastAPI(lifespan=lifespan)


@app.get("/")
def index():
    return FileResponse(config.ROOT / "index.html")


@app.get("/results")
@app.get("/results.html")
def results():
    return FileResponse(config.ROOT / "results.html")


def benchmark_active():
    manager = getattr(app.state, "benchmark", None)
    return bool(manager and manager.active)


class BenchmarkVariant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str
    effort: str


class BenchmarkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    variants: list[BenchmarkVariant] = Field(min_length=1, max_length=50)
    concurrency: int = Field(default=3, ge=1, le=4)
    repeats: int = Field(default=benchmark.DEFAULT_REPEATS, ge=1, le=benchmark.MAX_REPEATS, strict=True)


@app.get("/api/benchmarks/config")
def benchmark_config():
    active = app.state.benchmark.active
    return {"variants": benchmark.variants(), "topologies": list(topology_control.TOPOLOGIES),
            "scenarios": list(benchmark.SCENARIOS), "configured": config.configured(),
            "repeats": {"default": benchmark.DEFAULT_REPEATS, "min": 1, "max": benchmark.MAX_REPEATS},
            "active_id": active["id"] if active else None,
            "active_run": {"id": active["id"], "status": active["status"],
                           "variants": active.get("variants", []), "repeats": active.get("repeats", 1),
                           "phase": active.get("phase")} if active else None}


@app.get("/api/benchmarks")
async def benchmark_listing():
    return [benchmark.public_run(item) for item in await asyncio.to_thread(store.benchmark_listing)]


@app.post("/api/benchmarks")
async def benchmark_start(body: BenchmarkRequest):
    if busy or network_changing or benchmark_active():
        raise HTTPException(409, "Wait for the current diagnosis, benchmark or network change to finish")
    try:
        return await app.state.benchmark.start([v.model_dump() for v in body.variants], body.concurrency, body.repeats)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get("/api/benchmarks/{run_id}")
async def benchmark_status(run_id: str):
    item = await asyncio.to_thread(store.get_benchmark, run_id, False)
    if not item:
        raise HTTPException(404, "Benchmark not found")
    if benchmark_active() and app.state.benchmark.active["id"] == run_id:
        item.update(app.state.benchmark.active)
    return benchmark.public_run(item)


@app.post("/api/benchmarks/{run_id}/stop")
async def benchmark_stop(run_id: str):
    manager = app.state.benchmark
    if not manager.active or manager.active["id"] != run_id:
        raise HTTPException(409, "This benchmark is no longer running")
    manager.stop()
    return {"status": manager.active["status"]}


@app.post("/api/benchmarks/{run_id}/pause")
async def benchmark_pause(run_id: str):
    manager = app.state.benchmark
    if not manager.active or manager.active["id"] != run_id:
        raise HTTPException(409, "This benchmark is no longer running")
    manager.stop(paused=True)
    return {"status": "pausing"}


@app.get("/api/benchmarks/{run_id}/export")
async def benchmark_export(run_id: str):
    item = await asyncio.to_thread(store.get_benchmark, run_id)
    if not item:
        raise HTTPException(404, "Benchmark not found")
    item.update(benchmark.run_costs(item["cells"]))
    item.setdefault("repeats", 1)
    item["matrix"] = benchmark.aggregate_cells(item["cells"])
    return item


@app.get("/api/benchmarks/{run_id}/cells/{cell_id}")
async def benchmark_cell(run_id: str, cell_id: str):
    cell = await asyncio.to_thread(store.get_benchmark_cell, run_id, cell_id)
    if not cell:
        raise HTTPException(404, "Benchmark cell not found")
    return benchmark.public_cell(cell, detail=True)


@app.post("/api/benchmarks/{run_id}/cells/{cell_id}/explain")
async def benchmark_explain(run_id: str, cell_id: str):
    cell = await asyncio.to_thread(store.get_benchmark_cell, run_id, cell_id)
    if cell and cell.get("conversation_id"):
        # Both views use the chat's existing job key and explanation lock.
        evaluation = await explain_evaluation(cell["conversation_id"], cell["message_id"])
        result = benchmark.public_cell(cell, detail=True)
        result["evaluation"] = evaluation
        return result
    try:
        return await app.state.benchmark.explain(run_id, cell_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


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
            "busy": busy or network_changing or benchmark_active()}


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
    messages = [{**m, "evaluation": judge.public(m.get("evaluation"))} for m in item["messages"]]
    return {**{k: v for k, v in item.items() if k != "history"}, "messages": messages,
            "settings": conversation_settings(item)}


async def message_evaluation(cid, message_id):
    item = await asyncio.to_thread(store.get, cid)
    if not item:
        raise HTTPException(404, "Conversation not found")
    message = next((m for m in item["messages"] if m.get("id") == message_id and m.get("role") == "assistant"), None)
    if not message or not message.get("evaluation"):
        raise HTTPException(404, "Evaluation not found")
    evaluation = message["evaluation"]
    live_benchmark_grade = (evaluation.get("status") == "pending" and benchmark_active()
                            and (message.get("benchmark") or {}).get("run_id") == app.state.benchmark.active["id"])
    if not live_benchmark_grade:
        evaluation = await judge.recover(cid, message_id, evaluation)
    if (cid, message_id, "explain") in judge.JOBS and not evaluation.get("explanation"):
        evaluation["explanation"] = {"status": "pending", "model": judge.EXPLAIN_MODEL, "effort": "high"}
    return evaluation


@app.get("/api/conversations/{cid}/messages/{message_id}/evaluation")
async def evaluation_status(cid: str, message_id: str):
    return judge.public(await message_evaluation(cid, message_id))


@app.post("/api/conversations/{cid}/messages/{message_id}/evaluation/explain")
async def explain_evaluation(cid: str, message_id: str):
    async with app.state.explanation_lock:
        return await _explain_evaluation(cid, message_id)


async def _explain_evaluation(cid, message_id):
    evaluation = await message_evaluation(cid, message_id)
    if evaluation["status"] != "completed":
        raise HTTPException(409, "Wait for a completed evaluation before explaining it")
    result = evaluation.get("explanation") or {}
    if result.get("status") in {"pending", "completed"}:
        return judge.public(evaluation)
    if not app.state.client:
        raise HTTPException(503, "Configure the AI Gateway and restart the server.")
    # Reserve synchronously before yielding, so repeated clicks cannot bill twice.
    evaluation["explanation"] = {"status": "pending", "model": judge.EXPLAIN_MODEL, "effort": "high"}
    judge.launch(cid, message_id, "explain", judge.explain(app.state.client, cid, message_id, evaluation))
    return judge.public(evaluation)


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
    if busy or benchmark_active():
        raise HTTPException(409, "Stop the current turn or benchmark before deleting a conversation")
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
    if busy or network_changing or benchmark_active():
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
    if benchmark_active():
        raise HTTPException(409, "Wait for the benchmark to finish or stop it before chatting")
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
    if busy or network_changing or benchmark_active():
        raise HTTPException(409, "Another diagnostic turn is running. Wait for it to finish.")
    # D1 lookup yielded: setup may have failed while the conversation was read.
    if topology_control.error:
        raise HTTPException(409, "Reload a topology before diagnosing: " + topology_control.error)
    settings = {"model": body.model, "effort": body.effort, **network_settings()}
    saved_settings = conversation_settings(item)
    if item["messages"] and saved_settings != settings:
        raise HTTPException(409, "This chat's settings or network differ. Start a new conversation to change them.")
    evaluation = judge.prepare(settings, body.message.strip(), item["messages"])
    message_id = uuid.uuid4().hex
    busy = True

    async def events():
        global busy
        nonlocal evaluation
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
            if completed:
                evaluation["answer"] = state["content"]
            else:
                evaluation = {"status": "skipped", "reason": "Diagnosis did not complete."}
            assistant = {"id": message_id, "role": "assistant", **state, "settings": settings,
                         "evaluation": evaluation}
            try:
                await asyncio.to_thread(
                    store.save, body.conversation_id, user, assistant, history
                )
                if completed and evaluation["status"] == "pending":
                    judge.launch(body.conversation_id, message_id, "judge",
                                 judge.evaluate(app.state.client, body.conversation_id, message_id, evaluation))
            finally:
                busy = False
        yield "data: " + json.dumps({"type": "evaluation", "message_id": message_id,
                                    "evaluation": judge.public(evaluation)}) + "\n\n"
        yield "data: " + json.dumps({"type": "stats", "stats": state["stats"]}) + "\n\n"
        yield 'data: {"type":"done"}\n\n'

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
