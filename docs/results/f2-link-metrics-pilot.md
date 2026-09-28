# F2 link-metrics pilot

**PILOT / NOT FORMAL EXPERIMENTAL RESULTS**

One run per model. This does not replace `docs/results/llm-diagnosis.md` or `docs/results/f2-observability-pilot.md`.

## Setup

| Item | Value |
| --- | --- |
| Date | 28 September 2026 |
| Host | Ubuntu server `Aus`, `45.63.30.137` |
| Git | `feature/f2-observability-pilot` at `b3d403846de77792fa912217490ce302cb17956a`, plus the uncommitted Phase 1–3 worktree |
| Prompt | `Transfers from h1 to h5 are very slow. Investigate and localise the cause.` |
| Reasoning | `medium` |
| Models | `gpt-5.6-luna`, `gpt-5.6-terra`, `gpt-5.6-sol`, `gpt-6-astra` |
| Budget | `MAX_TOOL_CALLS=14` in the agent process only. Source default remains 10. |
| Turn limit | `MAX_TURN_SECONDS` unset, so the 300-second default stayed |
| Tool delay | 0 / 0 |
| Runs | One new conversation per model, after a healthy reset and a fresh operator inject. No retries. |

## Tool

`get_link_metrics(sw, port)` returns measurements for one known switch port. The window is fixed at 2.0 seconds. The model cannot set the duration or pass an interface name.

| Field | Source |
| --- | --- |
| `switch`, `port` | validated arguments |
| `peer` | canonical topology. A switch peer is `{switch, port}`. A host peer is `{host}`. |
| `enabled` | ONOS port state, or null if that read fails |
| byte, packet, drop, and error deltas; bit and packet rates | two kernel interface-counter samples |
| `queue_backlog_bytes`, `queue_backlog_packets` | instantaneous sample at the end of the window |
| `queue_overlimits_delta`, `queue_requeues_delta` | difference across the same window |

Arguments are `s1`–`s6` and a port that exists on that switch. Unknown switches, unknown ports, and extra properties are rejected. The command that reads queue counters is a fixed argument list. Its configuration text is discarded before the result is built.

The description does not name a fault or tell the model when to use the tool.

### Leakage

Healthy and impaired live results, and every tool observation stored in the four conversations, were searched for `tbf`, `1mbit`, `400ms`, `burst`, `qdisc`, `noqueue`, scenario ids, and fault-state wording. None of those strings were in the tool JSON. Models later used the word “qdisc” themselves when recommending a next inspection. That word was not in the measurement.

### What the counters did before any model call

Healthy, no active fault, `s1` port 4: enabled, peer `s5` port 1, transmit 0 bit/s, backlog 0, overlimits delta 0, requeues delta 0. Control ports `s5:1`, `s1:2`, and `s3:3` were the same, apart from about 1 kbit/s of idle traffic on some ports.

With the operator scenario active, `s1` port 4 transmitted about 0.990 Mbit/s, held 52,990 bytes / 20 packets of backlog, and counted 269 overlimits in the 2-second window. Requeues stayed 0. Drops and errors stayed 0. The peer `s5` port 1 received about 0.984 Mbit/s with backlog 0 and overlimits 0. `s1` port 2 and `s3` port 3 stayed near idle with backlog 0 and overlimits 0.

The fields that separated the impaired egress from the control ports were transmit rate, queue backlog, and the overlimit delta. Requeues did not move.

The scenario was reset before the agent restart. ONOS and Mininet were not restarted.

## Result table

Type is scored on whether the model used the queue evidence to name egress queue buildup, contention, or a rate/shaping constraint, rather than stopping at generic delay or an unknown impairment. Location is the s1↔s5 segment. Hedging is marked and is not upgraded silently.

| Model | Type | Location | Calls | Link-metric calls | Budget | Elapsed | First token | Tokens | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gpt-5.6-luna | Correct, hedged between a shaper and contention | s1 port 4 toward s5 | 14 | 5 | Exhausted | 74.7 s | 69.8 s | 122,776 | $0.0069 |
| gpt-5.6-terra | Correct, hedged among a rate limit, shaping, and sustained congestion | s1 port 4 → s5 port 1 | 11 | 2 | Not exhausted | 60.5 s | 54.5 s | 94,489 | $0.0589 |
| gpt-5.6-sol | Correct: rate limiter or constrained queue | s1 port 4 → s5 port 1 | 13 | 2 | Not exhausted | 71.7 s | 66.6 s | 102,534 | $0.1047 |
| gpt-6-astra | Correct: shaping near 1 Mbit/s, with the configured rate left unverified | s1 port 4 → s5 port 1 | 14 | 5 | Exhausted | 93.3 s | 52.5 s | 118,242 | $0.2598 |

Invalid calls: 0. Costs are estimates from `agent/config.py`, not an invoice. Four runs total about $0.43.

### gpt-5.6-luna

Called `get_link_metrics` on s3:1, s1:2, s1:4, s5:1, and s3:3. The impaired port showed about 998 kbit/s transmit, 9 KB / 6 packets queued, and 197 overlimits. Control ports were idle. Diagnosis: egress queuing, rate limiting, or contention on s1 port 4. It also treated the iperf result as invalid because the receiver reported 0 bytes and a scan found TCP/5201 closed. The link measurement, not iperf, carried the localisation. Conversation `da58668074d54379b96cab5f4e6e2b92`.

### gpt-5.6-terra

Compared h1→h5, h2→h5, h1→h3, and both directions between h5 and h6, then sampled s1:4 and s5:1. s1:4 showed about 1.01 Mbit/s, 11–12 KB / 8 packets queued, and 192 overlimits. The peer had the matching receive rate and an empty queue. Stopped after 11 calls. Conversation `0269b71248ef4565af3171091466ad1d`.

### gpt-5.6-sol

Isolated the path with throughput tests, then sampled s1:4 and s5:1. s1:4 showed about 1.0 Mbit/s, 19,682 bytes / 13 packets queued, and 191 overlimits. The peer queue was empty. Diagnosis: a rate limiter or constrained queue on that egress. Reverse h5→h1 was also slow, which it attributed to acknowledgements crossing the same egress. Conversation `9082252067324d07a7744580d52a80da`.

### gpt-6-astra

Sampled s3:1, s1:4 twice, s5:3, and s5:1, and compared h1→h2, h6→h5, and h1→h3. Both s1:4 samples were about 1.00–1.01 Mbit/s with 8–9 packets queued and about 200 overlimits. Fast comparisons stayed off that egress. It described shaping and said the exact configured rate was not verified. Conversation `477764d30d434f0191c00d3e807cfe38`.

## Comparison

| | Pilot A (PR #2) | Pilot B | Pilot C |
| --- | --- | --- | --- |
| Iperf | receiver bytes only | sender and receiver | sender and receiver |
| Extra tool | none | none | `get_link_metrics` |
| Budget | 10 | 14 | 14 |
| F2 score | 1 / 4 | 4 / 4, mechanism still open | 4 / 4, each answer cited backlog and overlimits |
| Type language | Luna treated 0 bytes as a bad test. Astra could not separate the link from the host. | Shaping, delay, or contention, with counters that could not separate them. | Egress queue, a ~1 Mbit/s plateau, and about 200 overlimits in 2 seconds. |
| Calls | 10 / 10 for every model | Terra 12; the other three 14 | Terra 11, Sol 13, Luna and Astra 14 |

This is one run each, on a different host from Pilot A. It is not a measured effect.

Location was already correct for all four models in Pilot B. Pilot C did not need to improve location, and it did not lose it. Fault-type language became more specific: every model reported a queue that was building and crossing an overlimit threshold at about 1 Mbit/s, and every model saw that the peer and the control ports did not. They still could not read a configured rate, which is intended. Requeues never changed, so that field did not help.

Luna spent a call on nmap and again described the zero-receiver iperf as unusable, even with the sender fields present. The new measurement is what kept that run on the right port.

Time and cost stayed in the same band as Pilot B. Astra was the longest run here, 93 seconds and about $0.26. No run approached 300 seconds.

## Decision

**KEEP** `get_link_metrics`.

The non-model measurement already separated the impaired egress (backlog and hundreds of overlimits at about 1 Mbit/s) from idle control ports (backlog 0, overlimits 0). All four models read those fields and used them in the diagnosis. The tool does not earn a place merely by existing: requeues were uninformative, and the tool does not reveal why the limit exists. It does add an observation the earlier tools did not provide.

A deterministic baseline can use the same tool. The inputs are an allow-listed switch and port, the window is fixed, and the result is numeric. A script can compare backlog and overlimit deltas across ports without a fault label. The 2-second sample makes a full-port sweep slower than a single ONOS read, so a script should query the ports under test rather than every port on every switch.

Recommended tool set for a later formal design: `get_topology`, `ping`, `nmap`, `get_port_status`, `get_port_stats`, `get_link_metrics`, `get_flow_table`, `iperf`.

Recommended `MAX_TOOL_CALLS` candidate: **14**. Terra stopped at 11 and Sol at 13. Luna and Astra still used the full 14, including repeated samples. Leave the source default at 10 until that candidate is accepted.
