"""Local FastAPI server. One active diagnostic turn protects shared probe state."""
import asyncio
import json
import logging
from contextlib import asynccontextmanager

import logfire
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import config, store
from .loop import run

busy = False


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
    return {"configured": config.configured(), "models": config.MODELS,
            "default_model": "gpt-5.6-luna", "default_effort": "medium"}


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
    return {k: v for k, v in item.items() if k != "history"}


@app.delete("/api/conversations/{cid}")
async def delete(cid: str):
    if busy:
        raise HTTPException(409, "Stop the current turn before deleting a conversation")
    await asyncio.to_thread(store.delete, cid)
    return {"ok": True}


class ChatRequest(BaseModel):
    conversation_id: str
    message: str = Field(min_length=1, max_length=16000)
    model: str
    effort: str


@app.post("/api/chat")
async def chat(body: ChatRequest):
    global busy
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
    if busy:
        raise HTTPException(409, "Another diagnostic turn is running. Wait for it to finish.")
    busy = True

    async def events():
        global busy
        state = {"content": "", "tools": [], "stats": {}}
        user = {"role": "user", "content": body.message.strip()}
        history = [*item["history"], user]
        completed = False
        try:
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
            assistant = {"role": "assistant", **state}
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
