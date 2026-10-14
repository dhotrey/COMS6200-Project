# LLM Diagnosis Test Results

September 2026 pilots. These 20 WSL2 runs are not the completed evaluation.
The completed dataset is `evidence/experiments/sweep/sweep-2026-10/`
(525 final trials, 527 attempt rows).

Summary of early LLM diagnosis tests against Fault Catalogue v1 (F1–F5), run through
the `agent/` chat harness. Raw per-run records stay in dated evidence files
under `evidence/progress/llm/`. Do not add the later sweep results to this file.

**Status:** 🟡 one run per scenario and model (20 runs) on WSL2. Not yet run on
the Ubuntu reference host. Scoring is provisional (team review pending).

---

## Test setup

| Item | Value |
| --- | --- |
| Date | 23 September 2026 |
| Environment | WSL2 Ubuntu 24.04.4 on Windows 11 — capability-equivalent, **not** the reference host |
| Harness | `agent/` chat harness → Cloudflare AI Gateway (`/openai/responses`, cache bypassed) |
| Repository | `master` @ `5877bdc` plus uncommitted `feature/f2-f5-llm-scenarios` changes |
| System prompt | `agent/prompt.md` (sha256 `b735ca13…a2ccbc`) |
| Models | `gpt-5.6-luna`, `gpt-5.6-terra`, `gpt-5.6-sol`, `gpt-6-astra` |
| Reasoning effort | medium |
| Limits | 10 tool calls and 300 s per turn; tool delays 0 |
| Runs | 1 per scenario and model |

Each run: load the scenario, start a new conversation, send the symptom-only
prompt, read the answer. Scenario ids are never sent to the model.

## Prompts

| Scenario | Prompt |
| --- | --- |
| F1, F3, F4 | “h1 can no longer reach h5. Diagnose and localise the fault.” |
| F2 | “Transfers from h1 to h5 are very slow. Investigate and localise the cause.” |
| F5 | “h1 and h2 can no longer reach h5. Diagnose and localise the fault.” |

## Scoring

| Score | Meaning |
| --- | --- |
| ✅ Success | Correct fault type **and** correct location |
| 🟠 Partial | Only one of the two |
| ❌ Fail | Neither |

Wrong secondary claims are noted but do not change the score.

## Results

| Scenario | Ground truth | gpt-5.6-luna | gpt-5.6-terra | gpt-5.6-sol | gpt-6-astra | Success |
| --- | --- | --- | --- | --- | --- | --- |
| F1 | Link failure s3:1 ↔ s1:2 | ✅ | ✅ | ✅ | ✅ | 4 / 4 |
| F2 | Congestion on s1:4 ↔ s5:1 | ❌ | ✅ ¹ | 🟠 | ❌ | 1 / 4 |
| F3 | Drop rule on s3 for h1→h5 | ✅ | ✅ | ✅ | ✅ | 4 / 4 |
| F4 | Loop s3 → s4 → s1 for h1→h5 | ✅ | ✅ | ✅ | ✅ | 4 / 4 |
| F5 | Missing h5 rule on s3 | ✅ | 🟠 | ✅ | ✅ | 3 / 4 |
| **Success** | | **4 / 5** | **4 / 5** | **4 / 5** | **4 / 5** | **16 / 20** |

¹ Hedged: “most plausibly the s1–s5 segment”.

Partials: Terra on F5, Sol on F2. Every model missed exactly one scenario;
F2 is the only scenario that most models got wrong.

## Notes by scenario

- **F1** — All four models found the s1:2 ↔ s3:1 link down. Luna and Sol also
  described the baseline's lack of rerouting as a controller failure; Terra
  and Astra noted the rules had not rerouted without calling it a fault. The
  baseline is static by design.
- **F2** — The hardest scenario. The bottleneck is a Linux `tc` rule that ONOS
  does not report, agent `iperf` returned 0 bytes, and the ~1 s port-rate
  samples read near zero. Every run used all 10 tool calls.
  - Luna: saw high RTT on s3 → s1 → s5, treated the 0-byte `iperf` as a broken
    test, did not localise.
  - Terra: congestion “most plausibly the s1–s5 segment”, partly based on
    cumulative counters that include traffic from earlier `iperf` tests.
  - Sol: named shaping/congestion but blamed the h1↔h5 flow; its comparison
    pairs (h1→h6, h2→h5) cross the same s1–s5 link.
  - Astra: narrowed to s1–s5, s5–h5 or h5 and proposed the right next test,
    but had no tool calls left.
- **F3** — All four found the priority-50000 `NOACTION` rule on s3 for h1→h5.
  Astra confirmed it by watching the rule's counter rise during a re-test.
- **F4** — All four traced the loop s3:5 → s4:1 → s1:2. Terra misstated where
  s3 port 1 leads (s1, not s2); Sol blamed only the s1 rule, although all
  three loop rules need removing.
- **F5** — Luna, Sol and Astra found that s3 has no rule for h5; Sol and Astra
  gave the exact missing rule (priority 41000, output s3 port 1). Terra
  localised to s3's forwarding for h5 but never read s3's flow table.

## Cost and time

| Model | Total cost (5 runs) | Avg cost / run | Avg time / run | Avg tool calls |
| --- | ---: | ---: | ---: | ---: |
| gpt-5.6-luna | ~$0.024 | ~$0.005 | 42 s | 9.8 |
| gpt-5.6-terra | ~$0.225 | ~$0.045 | 56 s | 9.4 |
| gpt-5.6-sol | ~$0.375 | ~$0.075 | 67 s | 9.0 |
| gpt-6-astra | ~$0.789 | ~$0.158 | 45 s | 9.0 |

All 20 runs: ~$1.41. Costs are estimates from the dated price constants in
`agent/config.py`, not a Cloudflare invoice. Per-run tokens, costs and times
are in the evidence files.

## Observations

- All five scenarios were solved by at least one model; accuracy was the same
  for every model (4 / 5), so cost and speed separate them: Luna was cheapest
  and fastest to comparable accuracy in this single-run test.
- The 10-call tool budget was nearly always used up. F2 in particular ran out
  of calls before the models could compare a path that avoids s1–s5.
- Port counters are cumulative and include traffic from earlier tests on the
  same testbed.

## Harness path check (no model)

`./scripts/verify_agent_scenarios.sh` on WSL2, 23 September 2026: **all five
scenarios pass**. F1, F2, F4 and F5 passed in the first run. F3's fault behaved
correctly there, but the check expected an empty treatment where ONOS reports
`NOACTION`; after fixing the check, the F3 re-run passed.

## Still to do

- Team review of the scores
- Repeat runs to check consistency (especially F2 and F5)
- Runs on the Ubuntu reference host
- F6 extension: requires a new fault catalogue version (team decision)

## Evidence

- `evidence/progress/llm/llm-diagnosis-f1-f5-wsl-2026-09-23.txt` — gpt-5.6-luna F1–F5; Terra and Sol on F1
- `evidence/progress/llm/llm-diagnosis-models-f1-f5-wsl-2026-09-23.txt` — Terra, Sol, Astra on F2–F5; Astra on F1
- `evidence/progress/llm/agent-scenario-path-wsl-2026-09-23.txt` — harness path check
- Conversations in Cloudflare D1, titled `Test Fn · <model> · medium`
