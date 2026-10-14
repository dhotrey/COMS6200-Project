# LLM diagnosis judge prompts

Select one self-contained rubric by the topology and injected fault:

```text
judge/
  main6s8h/Fault1.md ... Fault5.md
  ring5s5h/Fault1.md ... Fault5.md
  tree5s8h/Fault1.md ... Fault5.md
```

The directory names match `COMS6200_TOPOLOGY`. `tree5s8h` is the retained selector for the current seven-switch/eight-host tree.

Send the appropriate Markdown document as the judge's instruction and the final diagnosing assistant response as a separate input. Each document contains the required fault type, location, optional supporting observations, unsuccessful cases, and the same JSON output contract. Every rubric is self-contained; the judge does not need this README or another prompt file.

`full_diagnosis_correct` is 1 only when both `family_correct` and `location_correct` are 1. A symptom report alone is not a diagnosis. Score the primary conclusion, not a rejected hypothesis or an unranked list of possibilities. Supporting symptoms are not a requirement to enumerate every affected host.

These rubrics contain evaluator-only ground truth. Keep them out of the diagnosing agent's messages, tools and telemetry. A response-only judge assesses agreement with ground truth; it cannot independently verify tool calls or runtime observations.

Sources:

- `faults/scenarios.py`: frozen main catalogue v1.
- `faults/ring_scenarios.py`: ring catalogue. Source status remains `draft`; the completed sweep used it.
- `faults/tree_scenarios.py`: tree catalogue. Source status remains `draft`; the completed sweep used it. The selector `tree5s8h` is a 7-switch / 8-host tree.
- `forwarding/baseline_forwarding.py` and `topologies/*_spec.py`: forwarding paths, ports and host attachments.
- `docs/experiments/protocol-v1.md`, sections 7 and 9: existing symptom prompts and main-topology family/location scoring.

The tree rubrics use the current seven-switch forwarding plan for supporting symptoms. Some tree catalogue scope descriptions still refer to the earlier layout: F1 partitions h1–h4 from h5–h8; F5 prevents h1–h4 from reaching h5 through s2.

The chat UI now automatically evaluates successfully completed answers when F1–F5
is selected. `agent/judge.py` sends a typed Choice question to the OpenAI Decisions
API (`gpt-6-luna`) through the configured Cloudflare AI Gateway and BYOK route. It
combines the scenario's factual criteria with
[shared four-level criteria](grading.md), omitting the legacy **Judge output** JSON
instructions from the API prompt. The verdict's criteria appear immediately in
the UI. Optional observations are never mandatory.

**Explain decision** makes a separate, tool-free Responses request using
`gpt-6.1-sol` / `high`. It explains the assessment against the captured rubric,
and may flag an apparent disagreement; it never changes the recorded verdict.
Rubrics, verdicts and explanations stay out of the diagnosis provider history.
The complete result, rubric snapshot/hash and separate usage measurements are
saved with the assistant answer. Reopening an answer does not rerun grading.
The existing four verdicts, confidence and probability list are preserved in the
operator payload. No database schema or separate judge credential is required.
See [agent setup and grading](../agent/README.md#automatic-diagnosis-assessment)
and the [OpenAI Decisions documentation](https://developers.openai.com/api/docs/guides/decisions).

The command-line sweep (`experiments/sweep.py`) grades every trial, the scripted
baseline included, with the judge configured at run time and the same rubrics,
alongside its rule-based cross-check.

`evidence/experiments/sweep/sweep-2026-10/` was graded by the same OpenAI
Decisions judge (`gpt-6-luna`). Those stored verdicts are preserved and are not
recomputed by this implementation change.

`experiments/evaluator.py` and the frozen protocol's binary scoring are unchanged.
That evaluator continues to use main-topology locations. Ring and tree rubrics
describe the catalogues used by the completed sweep. Their source status field
was not changed to a frozen version.

