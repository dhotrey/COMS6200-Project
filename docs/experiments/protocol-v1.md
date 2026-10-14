# Experimental Protocol v1

**Earlier design. Not the completed dataset.**

This document freezes a main-only comparison that was not collected. Its
`formal` command still refuses to start. The completed evaluation is
`evidence/experiments/sweep/sweep-2026-10/`: 525 final trials and 527 attempt
rows, graded by the OpenAI Decisions API (`gpt-6-luna`). Those records keep
the separate label `EXPLORATORY SWEEP / NOT PROTOCOL V1` and must not be
rewritten as protocol-v1 results.

**EXPERIMENTAL PROTOCOL V1**
**PRE-FORMAL-DATA-COLLECTION**

This document freezes the procedure for a formal COMS6200 comparison that was
not run. It does not contain those formal results, and it is not the 525-trial
dataset.

No diagnostic trial has been run under this protocol.
The scripted troubleshooting baseline specified here is implemented. It has
non-formal dry runs, and it was also a method in the completed sweep.
Fault Catalogue v1 (F1–F5) on `main6s8h` is unchanged. This protocol's formal
collection was not started. Dry runs are not part of either dataset's accuracy
denominator.

## Status of earlier runs

The following runs are **pilot evidence**. They are not part of the formal dataset, they are not repetitions under this protocol, and they must not be pooled with formal results.

| Record | What it is | Why it is excluded |
| --- | --- | --- |
| `docs/results/llm-diagnosis.md` and `evidence/progress/llm/*2026-09-23*` | PR #2 / Pilot A. One WSL2 run per scenario per model (20 runs), 10 tool calls, receiver-preferred iperf, no `get_link_metrics`. | Different host, tool budget, iperf schema, and tool set. Scoring was provisional. |
| `docs/results/f2-observability-pilot.md` | Pilot B. One Ubuntu F2 run per model, 14 tool calls, sender and receiver iperf. | One scenario, one run each, before `get_link_metrics`. |
| `docs/results/f2-link-metrics-pilot.md` | Pilot C. One Ubuntu F2 run per model with `get_link_metrics`. | One scenario, one run each. |

Those pilots are the only evidence used for the model and budget candidates below. They do not establish statistical superiority.

## 1. Research question

Primary question, unchanged:

> How accurately and efficiently can a tool-using LLM agent diagnose and localise common faults in an OpenFlow-controlled Mininet network compared with a deterministic scripted troubleshooting baseline?

The primary formal comparison is:

- **one** pinned LLM configuration
- versus **one** deterministic scripted baseline
- across F1–F5

A multi-model comparison is optional and secondary. It must not replace this comparison, and its runs must not be mixed into the primary accuracy denominators.

The optional constrained-repair question in Part A stays out of this protocol. Repair success is not a primary outcome.

## 2. What this protocol freezes, and what still needs approval

Frozen by this document, for a later collection commit:

- research question and primary comparison
- candidate tool set and the observational boundary
- candidate limits: `MAX_TOOL_CALLS=14`, `MAX_TURN_SECONDS=300`, tool delay 0, `MAX_TURN_TOKENS` disabled
- the five symptom prompts
- repetition count, run order, and seeds
- scoring rubric, including hedge and failure rules
- metrics, timing, and the run-record schema
- reset procedure
- baseline contract

The primary model for protocol v1 is approved:

- `gpt-5.6-sol`
- reasoning effort `medium`

That pair does not change during the 80 primary trials. A different model is a new protocol version, or an explicitly separate secondary dataset.

Formal collection still waits on all of the following:

1. A clean Git commit of the frozen source, prompt, tool schemas, and this protocol.
2. Formal metadata whose `approved_model_id` is `gpt-5.6-sol` and whose effort is `medium`.
3. The scripted baseline against the contract in section 11. The baseline is implemented. Protocol-v1 use of it is dry-run only; the completed sweep also included it.
4. A runner that asserts the effective limits in section 5 before the first trial. Formal mode stays refused until the launcher is armed and the live agent matches this protocol.

This file is not an authorisation to collect protocol-v1 data. The completed
project used `experiments/sweep.py` instead. Do not arm this runner in order to
recreate the archived sweep.

## 3. Platform held constant

| Item | Frozen value |
| --- | --- |
| Topology | `main6s8h`: 6 switches, 8 hosts, `10.0.0.0/24` |
| Controller | ONOS 2.7.0, OpenFlow 1.3, secure fail mode |
| Healthy datapath | 6 available `OF_13` devices, 20 directed links, 56 `org.coms6200.baseline` flows ADDED, 18 controller punt flows |
| Faults | Catalogue v1 only: F1 link failure, F2 congestion, F3 ACL/policy drop, F4 forwarding loop, F5 missing baseline flow |
| Reference host | Ubuntu 24.04.4 server used for Pilots B and C and the Phase 4 lifecycle checks |
| Agent bind | `127.0.0.1:8000` only |

Do not change F1–F5, the topology, or the tool schemas during collection.

## 4. Model-selection decision pack

**Approved primary model: `gpt-5.6-sol`. Approved reasoning effort: `medium`.**

The comparison below is the pilot evidence used to make that choice. It is historical and is not part of the formal dataset.

The harness does not expose the Part A model. Part A proposes GPT-5 mini, snapshot `gpt-5-mini-2025-08-07`. The implemented harness exposes only:

- `gpt-5.6-luna`
- `gpt-5.6-terra`
- `gpt-5.6-sol`
- `gpt-6-astra` (no `none` effort)

No further LLM calls are to be made to choose among them.

### Pilot comparison

Costs are estimates from `agent/config.py` price constants, not an invoice. Each cell is one run. Pilot A is the only run that covers F1–F5. Pilots B and C are F2 only, on the Ubuntu host, after the tool changes named in the table.

| Model | Pilot A success (5 scenarios, 10 calls, old iperf) | Pilot A F2 | Pilot A avg time / calls / 5-run cost | Pilot B F2 (14 calls, split iperf) | Pilot C F2 (14 calls, split iperf, `get_link_metrics`) |
| --- | --- | --- | --- | --- | --- |
| `gpt-5.6-luna` | 4 / 5 | Fail. Treated 0-byte iperf as a broken test. | 42 s, 9.8 calls, ~$0.024 | Hedged success. Location "s1–s5 or immediately beyond". 14/14. 57.9 s. 129,469 tokens. $0.0071. | Type hedged (shaper vs contention). Location s1 port 4 toward s5. 14/14, five link-metric calls. 74.7 s. 122,776 tokens. $0.0069. Again treated receiver 0 as an invalid iperf. |
| `gpt-5.6-terra` | 4 / 5 | Success, hedged: "most plausibly the s1–s5 segment". F5 was the partial: s3 forwarding for h5, flow table not read. | 56 s, 9.4 calls, ~$0.225 | Exact s1 port 4 ↔ s5 port 1. Mechanism not singled out. 12/14. 79.7 s. 107,456 tokens. $0.0691. | Type hedged among rate limit, shaping, and congestion. Exact ports. 11/14, two link-metric calls. 60.5 s. 94,489 tokens. $0.0589. |
| `gpt-5.6-sol` | 4 / 5 | Partial: shaping/congestion named, location stayed on the h1↔h5 flow. Comparisons did not leave s1–s5. | 67 s, 9.0 calls, ~$0.375 | Exact s1 port 4 → s5 port 1. 14/14. 82.7 s. 102,259 tokens. $0.1086. | Primary type: rate limiter or constrained queue. Exact ports. 13/14, two link-metric calls. 71.7 s. 102,534 tokens. $0.1047. |
| `gpt-6-astra` | 4 / 5 | Fail. Narrowed to s1–s5, s5–h5, or h5, with no calls left. | 45 s, 9.0 calls, ~$0.789 | Location exact. Mechanism left open. 14/14. 78.1 s. 122,845 tokens. $0.2857. | Shaping near 1 Mbit/s, configured rate left unverified. Exact ports. 14/14, five link-metric calls. 93.3 s. 118,242 tokens. $0.2598. |

Invalid tool calls in Pilot C: 0. No pilot run approached 300 s.

### What the pilots do not show

- They do not show a stable accuracy ranking. On the only full-catalogue sample, every model scored 4 / 5 under a looser provisional rubric.
- Pilot A used a 10-call budget and an iperf parser that hid sender progress. F2 misses in that sample are not a fair ranking under this protocol's tool set.
- Pilots B and C are one F2 run each. A single success is not a rate.
- Hedged wording was footnoted, not upgraded. This protocol's hedge rule in section 9 is stricter and is not applied backwards to rewrite those notes.

### Recommendation

Recommended primary model: **`gpt-5.6-sol`**.
Recommended reasoning effort: **`medium`**.

Reason:

- The research question leads with accuracy. On the F2 runs that used the candidate budget, sol named the exact impaired ports both times. In Pilot C the primary type was a rate limiter or constrained queue, which is one family under section 9, not an unranked list of unrelated faults.
- Sol did not repeat luna's reading of a completed iperf with `receiver_bytes` 0 as a failed command.
- Terra is the closest alternative on tool efficiency: it stopped at 11 and 12 calls and was exact on F2 location in Pilots B and C. In the only full-catalogue sample it was the F5 partial, and its F2 wording stayed more hedged.
- Luna matched the 4 / 5 headline and is much cheaper (about $0.007 per F2 pilot run versus about $0.10 for sol, and about $0.024 versus about $0.38 for five Pilot A runs). Its F2 answers stayed location-hedged or type-hedged, and it spent a call scanning the iperf port after treating the receiver summary as invalid.
- Astra showed no accuracy advantage. Its F2 pilot runs cost about $0.26–$0.29, several times sol.

Forty formal LLM trials at the Pilot A average would be on the order of a few dollars for sol and well under a dollar for luna. Cost does not force the choice. It does make luna a reasonable alternative if the team prefers the cheapest model that matched the only five-scenario score.

`gpt-6-astra` is not recommended as the primary model.

The approved identifier and effort are pinned. They do not change for the 80 primary trials. A later model is a new protocol version, or an explicitly separate secondary dataset.

## 5. Limits candidate

These values apply to every F1–F5 trial. They are not changed per scenario.

| Limit | Formal value | Where it lives today |
| --- | --- | --- |
| `MAX_TOOL_CALLS` | 14 | Source default in `agent/limits.py`. Formal preflight reads the live agent `/api/config` and refuses unless it is 14. |
| `MAX_TURN_SECONDS` | 300 | Source default. Formal preflight requires the live agent to report 300. |
| `TOOL_DELAY_MIN_SECONDS` | 0 | Source default. Formal preflight requires the live agent to report 0. |
| `TOOL_DELAY_MAX_SECONDS` | 0 | Source default. Formal preflight requires the live agent to report 0. |
| `MAX_TURN_TOKENS` | 0 (disabled) | Source default. Leave it unset or set to 0. |
| Parallel tool calls | false | `agent/loop.py` |
| Provider cache | bypassed | `cf-aig-skip-cache: true` in `agent/config.py` |
| Responses storage | off | `store: false` in `agent/loop.py` |

Why 14 rather than 10:

- In Pilot A every F2 run used 10 / 10 calls. Astra had the next useful comparison in mind and no calls left. Sol's comparisons stayed on the impaired segment.
- In Pilot B the first comparison that avoids s1–s5 was call 10 or call 12. Terra then stopped at 12. The other three used all 14.
- In Pilot C Terra stopped at 11 and sol at 13. Luna and astra used 14, including repeated link-metric samples.
- 14 is a maximum, not a target. Stopping earlier is a valid trial.

The 2-second `get_link_metrics` sample is part of tool execution time. It is not subtracted.

Before the first formal trial the runner must read the agent process environment and refuse to start unless `MAX_TOOL_CALLS` is 14 and both tool delays are 0. A mismatch is a session abort, not a scored trial.

## 6. Tool-set candidate

The model-facing tools are exactly these eight, taken from `telemetry/schemas.py` `TOOL_SCHEMAS`. The agent builds its tool list from that mapping.

| Tool | Purpose | Bounded arguments |
| --- | --- | --- |
| `get_topology` | ONOS devices, links, and ports, plus the configured host-attachment map. Does not use ONOS host discovery. | No arguments. |
| `ping` | ICMP reachability, loss, and RTT between two project hosts, primary IPv4 only. | `src`, `dst` in h1–h8. `count` integer 1–10, default 3. |
| `nmap` | One TCP-connect or UDP scan of one port. | `src`, `dst` in h1–h8. `proto` is `tcp` or `udp`. `port` integer 0–65535. `-Pn`, 5 s host timeout, 20 s overall limit. |
| `get_port_status` | Administrative and operational port state, with configured peers. | `sw` in s1–s6. |
| `get_port_stats` | ONOS port counters and a short derived bit-rate sample. No utilisation from configured capacity. | `sw` in s1–s6. |
| `get_link_metrics` | Fixed two-second sample for one known switch port: peer, enabled, packet and byte deltas, rates, drop and error deltas, end-of-window queue backlog, overlimit and requeue deltas. Null when unavailable. | `sw` in s1–s6. `port` integer 1–5, and only if that port exists. Window is not a parameter. |
| `get_flow_table` | Normalised flow entries for one switch. | `sw` in s1–s6. |
| `iperf` | One-shot iperf3 TCP test. Sender and receiver byte, rate, and duration fields, plus retransmits. `receiver_bytes` 0 with `sender_bytes` > 0 is a completed measurement. | `src`, `dst` in h1–h8. `duration` integer 1–5, default 2. Gateway port 5201. |

`telemetry.schemas.schema_list()` and `telemetry.gateway.tool_names()` list these eight tools, including `nmap`, in this order. Do not add or remove a tool during collection.

The diagnostic methods do **not** receive:

- a shell tool
- arbitrary ONOS REST
- ONOS credentials
- a fault-injection tool
- a ground-truth tool
- a scenario id
- raw `tc` / qdisc configuration, configured rate, burst, latency, or limit
- fault-state contents

The scripted baseline uses this same boundary. It may call the same gateway functions. It may not receive a wider interface than the model.

## 7. Scenario prompts

The first two columns are the only scenario text a diagnostic method may see.
The ground-truth columns are evaluator-only. They must not appear in the system prompt, the user message, tool descriptions, or the baseline's inputs.

The prompts are the strings already used in `docs/results/llm-diagnosis.md` and the user-guide diagnosis table. They are preserved exactly, without the surrounding quotation marks.

| Scenario | Exact user prompt (model-visible) | Ground-truth family (evaluator-only) | Ground-truth location (evaluator-only) |
| --- | --- | --- | --- |
| F1 | h1 can no longer reach h5. Diagnose and localise the fault. | Link failure | s3 port 1 ↔ s1 port 2 |
| F2 | Transfers from h1 to h5 are very slow. Investigate and localise the cause. | Congestion | s1 port 4 ↔ s5 port 1 |
| F3 | h1 can no longer reach h5. Diagnose and localise the fault. | ACL / policy drop | Selective drop of h1→h5 on s3 |
| F4 | h1 can no longer reach h5. Diagnose and localise the fault. | Forwarding loop | Cycle s3 → s4 → s1 → s3 for h1→h5 |
| F5 | h1 and h2 can no longer reach h5. Diagnose and localise the fault. | Missing baseline flow | No baseline unicast for h5 on s3 |

F1, F3, and F4 share a prompt on purpose. The method has to separate them from tool evidence.

Each trial sends that one user message in a new conversation. The system prompt is the frozen `agent/prompt.md`. Its sha256 is the harness field `prompt_sha256`.

## 8. Matrix, repetitions, and run order

### Size

| | Count |
| --- | ---: |
| Scenarios | 5 |
| Repetitions per scenario per method | 8 |
| Methods | 2 (pinned LLM, scripted baseline) |
| LLM trials | 40 |
| Baseline trials | 40 |
| Primary formal trials | 80 |

Pilot runs are not counted. Optional repair trials are not counted. Secondary multi-model runs are not counted.

Eight remains the Part A number. It is feasible: pilot diagnoses took about 40–90 seconds, and an in-place fault reset is a few seconds when the healthy gate passes. The protocol does **not** keep Part A's option to raise the count to 10 after seeing variance. The count is frozen at 8 before formal data exist.

### One independent repetition

One repetition is all of the following, once:

1. Healthy gate passed (section 10).
2. The selected scenario injected by the operator or runner.
3. A new conversation with empty history. No earlier diagnosis, tool result, or chat title is carried in.
4. Exactly one user message, the prompt in section 7.
5. Exactly one diagnosis turn.
6. The run record appended.
7. The scenario reset.
8. The healthy gate passed again.

A second turn in the same conversation is not a repetition. Editing the prompt is not a repetition.

### Randomisation

Do not run F1 eight times, then F2 eight times, and so on.

Build the 40 pairs `(scenario, repetition)` with scenarios in order F1…F5 and repetitions 1…8. Shuffle that list with `random.Random(seed).shuffle` under CPython 3.12.3. The lists below were produced on the experiment host with that interpreter and are **authoritative**. Regenerating the shuffle is a checksum. If a later Python disagrees, keep these lists.

- LLM seed: `6200`
- Baseline seed: `6201`

Construction, for the record:

```python
import random
pairs = [(s, r) for s in ["F1", "F2", "F3", "F4", "F5"] for r in range(1, 9)]
order = pairs.copy()
random.Random(seed).shuffle(order)
```

LLM order (seed 6200):

| k | Pair | k | Pair | k | Pair | k | Pair |
| ---: | --- | ---: | --- | ---: | --- | ---: | --- |
| 1 | F1 r5 | 11 | F5 r2 | 21 | F2 r1 | 31 | F3 r4 |
| 2 | F5 r6 | 12 | F5 r5 | 22 | F5 r1 | 32 | F1 r7 |
| 3 | F4 r7 | 13 | F1 r4 | 23 | F3 r6 | 33 | F2 r2 |
| 4 | F3 r2 | 14 | F3 r8 | 24 | F3 r1 | 34 | F5 r8 |
| 5 | F3 r3 | 15 | F2 r6 | 25 | F2 r7 | 35 | F2 r4 |
| 6 | F4 r3 | 16 | F1 r8 | 26 | F5 r3 | 36 | F5 r4 |
| 7 | F1 r6 | 17 | F3 r7 | 27 | F2 r5 | 37 | F1 r2 |
| 8 | F2 r3 | 18 | F3 r5 | 28 | F1 r1 | 38 | F5 r7 |
| 9 | F4 r2 | 19 | F4 r8 | 29 | F4 r5 | 39 | F1 r3 |
| 10 | F4 r4 | 20 | F4 r1 | 30 | F4 r6 | 40 | F2 r8 |

Baseline order (seed 6201):

| k | Pair | k | Pair | k | Pair | k | Pair |
| ---: | --- | ---: | --- | ---: | --- | ---: | --- |
| 1 | F1 r1 | 11 | F2 r3 | 21 | F2 r5 | 31 | F2 r4 |
| 2 | F5 r8 | 12 | F3 r1 | 22 | F2 r1 | 32 | F2 r2 |
| 3 | F5 r5 | 13 | F1 r3 | 23 | F1 r8 | 33 | F4 r6 |
| 4 | F1 r2 | 14 | F4 r8 | 24 | F3 r6 | 34 | F3 r8 |
| 5 | F1 r7 | 15 | F4 r2 | 25 | F2 r8 | 35 | F2 r7 |
| 6 | F3 r5 | 16 | F4 r7 | 26 | F4 r4 | 36 | F5 r2 |
| 7 | F3 r7 | 17 | F3 r3 | 27 | F3 r2 | 37 | F5 r1 |
| 8 | F4 r5 | 18 | F1 r4 | 28 | F1 r5 | 38 | F1 r6 |
| 9 | F4 r1 | 19 | F2 r6 | 29 | F5 r3 | 39 | F5 r7 |
| 10 | F5 r4 | 20 | F3 r4 | 30 | F5 r6 | 40 | F4 r3 |

Execution is interleaved, after the baseline exists:

```text
for k in 1..40:
    LLM trial at LLM-order[k]
    reset and healthy gate
    baseline trial at baseline-order[k]
    reset and healthy gate
```

Analysis pairs a method's trials on `(scenario, repetition)`, not on the interleave index `k`. The two methods do not share an injection. Each gets its own inject and its own clean start.

Both seeds and both full orders are copied into the experiment metadata file before the first trial. There is no other random source for run order.

Do not start the LLM half early and the baseline half on a later day. That would break the interleave. If collection is interrupted by an infrastructure stop, resume at the next unfinished `k`. Do not reshuffle.

## 9. Scoring rubric

Scoring is evaluator-only. It is applied to the final assistant message, after the last tool result. Tool traces are kept for audit and are not themselves the diagnosis. Intermediate text that the model later revises is not scored. A later sentence that explicitly replaces the conclusion ("the cause is", "the actual fault is") replaces the earlier one.

The evaluator records the verbatim span treated as the primary conclusion.

Two binary scores:

- `family_correct` is 1 or 0
- `location_correct` is 1 or 0

`full_diagnosis_correct` is 1 only when both are 1. Do not collapse the two into a single impression and then back-fill the bits.

### Closed family map

The primary conclusion must map to exactly one of these families. Wording outside this map scores 0 for family.

| Family id | Accept as that family | Do not accept as that family |
| --- | --- | --- |
| `link_failure` | The primary cause is a link or port that is down. | A controller or baseline that "failed to reroute", if that is the primary cause. A down link mentioned only as background. |
| `congestion` | The primary cause is congestion, contention, competing load, shaping, a rate limit, or a constrained queue on a path that is still up. | The word "slow" or "delay" alone. An unranked mix with a drop rule, a missing flow, a loop, or a down link. |
| `policy_drop` | The primary cause is an explicit drop, filter, or policy rule. | A missing forwarding rule. A down link. |
| `forwarding_loop` | The primary cause is a forwarding cycle. | One black-hole rule with no cycle. |
| `missing_flow` | The primary cause is an absent baseline forwarding rule. | An explicit drop rule. |

Synonyms inside one cell are one family. "Rate limiting or shaping" on an up path is `congestion`, not two families. "Congestion or a drop rule" is two families.

### Location granularity, fixed before formal answers exist

| Scenario | Location-correct requires | Not sufficient |
| --- | --- | --- |
| F1 | The link s3:1 ↔ s1:2. Any of these names it: "s3–s1", "s3 port 1", "s1 port 2", or either interface on that pair. | "s3" alone, "s1" alone, or the host pair h1–h5. |
| F2 | The link s1:4 ↔ s5:1. Any of these names it: "s1–s5", "s1 port 4", "s5 port 1". | "s1" alone, "s5" alone, the flow h1↔h5, or s5–h5. |
| F3 | Switch s3 and a drop of traffic from h1 toward h5. Priority 50000 and the experiment application id are visible in the flow table and may be quoted. They are not required. | "s3" without the h1→h5 drop. The same drop claimed on another switch. |
| F4 | All three switches s3, s4, and s1, as the cycle for h1→h5. The port sequence s3:5 → s4:1 → s1:2 is sufficient. | Only one or two of those switches. A different cycle. |
| F5 | Switch s3 and destination h5, together with the claim that the forwarding rule is missing. Priority 41000 may be quoted and is not required. | "s3" alone. "Missing rule" with no switch. An explicit drop on s3, which can still be location-correct only if the switch and destination match, but then family is `policy_drop` and family_correct is 0. |

A secondary wrong remark does not flip a correct primary score. A co-equal alternative does. That distinction is the hedge rule.

### Hedge rule

Apply this before assigning either bit:

1. If the conclusion names one family and one location, score those.
2. If it ranks alternatives, score only the highest rank. "Most likely" and "most plausibly" mark the highest rank. A lower-ranked correct answer does not count.
3. If it joins alternatives with "or", "either", "could be", or an unranked slash, and those alternatives are different families or different locations under the tables above, that bit is 0. Membership of the correct item in the list does not count.
4. Alternatives that the map treats as the same family do not trigger rule 3 for family.
5. A correct location with an unranked extra location is location 0. "s1–s5 or immediately beyond it" is location 0. "Most likely s1–s5; the host is unlikely" is location 1 if s1–s5 is the right link for that scenario.
6. No cause, or only a request for another test, is family 0 and location 0.

Do not rescore a trial after seeing later trials. Do not give the benefit of the doubt: if the span does not meet the table, the bit is 0, and the span stays in the record.

Reaching 14 tool calls is not itself a wrong answer. Score whatever primary conclusion was produced. If none was produced, both bits are 0.

## 10. Reset procedure

Normal trial loop. ONOS stays up.

`./scripts/testbed.sh stop --with-onos` is administrative. It is not part of a formal trial. The Phase 4 recovery that may recreate the `onos` container belongs to `start` after an explicit ONOS stop or a failed device attach. Do not provoke it between trials.

Before every trial:

1. Reset any active F1–F5 fault (`./scripts/testbed.sh reset`).
2. If the healthy gate fails, run `./scripts/testbed.sh stop` and then `./scripts/testbed.sh start`. That stops Mininet and leaves ONOS running.
3. Pass the healthy gate:
   - 6 available `OF_13` devices
   - 20 directed links
   - 56 baseline flows ADDED
   - no `org.coms6200.experiment` flows
   - no active fault-state file
   - no residual `iperf3`
   - no TBF qdisc on the catalogue interfaces (including `s1-eth4` and `s3-eth5`)
   - h1→h5 connectivity healthy
4. Inject the selected scenario through the operator path. The diagnostic method is not told the scenario id.
5. Create a new conversation.
6. Send the one prompt. One diagnosis.
7. Append the run record.
8. Reset the scenario.
9. Pass the healthy gate again. A failed post-trial gate is an infrastructure event for the *next* slot, not a reason to discard a completed diagnosis.

F2's background iperf3 on h3→h6 (port 5202) stays up for the lifetime of the injected fault and is stopped by reset. iperf3 is started with `-t 0`, which on iperf 3.16 sets no transmit timer. The TBF on s1-eth4 also remains until reset. The target link, 1 Mbit/s TBF, family, ground truth, and symptom prompt are unchanged. A diagnosis turn cannot outlive the background load while F2 is still active.

## 11. Scripted baseline contract

Implemented in `baseline/`. It was checked with non-formal dry runs. It must not be tuned on formal answers. Formal answers do not exist yet.

**Input.** The same user symptom string the LLM receives for that trial, plus the same system instruction that the task is to diagnose the current network. The runner knows the scenario in order to inject and to score. That knowledge is not passed into the baseline as an argument, a prompt field, or a branch key.

**Observations.** The same eight tools, or the same `TelemetryGateway` methods with the same argument bounds. No extra counters, no raw `tc` text, no ONOS credentials, no shell.

**Forbidden.** `fault-state.json`, scenario id, injector source, F2's configured rate, burst, latency, or qdisc type, evaluator labels, and any file under the formal results directory.

**Output.**

- `diagnosis_family` in the family ids of section 9, or empty if the procedure abstains
- `diagnosis_location` as a short location string
- tool trace: name, arguments, and the gateway envelope, in order
- `diagnosis_elapsed_sec`
- `tool_call_count`

**Fairness.** The LLM chooses tools adaptively. The baseline follows a fixed procedure. That difference is the experimental contrast. The baseline does not get a larger tool budget, a private cache of ground truth, or thresholds fit on the formal trials. Healthy-path thresholds, if any, are calibrated on non-formal pilot traffic and then frozen in the same commit as the baseline.

The baseline is not `org.coms6200.baseline`. That application is the forwarding datapath.

## 12. Metrics and timing

### Primary

- fault-family accuracy: mean of `family_correct`
- localisation accuracy: mean of `location_correct`
- full diagnosis accuracy: mean of `full_diagnosis_correct`
- tool-call count
- `diagnosis_elapsed_sec`

Report each accuracy by scenario and overall, as counts and percentages. Report tool calls and elapsed time as median and range. The primary contrast is the pinned LLM against the baseline on the 80 scored trials.

### LLM-only secondary

Taken from the harness turn stats when present:

- `input_tokens`, `output_tokens`, `reasoning_tokens`, `cached_tokens`, `total_tokens`
- `model_calls` (count of model requests; the harness name is `model_calls`)
- `cost_usd` (estimate from `agent/config.py`, not an invoice)
- `invalid_tool_calls`
- `first_token_seconds`
- `usage_complete`

### Not primary

Repair success stays optional and outside this matrix.

### Timing

`diagnosis_elapsed_sec` for the LLM is the harness `duration_seconds`: perf-counter time from entry to `agent.loop.run` until the turn finishes. That includes model inference, tool execution, and the `get_link_metrics` sample. Tool delay is 0, so there is nothing to subtract. It excludes injection, reset, healthy-gate time, and any human pause.

`diagnosis_elapsed_sec` for the baseline is wall time from invocation to the returned diagnosis, including the same gateway work and the same 2-second samples. It excludes injection and reset.

`first_token_seconds` is secondary and is not used as diagnosis time.

## 13. Run record

One JSON object per line in `evidence/experiments/protocol-v1/runs.jsonl`.
Create that file only when collection starts. Do not create it in this phase.

A sibling `evidence/experiments/protocol-v1/metadata.json` stores `experiment_version`, both seeds, both orders, the approved model id, `prompt_sha256`, and the frozen git commit. Metadata is written before trial `k = 1`.

D1 already stores `conversations` (`id`, `title`, `history`, timestamps) and `messages` (`conversation_id`, `payload`). The formal record keeps `conversation_id` so a trial can be audited there. Scores are not written into the conversation. D1 is not the scoring database.

Field names follow the harness stats where a stat already exists.

| Field | Source |
| --- | --- |
| `experiment_version` | `protocol-v1` |
| `git_commit` | Full SHA of the frozen commit. Required. |
| `run_id` | Unique id for this attempt. |
| `attempt` | 1, or 2 when section 14 allows one infrastructure rerun. |
| `interleave_index` | `k` from 1 to 40. |
| `method` | `llm` or `baseline` |
| `model` | Pinned id, or null for the baseline. |
| `reasoning_effort` | `medium`, or null for the baseline. |
| `scenario` | Evaluator-only. |
| `repetition` | 1–8. |
| `random_seed` | 6200 or 6201. |
| `prompt` | Exact user message. |
| `prompt_sha256` | Harness stat for the system prompt. |
| `conversation_id` | D1 id for an LLM trial. Null for the baseline. |
| `started_at`, `completed_at` | UTC timestamps. |
| `diagnosis_elapsed_sec` | Section 12. |
| `diagnosis_text` | Final assistant message, or the baseline's text. |
| `primary_conclusion_span` | Verbatim span the evaluator scored. |
| `diagnosis_family`, `diagnosis_location` | Mapped labels. Empty if abstained. |
| `family_correct`, `location_correct`, `full_diagnosis_correct` | 0 or 1. Null when `include_in_accuracy` is false. |
| `tool_trace` | Ordered tool name, arguments, and observation. |
| `tool_call_count` | Harness `tool_calls`. |
| `invalid_tool_calls` | Harness name. |
| `model_calls` | Harness name. Null for the baseline. |
| `input_tokens`, `output_tokens`, `reasoning_tokens`, `cached_tokens`, `total_tokens` | Harness sums. |
| `cost_usd` | Harness estimate. |
| `first_token_seconds` | Harness stat. |
| `usage_complete` | Harness flag. |
| `reset_verified_before`, `reset_verified_after` | Booleans. |
| `f2_load_running_at_start` | Boolean or null. |
| `outcome` | `scored`, `infrastructure_failure`, or `infrastructure_excluded`. |
| `include_in_accuracy` | False for infrastructure outcomes. |
| `error` | Short infrastructure or harness error. Empty when none. |

Ground truth stays in the evaluator's copy of the catalogue, not in the model context. The record may repeat the evaluator-only family and location ids so the file is self-contained. The runner must not send the record back to the model.

## 14. Failure and abort rules

Two outcomes. They are classified from the logs before any rerun, and the classification is stored on the attempt.

### Diagnostic failure

Scored. `include_in_accuracy` true. **Never rerun** to seek a better answer.

- Wrong or hedged diagnosis.
- No usable primary conclusion, including a turn that only asks for another test.
- The model reaches 14 tool calls.
- The turn hits 300 seconds while the testbed is still healthy.
- Invalid tool arguments (`invalid_tool_calls`).
- A tool returns `ok: false` because the arguments were rejected.
- An early, poor, or abstaining answer.

Both score bits are 0 when there is no primary conclusion. Elapsed time and tool counts are still recorded.

### Infrastructure failure

Not an accuracy observation. At most **one** rerun of that `(method, scenario, repetition)` slot.

- The agent process crashes, or the HTTP call fails, before a completed turn.
- Cloudflare or the Responses stream fails, or the response status is not completed.
- The healthy gate fails before the trial. This is not an attempt: restore the testbed, then start the slot. If the gate cannot be restored, stop the session. Do not skip the slot.
- ONOS or Mininet becomes unhealthy during the turn, confirmed from testbed state or logs, including a 300-second timeout caused by that outage rather than by model time.
- The post-start device check fails and `start`'s single ONOS recreation also fails. Stop. Do not continue the matrix on a broken controller.
- D1 does not persist the conversation **and** the runner did not keep the transcript. If the runner kept the transcript and stats, score the trial and record the D1 error. Do not rerun a scored answer because D1 failed.

The first infrastructure attempt stays in the JSONL with `outcome=infrastructure_failure`, `attempt=1`, `include_in_accuracy=false`. The rerun is `attempt=2`, a new conversation, the same pair and the same `k`. A second infrastructure failure sets `outcome=infrastructure_excluded` and does not create `attempt=3`. Excluded slots are reported separately. They are not silent omissions and they are not scored as wrong answers.

A poor diagnosis is never reclassified as infrastructure.

## 15. Version freeze

Formal rows must name one immutable git commit. Collection must not start on a dirty tree.

Frozen in that commit:

- source code
- `agent/prompt.md`
- pinned model identifier and reasoning effort
- the eight tool schemas
- tool budget, turn limit, delays, and disabled token cap
- Fault Catalogue v1 definitions
- baseline implementation
- this scoring rubric
- run-order seeds and the authoritative orders in section 8
- the reset procedure

If any of those change after the first formal row is written, increment the protocol version. Do not pool the new rows with protocol-v1 results without an explicit, separate analysis. Pilot documents stay historical and are not edited to match the new rubric.

## 16. Part A statements this protocol does not rewrite

Part A is left unchanged. Later report writing will need to reconcile at least these points. Line numbers refer to `docs/reports/part-a/part-a-source.md` as of this protocol.

| Part A statement | Current state this protocol uses |
| --- | --- |
| Abstract: fault injection and LLM integration remain pending. | Catalogue v1 is frozen. The harness, baseline and 525-trial sweep now exist. This protocol's own formal matrix was not collected. |
| GPT-5 mini, snapshot `gpt-5-mini-2025-08-07`, as the single primary model (about lines 60 and 116). Model comparison declared out of scope. | The completed sweep compared six models with the scripted baseline. This protocol still pins `gpt-5.6-sol` at effort `medium`, and that pin was not the collected design. |
| Six diagnostic tools in section 5.2 and Table 1. No nmap. No `get_link_metrics`. Iperf described as duration, transfer, and Mbit/s. | Eight model-facing tools. Iperf exposes sender and receiver fields. `get_link_metrics` is the eighth. |
| Section 5.2: baseline and LLM agent are not yet implemented. | Both are implemented. The completed comparison is the sweep, not this protocol. |
| Section 5.5: eight repetitions, with room to move to ten if variance is high. | Eight remains this protocol's unused freeze. The sweep used five rounds. |
| Metrics in Table 3, including optional repair success and secondary token cost. | Primary metrics match Table 3 except repair success, which stays out of the matrix. |
| Section 6 schedule: M6 next; baseline 12–18 Sep 2026; protocol freeze 19–25 Sep; paired experiments 26 Sep–7 Oct. | Those dates passed. The agent, baseline and sweep are complete. This protocol's paired matrix was not collected. |
| `docs/results/llm-diagnosis.md`: 10 tool calls, provisional scores, WSL2. | Historical pilot. It is not the 525-trial dataset. |
| User-guide and README milestone lines that still describe repeated experiments and the scripted baseline as only planned. | Corrected. The baseline is implemented and was in the sweep. This protocol's formal collection remains unstarted. |

## 17. Collection gate

Do not run a formal trial until section 2's approval and implementation gates are met.

A formal trial is any diagnosis that is intended to enter `runs.jsonl` or to be reported as protocol-v1 accuracy. Pilot reruns, baseline debugging, and healthy-path threshold calibration are not formal trials only when they are labelled as such and are not scored into the 80.
