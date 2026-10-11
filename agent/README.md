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
The sidebar is resizable and can be collapsed with its hamburger button; both
its width and collapsed state persist across page refreshes. Conversations can
be renamed from the list.

For automatic reload during development, start with:

```sh
COMS6200_AGENT_DEV=1 uv run --project agent python -m agent
```

You can also set `COMS6200_AGENT_DEV=1` in the root `.env`. It is off by default.
Python edits in the agent and its network modules restart the server. The
browser checks every two seconds for UI edits or a server restart and refreshes
when idle, with no unsent text. Python restarts can interrupt an active diagnosis;
saved conversations remain in D1. Set the flag to `0` and restart to disable it.

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

The UI includes a picker for F1–F5. Selecting a scenario immediately injects the chosen
catalogue fault on the live network (resetting any active catalogue fault first).
**Reset** clears it. The picker value is not sent in chat requests, stored as
assistant context, or added to the system prompt. Describe a symptom; do not name
the scenario. Start a new conversation after changing the fault.

All five scenarios use the same loop, prompt and tools. Example symptom prompts,
the evidence each fault exposes to the tools, and the operator-only expected
localisation are in the user manual under
[diagnosis sessions per scenario](../docs/user-guide.md#diagnosis-sessions-per-scenario-f1f5).
Test results: [LLM diagnosis test results](../docs/results/llm-diagnosis.md).

Check the load → tools → reset path for F1–F5 without model requests (root,
testbed running, no chat turn in progress):

```sh
./scripts/verify_agent_scenarios.sh        # or: ... F2 F4
```

F2's background load stays up until reset. Tool delays default to `0` and
`MAX_TOOL_CALLS` defaults to 14. Agent `iperf` calls stop only the gateway's own
port-5201 iperf3, so they no longer end the F2 load.

## Network access

Run on the Linux testbed host, beside the existing Mininet/ONOS installation
(Ubuntu server, Linux VM, or WSL2 Ubuntu 24.04 from a clone in the WSL
filesystem). On native Windows the UI opens but scenario loading / **Reset**
return HTTP 500 and the tools cannot reach Mininet. Session helper:
`./scripts/testbed.sh start`. Load F1–F5 from the UI or `./scripts/testbed.sh inject F1`.
The diagnostic tools, including `nmap` and `get_link_metrics`, call `telemetry.TelemetryGateway`. `get_link_metrics(sw, port)` returns a fixed two-second port measurement: rates, drop and error deltas, instantaneous queue backlog, and overlimit and requeue deltas. It does not return queue configuration. `nmap` scans one TCP or UDP port between two project hosts (primary IPv4, no host discovery, 5 s host timeout, 20 s limit) and returns protocol, state, and service name. Inject/reset is operator-only and is not an LLM tool.
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
end-to-end time. The default delay range is 0–0 seconds. Research runs keep
both `TOOL_DELAY_MIN_SECONDS` and `TOOL_DELAY_MAX_SECONDS` at `0`. The delay is excluded from observations
sent to the model. One turn runs at a time to avoid overlapping network probes.
Stop closes model streaming; an already-running bounded diagnostic finishes its
cleanup before another turn can start.

Defaults: 14 tool calls and 300 seconds per turn. The UI model default is
`gpt-5.6-sol` at reasoning effort `medium`. The per-turn token stop is
off (`MAX_TURN_TOKENS=0`). Set a positive value to restore it. A per-request
output cap of 8,192 tokens remains. This is not a billing cap; set gateway spend
limits for a financial cap. A final answer is requested after the tool budget is
exhausted.

The model picker lists GPT-6.1 Sol, GPT-6 Luna and GPT-6 Astra, with the
GPT-5.6 series inside an expandable **Deprecated** group. This is a UI grouping;
the legacy models remain selectable and the protocol default stays GPT-5.6 Sol.
GPT-6.1 Sol supports reasoning efforts `low` through `max`; GPT-6 Luna also
supports `none`. New model efforts and Standard cost estimates follow the
[Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol) and
[Luna](https://developers.openai.com/api/docs/models/gpt-6-luna) model pages,
reviewed on 2026-10-11.

Cloudflare D1 stores conversations, provider context, tool results and statistics.
Logfire receives model/tool timing spans and turn metrics when configured. Tool
observations may be exported to that Logfire project.

## Files

- `server.py`: routes and streamed turn lifecycle.
- `fault_control.py`: operator F1–F5 load/reset for the UI (not an LLM tool).
- `loop.py`: complete model/tool loop and measurements.
- `tools.py`: tool adapter around `TelemetryGateway`, including `nmap`.
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
