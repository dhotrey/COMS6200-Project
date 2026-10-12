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

## Automatic diagnosis assessment

After a successfully completed answer with F1–F5 selected, the backend automatically
uses the OpenAI **Decisions API** (`gpt-6-luna`) to compare the final answer with
the captured `judge/<topology>/Fault<id>.md` rubric and shared `judge/grading.md`.
The user question and earlier visible exchanges are supplied as reference context;
tool traces are not supplied. Only the final primary diagnosis receives credit.

The answer shows **Analysing answer…**, then **Correct** (green tick), **Mostly
correct** (yellow circle), **Partially correct** (orange circle) or **Incorrect**
(red cross), followed by the corresponding criteria text. Healthy scenarios and
failed/cancelled diagnoses are not graded. A refusal, malformed result, timeout
or provider error shows **Evaluation failed**, rather than an incorrect verdict.

**▶ Explain decision** opens a separate evaluation panel and calls GPT-6.1 Sol
with `high` thinking, without diagnostic tools. It receives the question, diagnosis,
topology/fault, saved decision result and expected rubric. Its explanation is based
on those inputs; it does not reveal the judge's private reasoning or change its
verdict. Explanation failures can be retried by clicking the button again.

Judging runs independently of the diagnosis stream and survives browser navigation.
Verdicts and explanations are saved in each assistant message's operator payload,
with the rubric snapshot/hashes, raw decision response and separate usage/cost.
They are never added to the diagnosing agent's history or its token/tool statistics.
Opening history reuses saved results; it never automatically bills another judge call.
A server restart marks interrupted work as failed when its status is checked.
Older conversations have no automatic assessment. No D1 schema migration is needed.

Both requests use the existing gateway's `/openai/decisions` and `/openai/responses`
routes and stored BYOK key. No local OpenAI key is required. See the
[Decisions documentation](https://developers.openai.com/api/docs/guides/decisions)
and [judge criteria](../judge/grading.md).

## Exploratory benchmark matrix

Open **Benchmarks / Evals** from the homepage's top bar, or visit
http://127.0.0.1:8000/results.html. The page has one 3 × 5 matrix per selected
model/thinking combination: Main, Ring and Tree against F1–F5. The catalogue
comes from `config.MODELS`: reasoning models use low, medium, high and xhigh
where supported; GPT-4.1 Mini and Nano use none. All eight configured models, including
the deprecated group, currently give 26 combinations and **390 matrix cells**.
**Runs per cell**, next to Run all, defaults to 3 and accepts integers from 1
through 50: all models at 3 repeats means **1,170 diagnoses**, or 1,560 at 4.
The run button count includes repeats. Each trial is saved separately, with a
fresh conversation and its own chat, grade, usage and cost. Existing saved
single-trial runs remain readable. More repeats expose output variability;
three or four trials alone do not establish statistical significance.
Uncheck combinations before pressing **▶ Run all** to make a smaller run.
Each model heading also has **▶ Run**, which runs only that section's displayed
thinking levels using Runs per cell (for example, GPT-6.1 Sol's four efforts
give 60 cells and 180 diagnoses at 3 repeats).
While running, it becomes **Ⅱ Pause**. Pause safely ends the current run,
waits for probe/setup cleanup, resets the fault and keeps the results. Once
paused or finished, **↻ Rerun** starts a fresh benchmark with the same section's
combinations and the currently selected repeat count; the previous run and its
chats remain in saved history. During **Run all**, a section's Pause ends the
whole current run. Runs cannot overlap
on the shared testbed.

**Cost so far** updates beside each model and in the top bar as model requests
complete; finished/paused runs show **Cost**. Hover for diagnosis, grading and
explanation subtotals. These are calculated USD amounts from reported token
usage and the configured rates, including cached-token pricing, not a forecast
of the full suite or a provider invoice. Missing, cancelled or unfinished usage
is labelled **partial**, never silently charged as zero. Explanations requested
later in chat update the saved run total when the results page refreshes/polls.

Play is the only benchmark trigger. Opening the page, reloading it or starting
the server never starts diagnoses or injects a fault. The coordinator loads one
topology/fault, runs its combinations with fresh independent histories, waits
for diagnosis and grading to finish, and reapplies the scenario before the next
repeat. After all repeats it proceeds to the next scenario. It
reuses the scenario symptom prompts from `experiments/prompts.py`, captures
the system prompt and limits at Play, and captures one rubric per scenario
batch. Neither model settings, scenario identifiers nor judge ground truth are
added to the diagnosing model's history. The normal telemetry tools expose the
selected network as in chat.

Model requests run concurrently (default 3, selectable 1–4); **all diagnostic
probes are serialized** because they share Mininet, counters and iperf's server
port. Elapsed time and the turn timeout include probe queueing. Tool traces also
record that waiting time separately. Use concurrency 1 to compare elapsed
diagnosis times. Chat and operator topology/fault changes are blocked until the
benchmark releases the testbed. **Stop** cancels model work, waits for bounded
probes/setup to finish, resets the fault and marks unstarted cells skipped.
A cleanup failure blocks chat until the network is reloaded.

✅ means Correct, 🟡 means Mostly correct or Partially correct, and ❌ means
Incorrect. Once every trial in a cell is graded, the matrix shows the unique
most frequent symbol. Mostly correct and Partially correct count together as
yellow; exact grades remain available per trial. For example, two correct and
one incorrect show ✅; one of each or a 2–2 tie show **? Inconclusive**. This is
the most frequent outcome, which need not be a strict majority with 4+ trials.
Running cells show ◌; terminal cells with failed/skipped trials show ⚠ and
retain their distribution without treating failures as incorrect votes.
Each attempted diagnosis is saved as a normal sidebar chat, named with its
topology, fault, model, thinking level, trial number and benchmark run. Clicking
a cell opens its counts/percentages, cost and trial list, with a separate
**Open chat** link for each attempted trial (`/?conversation=<id>`), showing the
exact grade, diagnosis, tool trace and usage.
Use **Explain decision** in the chat to request the GPT-6.1 Sol / high explanation;
saved explanations are reused and synchronized with the benchmark result.
Unstarted/skipped scenarios do not create empty chats.

Runs and trial rows live in separate D1 tables (`benchmark_runs`, `benchmark_results`)
created idempotently by normal schema initialization. Trials share a matrix
cell ID and have unique trial IDs; no new database schema is needed for repeats.
Distributions are derived from these saved rows on each read. Each attempted
trial links to its conversation in the regular sidebar. Saved results survive
navigation/reloads; JSON export includes the captured prompt, rubric, raw
verdict, usage, traces and matrix distributions. A restart marks unfinished
runs/trials interrupted and never automatically reruns them or resets the live
testbed. Inspect that testbed before starting another run. The normal formal
protocol runner is unchanged; these matrix comparisons are exploratory,
and the ring/tree catalogues remain draft pending live verification.

The command-line sweep (`python -m experiments.sweep`, see the user guide's
"Multi-topology model sweep") also publishes here. It restarts the network
before every trial, includes the scripted baseline (shown as **Scripted baseline**)
and runs one topology per session in rounds, graded by the same judge. Its runs
appear in the history as **Sweep · …**, each round as one trial per cell, with
**CLI sweep** in place of Run/Rerun.

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

## Topology and fault picker

The **Network** picker initially shows three collapsed groups: **Main**
(6 switches / 8 hosts), **Ring** (5 / 5), and **Tree** (7 / 8). Expand a group,
then select **Healthy · No fault** or **F1–F5**. Expanding a group only browses
the choices. Selecting an option loads that topology on the live testbed;
selecting a fault also injects it from the matching catalogue.

Switching topology resets the previous fault, removes its baseline flows,
stops Mininet and starts the selected topology with its baseline forwarding.
ONOS stays running unless the existing start helper needs its normal recovery.
Selecting an option on the already-running topology keeps it running and resets
the old fault before applying the new choice. **Reset** clears the fault on the
current topology. The agent updates its telemetry mappings and model tool
allow-lists without a server restart. Changes cannot overlap a diagnosis or
another network change. A failed setup blocks chat until a topology is reloaded.

After the first accepted message, the model, thinking, topology and fault
controls (including **Reset**) are locked for that conversation. **New
conversation** unlocks them. Reopening a saved conversation restores its
selections; if the shared network has since changed, start a new conversation
to continue. Older chats without a recorded network remain available to read.

Selections are saved as operator-only message metadata, without a database
schema change. They are not sent in chat requests, included in provider history,
or added to the system prompt. Describe a symptom; do not name the scenario.
The network's ordinary configured facts remain available through telemetry.

The tree uses the retained selector `tree5s8h` despite having seven switches.
The testbed helper records the running topology in `mininet.ready`, and the
agent also recognises the switch-port layout after a server/dev reload.
The picker requires the existing Linux Mininet/OVS/ONOS installation and a root
agent process; it does not install those dependencies. File preview offers the
nested menus but cannot load a network. Ring/tree catalogue definitions remain
draft pending their separate live verification.

F2 also requires `tc` and `iperf3`; F4 requires `tc` for its safety limiter.
On Fedora, install them with `sudo dnf install -y iproute-tc iperf3`.
Injection checks these dependencies before writing pending fault state. If a
previous failed injection left pending state, install the missing tools and
retry the selection so normal reset can finish. A switching error naming the
old topology may refer to cleanup of that topology, before the selected one is
started. The UI now names the failing step and its error; the agent terminal
contains bounded diagnostic output with configured secrets redacted.

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

Defaults: 14 tool calls and 300 seconds per turn. The UI selects the first model
in the list and its first reasoning effort (currently `gpt-6.1-sol` / `low`).
Changing models selects that model's first supported effort. Both pickers use the
same expandable menu style. The per-turn token stop is
off (`MAX_TURN_TOKENS=0`). Set a positive value to restore it. A per-request
output cap of 8,192 tokens remains. This is not a billing cap; set gateway spend
limits for a financial cap. A final answer is requested after the tool budget is
exhausted.

The model picker lists GPT-6.1 Sol, GPT-6 Luna, GPT-6 Astra and GPT-4.1 Mini, with the
GPT-5.6 series inside an expandable **Deprecated** group. This is a UI grouping;
the legacy models remain selectable. Protocol v1 separately pins GPT-5.6 Sol /
`medium`; its formal preflight still requires those runtime defaults.
GPT-4.1 Mini is a small tool-calling baseline for ablations. It has only the
`none` thinking option, and requests omit reasoning parameters. Its Standard
cost estimate uses $0.40 input, $0.10 cached input and $1.60 output per million
tokens, following the [official model page](https://developers.openai.com/api/docs/models/gpt-4.1-mini).
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
- `topology_control.py`: operator testbed switching and topology recognition.
- `loop.py`: complete model/tool loop and measurements.
- `judge.py`: Decisions assessment, rubric capture and separate explanations.
- `benchmark.py`, `results.html`: exploratory coordinator and results matrices.
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
