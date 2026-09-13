# Network Lab

Small conversational debugging harness: vanilla HTML chat, FastAPI, one OpenAI
Responses tool loop, existing telemetry tools, and SQLite. No LangChain, RAG,
ingestion, frontend dependencies, or additional services.

From the repository root:

```sh
uv sync --project agent
uv run --project agent python -m agent
```

Open http://127.0.0.1:8000. Opening `index.html` directly is a preview only:
model/thinking pickers work, but chat and saved history require the server. The UI and history work without credentials; sending
messages requires Cloudflare configuration. Keep one server process/worker.

## Credentials

Add the entries from `.env.example` to the **repository-root `.env`**.
Existing environment variables take precedence. Restart after configuration changes.

- `CLOUDFLARE_ACCOUNT_ID`: account ID.
- `CLOUDFLARE_AI_GATEWAY_ID`: gateway name/ID.
- `CLOUDFLARE_AI_GATEWAY_API_TOKEN`: authenticated gateway token.
- Store your **OpenAI API key in Cloudflare AI Gateway BYOK**; it is not needed locally.
- `CLOUDFLARE_BYOK_ALIAS`: optional stored-key alias (otherwise Cloudflare's default).
- `LOGFIRE_TOKEN`: optional Logfire project write token. Missing means export disabled.
- Existing `ONOS_USER` / `ONOS_PASSWORD` configure telemetry; never sent to the model.

The server sends requests to the gateway's `/openai/responses` endpoint. Provider
Authorization is omitted so Cloudflare supplies its stored key. Gateway response
caching is bypassed. No automatic retries hide extra calls or delays.

## Fault scenario picker

The UI includes a preview picker for F1–F5. **Load scenario is disabled** until
operator fault injection is connected. Selection is browser-only: it is not sent
in chat requests, saved as conversation context, or applied to the network.
For now, inject/reset faults separately using the existing operator workflow.

## Network access

Run beside the existing Mininet/ONOS installation. Start the topology and baseline
using the root user manual. The six tools directly use `telemetry.TelemetryGateway`;
`nmap` returns `NOT_IMPLEMENTED`. There is no fault-state/injector access in the agent.
Inject/reset scenarios separately; start a new conversation for an independent run.

Host probes require access to Mininet namespaces, usually root. If needed, launch
with the same configured environment and `sudo --preserve-env=ONOS_USER,ONOS_PASSWORD agent/.venv/bin/python -m agent` from the root. Keep the UI bound to loopback;
this local research app has no authentication. Use an SSH tunnel for remote access.

## Measurements and limits

Every assistant turn stores elapsed time, first visible token latency, per-request
latency, input/output/cached/reasoning tokens, estimated USD cost, model identifier,
reasoning effort, prompt hash, tool count and invalid-call count. Usage is summed
across all completed model calls. Reasoning tokens are a subset of output tokens;
cached tokens are a subset of input. Cost is an estimate using the dated price
constants in `config.py`, not a Cloudflare invoice. Failed/cancelled requests may
have unreported usage and are marked incomplete.

Each tool records arguments, result/error, execution time, artificial delay and
end-to-end time. `time.sleep(random.uniform(1,10))` runs in a worker thread by
default. Set both `TOOL_DELAY_MIN_SECONDS` and `TOOL_DELAY_MAX_SECONDS` to `0`
before collecting actual research timings. The delay is excluded from observations
sent to the model. One turn runs at a time to avoid overlapping network probes.
Stop closes model streaming; an already-running bounded diagnostic finishes its
cleanup before another turn can start.

Defaults: 10 tool calls, 300 seconds, 32,000 reported tokens per turn. A token
threshold stops subsequent requests and bounds output; it is not a hard billing
cap because each request also incurs input tokens. Set gateway spend limits for a
financial cap. A final answer is requested after the tool budget is exhausted.

`agent/chat.sqlite3` (Git-ignored) stores conversations, provider context, tool
results and statistics. Logfire receives model/tool timing spans and turn metrics
when configured. Tool observations may be exported to that Logfire project.

## Files

- `server.py`: routes and streamed turn lifecycle.
- `loop.py`: complete model/tool loop and measurements.
- `tools.py`: existing tool adapter and nmap placeholder.
- `store.py`: SQLite persistence.
- `config.py`, `prompt.md`: settings and editable system instructions.
- `index.html`: entire frontend.

```sh
uv run --project agent python -m pytest agent/tests
```

Tests use fake model responses and mocked tools; they do not spend API credits or
change a network. Live gateway/Logfire and Mininet integration require configured
services and are separate from those tests.
