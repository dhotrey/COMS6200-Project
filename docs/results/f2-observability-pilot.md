# F2 observability pilot

**PILOT / NOT THE 525-TRIAL EVALUATION**

One run per model. This does not replace `docs/results/llm-diagnosis.md` and is not the completed sweep.

## Setup

| Item | Value |
| --- | --- |
| Date | 28 September 2026 (server UTC afternoon) |
| Host | Ubuntu server `Aus`, `45.63.30.137` |
| Git | branch `feature/f2-observability-pilot`, HEAD `b3d403846de77792fa912217490ce302cb17956a` (same commit as `master`). Iperf, tests, and this note are uncommitted working-tree changes. |
| Prompt | `Transfers from h1 to h5 are very slow. Investigate and localise the cause.` |
| Reasoning | `medium` |
| Models | `gpt-5.6-luna`, `gpt-5.6-terra`, `gpt-5.6-sol`, `gpt-6-astra` |
| Tool budget | `MAX_TOOL_CALLS=14` in the agent process environment only. Source default remains 10. `.env.example` was not changed. |
| Turn limit | `MAX_TURN_SECONDS` was not set, so the source default of 300 seconds stayed in force. |
| Tool delay | `TOOL_DELAY_MIN_SECONDS=0`, `TOOL_DELAY_MAX_SECONDS=0` |
| Runs | Exactly one new conversation per model. The operator reset the catalogue, confirmed no active fault, injected F2, then sent the prompt. The prompt did not name the scenario. No run was repeated. |
| Agent | Restarted on `127.0.0.1:8000` only. ONOS and Mininet were not restarted. |

## Iperf change under test

`parse_iperf` used to copy `sum_received` bytes and bit rate whenever that object included the keys, including an explicit zero, so a sender that had transmitted data disappeared from the top-level result.

The tool now returns both sides:

- `sender_bytes`, `sender_bits_per_sec`, `sender_duration_sec`
- `receiver_bytes`, `receiver_bits_per_sec`, `receiver_duration_sec`
- `retransmits`

Legacy `bytes_transferred`, `mbit_per_sec`, `duration_sec`, and `retransmissions` remain. Those legacy byte, rate, and duration fields still follow the receiver summary when the receiver summary includes the field, including zero, and otherwise follow the sender. The tool does not add a diagnosis, scenario id, or traffic-control configuration.

A live check before any model call showed the previous misleading zero was the receiver summary. On an impaired h1→h5 test the sender had transmitted 131072 bytes (~0.52 Mbit/s) while `receiver_bytes` stayed 0. The same call is `ok: true`. An iperf3 `error` string is still `ok: false`.

## Result table

Scoring matches the PR #2 definition: success requires the congestion/shaping family and the s1↔s5 segment; partial is only one of those; fail is neither. A hedged but leading correct location is marked, not upgraded silently. Ground truth was applied only while scoring.

| Model | Fault type | Location | Overall | Tools | Budget | Isolation that avoids or stays off s1–s5 |
| --- | --- | --- | --- | --- | --- | --- |
| gpt-5.6-luna | Correct class (rate limit / queueing), with a software-datapath alternative | Hedged: leading claim is s1–s5, also “immediately beyond” / s5-side | Success (hedged) | 14 | Exhausted | h1→h4 ~7.4 Gbit/s (avoids s1–s5). No h5–h6 test. |
| gpt-5.6-terra | Correct class (contention, imposed bandwidth, or delay); mechanism not singled out | Exact: s1 port 4 ↔ s5 port 1 | Success | 12 | Not exhausted | h1→h3 ~11.1 Gbit/s. No h5–h6 test. |
| gpt-5.6-sol | Correct class (rate limit, shaping, or delay) | Exact: s1 port 4 → s5 port 1 | Success | 14 | Exhausted | h1→h3 ~10.5 Gbit/s and h6→h5 ~14.3 Gbit/s |
| gpt-6-astra | Correct class (traffic-control shaping / queueing); exact mechanism left open | Exact: s1 port 4 ↔ s5 port 1 | Success (mechanism hedged) | 14 | Exhausted | h1→h3 ~12.5 Gbit/s and h6→h5 ~13.9 Gbit/s; also h5→h1 |

Pilot score: **4 / 4 success**, of which Luna’s location and Astra’s mechanism are hedged. This is one run each.

## What each model said

### gpt-5.6-luna

Diagnosis: throughput impairment on the s1–s5 segment or immediately beyond it; rate limiting, queueing, or software datapath rather than a down link. h1→h5 and h1→h6 about 0.52 Mbit/s sent with 0 bytes received; h1→h4 about 7.38 Gbit/s. Ping h1→h5 succeeded with about 116–230 ms RTT.

Iperf reading: used the sender rate and treated receiver 0 as data, not a failed command.

Calls, in order: `get_topology`; `iperf` h1→h5 (3 s); `get_port_status` s3, s5; `get_flow_table` s3, s1, s5; `ping` h1→h5 count 5; `get_port_stats` s3, s1, s5; `iperf` h1→h4, h1→h5, h1→h6.

The bypass test was call 12, so a 10-call budget would have stopped before it. Invalid calls: 0.

Elapsed 57.9 s. First visible token 53.2 s. Tokens in 127760 (cached 114113), out 1709 (reasoning 930), total 129469. Model requests 15. Estimated cost $0.0071. Conversation `b2fd8d71564040f892cc1d5cb5360868`.

### gpt-5.6-terra

Diagnosis: the s1–s5 link, s1 port 4 ↔ s5 port 1. Receiver throughput on the 5 s h1→h5 test about 0.20 Mbit/s. h2→h5 and h2→h6 delivered 0 receiver bytes while the sender transmitted about 0.35 Mbit/s. h1→h3 about 11.1 Gbit/s. Ping loss 0 with RTT about 16–200 ms. Counters showed no ONOS drops; the model said they cannot separate competing traffic, a bandwidth policy, and delay.

Iperf reading: reported both sides and did not treat receiver 0 as a command failure.

Calls: `get_topology`; `iperf` h1→h5 (5 s); `ping` h1→h5 count 10; `get_flow_table` s3, s1, s5; `get_port_stats` s3, s1, s5; `iperf` h2→h5, h2→h6, h1→h3.

The path that leaves s1 toward s4 (h1→h3) was call 12. The model stopped at 12 calls. Invalid calls: 0.

Elapsed 79.7 s. First visible token 72.9 s. Tokens in 105411 (cached 92387), out 2045 (reasoning 1331), total 107456. Model requests 13. Estimated cost $0.0691. Conversation `83a43437d79d4ee8aea8a39143e95155`.

### gpt-5.6-sol

Diagnosis: s1–s5, forwarding direction s1 port 4 → s5 port 1; likely rate limiting, shaping, or delay. h1→h5 sender about 0.35 Mbit/s. h2→h5 and h1→h6 similarly slow. h1→h3 about 10.46 Gbit/s. h3→h5 about 0.35 Mbit/s. h6→h5 about 14.33 Gbit/s. Ports enabled, no ONOS drops.

Iperf reading: quoted sender throughput for the impaired tests.

Calls: `get_topology`; `ping` h1→h5 count 5; `iperf` h1→h5, h2→h5, h1→h6; `get_flow_table` s3, s1; `iperf` h1→h3, h3→h5, h6→h5; `get_port_status` s1, s5; `get_port_stats` s1, s5.

h6→h5, the local s5 comparison, was call 10. Invalid calls: 0.

Elapsed 82.7 s. First visible token 77.7 s. Tokens in 100895 (cached 89522), out 1364 (reasoning 680), total 102259. Model requests 15. Estimated cost $0.1086. Conversation `f1425d7536914a17be14e7ac2d759066`.

### gpt-6-astra

Diagnosis: s1 port 4 ↔ s5 port 1, not specific to h1 or h5. h1→h5, h3→h5, and h1→h6 received 0 bytes; the h1→h5 sender reported 256 KiB. h1→h3 about 12.49 Gbit/s. h6→h5 about 13.89 Gbit/s. h5→h1 about 5.08 Mbit/s at the receiver. Ping 5/5 with RTT about 30–77 ms. The model named traffic-control shaping, delay, or queue drops as the next check and said the measurements do not establish the exact mechanism or direction.

Iperf reading: explicitly paired “no payload received” with the sender byte count.

Calls: `get_topology`; `ping` h1→h5 count 5; `iperf` h1→h5 (5 s); `get_flow_table` s3, s1, s5; `get_port_stats` s1; `iperf` h1→h3, h3→h5, h6→h5, h1→h6, h5→h1; `get_port_stats` s5; `get_flow_table` s4.

h6→h5 was call 10. h5→h1 was call 13 and needed the extra budget. Invalid calls: 0.

Elapsed 78.1 s. First visible token 25.6 s. Tokens in 122010 (cached 108459), out 835 (reasoning 29), total 122845. Model requests 15. Estimated cost $0.2857. Conversation `0df5a9e5d65941cc9d4b7ed4078359d1`.

Costs are estimates from the price constants in `agent/config.py`, not an invoice. Four runs total about $0.47.

## Comparison with the PR #2 F2 pilot

PR #2 (WSL2, 23 September 2026, one run each, medium, 10 tool calls, delay 0) scored F2 **1 / 4**: Terra success (hedged), Sol partial, Luna fail, Astra fail. Every F2 run used all 10 calls. Luna treated a 0-byte iperf as an invalid test. Astra named the right next comparison and had no calls left.

| Model | PR #2 F2 | This pilot | Sender/receiver fields | Extra calls |
| --- | --- | --- | --- | --- |
| luna | Fail. 10/10. ~$0.0057, 56.3 s. | Success (hedged). 14/14. ~$0.0071, 57.9 s. | Used. Previously treated 0 bytes as a bad test. | The h1→h4 bypass was call 12. |
| terra | Success (hedged). 10/10. ~$0.0545, 69.0 s. | Success, exact ports. 12/14. ~$0.0691, 79.7 s. | Used both sides, including receiver 0 with sender progress. | The h1→h3 bypass was call 12. |
| sol | Partial (type only). 10/10. ~$0.0968, 83.5 s. Comparisons stayed on s1–s5. | Success, exact direction. 14/14. ~$0.1086, 82.7 s. | Quoted sender rate on the impaired tests. | h6→h5 fit in call 10; port stats used the extra calls. |
| astra | Fail. 10/10. ~$0.2129, 53.4 s. Wanted h6→h5 with no calls left. | Success (mechanism open). 14/14. ~$0.2857, 78.1 s. | Paired sender bytes with 0 received. | h6→h5 was call 10; h5→h1 was call 13. |

Qualitative reading only, n=1:

- The split sender/receiver result is what stopped the “unusable test” reading. All four models treated receiver 0 with sender progress as a measurement.
- The four extra calls mattered most for Luna and Terra, whose first path that avoids s1–s5 was call 12. Sol and Astra reached a local s5 comparison on call 10, which the old budget could have contained, but in PR #2 they spent those calls elsewhere while staring at a 0-byte result.
- Localisation moved from 1/4 to 4/4 in this single pass. That is not a statistical result.
- Token and cost rose for every model versus that model’s PR #2 F2 run (more tool observations and, for three models, two more model requests). Astra’s elapsed time rose from 53 s to 78 s. Luna’s elapsed time stayed near 58 s. No run approached the 300 s turn limit.

## Are the current tools enough?

They were enough, in this one pass, to localise the impairment to s1↔s5 and to recognise a collapse in delivered throughput. They were not enough to separate competing traffic, an imposed rate, and added delay. All four models said ONOS port counters showed no drops or errors and asked for queue or traffic-control statistics the tools do not provide.

`get_link_metrics` is still justified for that remaining gap, not because localisation failed. The fields the failed distinction actually needs are queue backlog, overlimit delta, and requeue delta. A longer rate window is secondary: Luna already saw on the order of 5 Mbit/s on the s1–s5 ports, so the old “1 s sample reads 0” problem was not what blocked these four answers. The tool must not copy the configured rate, burst, or latency.

Do not treat 14 as a measured optimum. It is the budget that let the two models which needed a twelfth call finish the bypass. Terra then stopped. A later formal design can adopt 14 as the candidate and leave the source default at 10 until that design is accepted.

## Suggested next phase

Keep this as pilot evidence. Before any formal repeat, decide the queue-counter tool separately, and handle the ONOS cold-restart issue separately. Do not change F2, the topology, or the experiment matrix on the basis of these four runs.
