# Network Lab

Small conversational debugging harness: vanilla HTML chat, FastAPI, one OpenAI
Responses tool loop, existing telemetry tools, and Cloudflare D1. No LangChain,
RAG, ingestion, frontend dependencies, or additional local services.

From the repository root:

```sh
uv sync --project agent
uv run --project agent python -m agent
```

`python -m agent` re-executes with sudo so ping/iperf can enter Mininet
namespaces. It loads the root `.env` and defaults ONOS REST to `onos` / `rocks`
if those variables are unset. Stop any previous non-root agent process first.

Open http://127.0.0.1:8000. Opening `index.html` directly is a preview only:
model/thinking pickers work, but chat and saved history require the server. With
D1 configured, the UI and history work without AI Gateway credentials; sending
messages requires AI Gateway configuration. Keep one server process/worker.
Assistant replies render Markdown. Tool calls are faint until hovered or clicked.
The sidebar is resizable, and conversations can be renamed from the list.

## Credentials

Add the entries from `.env.example` to the **repository-root `.env`**.
Existing environment variables take precedence. Restart after configuration changes.

- `CLOUDFLARE_ACCOUNT_ID`: account ID.
- `CLOUDFLARE_API_TOKEN`: account API token with D1 Write access.
- `CLOUDFLARE_D1_DATABASE_ID`: UUID of the D1 database used for chat storage.
- `CLOUDFLARE_AI_GATEWAY_ID`: gateway name/ID.
- `CLOUDFLARE_AI_GATEWAY_API_TOKEN`: authenticated gateway token.
- Store your **OpenAI API key in Cloudflare AI Gateway BYOK**; it is not needed locally.
- `CLOUDFLARE_BYOK_ALIAS`: optional stored-key alias (otherwise Cloudflare's default).
- `LOGFIRE_TOKEN`: optional Logfire project write token. Missing means export disabled.
- Existing `ONOS_USER` / `ONOS_PASSWORD` configure telemetry; never sent to the model.
  If omitted, the harness uses the reference lab pair `onos` / `rocks`. You can also
  put them in the root `.env`.

The D1 account token and AI Gateway authentication token are different
credentials. Do not substitute `CLOUDFLARE_AI_GATEWAY_API_TOKEN` for
`CLOUDFLARE_API_TOKEN`.

The server sends requests to the gateway's `/openai/responses` endpoint. Provider
Authorization is omitted so Cloudflare supplies its stored key. Gateway response
caching is bypassed. No automatic retries hide extra calls or delays.

## Cloudflare D1

The harness follows the same official Cloudflare Python SDK pattern used by
Kirana. Apply and verify the idempotent schema before first launch:

```sh
uv run --project agent python -m agent.setup_d1
```

The command creates `conversations` and `messages`, the message lookup index, and
the cascading foreign key. No seed rows are required. The server runs the same
schema check at startup and refuses to start if D1 is unavailable or malformed.

Conversation creation, history, tool results, and turn statistics now go only to
D1. The ignored legacy `agent/chat.sqlite3` is not read, migrated, or deleted.

## Fault scenario picker

The UI includes a picker for F1–F5. **Load scenario** injects the chosen
catalogue fault on the live network (resetting any active catalogue fault first).
**Reset** clears it. The picker value is not sent in chat requests, stored as
assistant context, or added to the system prompt. Describe a symptom; do not name
the scenario. Start a new conversation after changing the fault.

## Network access

Run beside the existing Mininet/ONOS installation. Session helper:
`./scripts/testbed.sh start`. Load F1–F5 from the UI or `./scripts/testbed.sh inject F1`.
The six tools directly use `telemetry.TelemetryGateway`; `nmap` returns
`NOT_IMPLEMENTED`. Inject/reset is operator-only and is not an LLM tool.
Start a new conversation after changing the fault.

Host probes require access to Mininet namespaces, usually root. `python -m agent`
now re-executes with sudo and preserves ONOS plus Cloudflare variables. To skip
that (tests or an already-privileged process), set `COMS6200_AGENT_NO_SUDO=1`.
Keep the UI bound to loopback; this local research app has no authentication.
Use an SSH tunnel for remote access.

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

Defaults: 10 tool calls and 300 seconds per turn. The per-turn token stop is
off (`MAX_TURN_TOKENS=0`). Set a positive value to restore it. A per-request
output cap of 8,192 tokens remains. This is not a billing cap; set gateway spend
limits for a financial cap. A final answer is requested after the tool budget is
exhausted.

Cloudflare D1 stores conversations, provider context, tool results and statistics.
Logfire receives model/tool timing spans and turn metrics when configured. Tool
observations may be exported to that Logfire project.

## Files

- `server.py`: routes and streamed turn lifecycle.
- `fault_control.py`: operator F1–F5 load/reset for the UI (not an LLM tool).
- `loop.py`: complete model/tool loop and measurements.
- `tools.py`: existing tool adapter and nmap placeholder.
- `store.py`, `d1_schema.py`: D1 persistence and idempotent schema.
- `setup_d1.py`: explicit D1 schema setup and verification command.
- `config.py`, `prompt.md`: settings and editable system instructions.
- `index.html`: entire frontend (Markdown rendering, resizable sidebar, rename).

```sh
uv run --project agent python -m pytest agent/tests
```

Tests use fake model responses, mocked tools, and an in-memory D1-dialect test
double; they do not call Cloudflare, spend API credits, or change a network. Live
gateway/D1/Logfire and Mininet integration require configured services and are
separate from those tests.
