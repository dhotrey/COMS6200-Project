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
- `faults/ring_scenarios.py`: draft ring catalogue.
- `faults/tree_scenarios.py`: draft tree catalogue.
- `forwarding/baseline_forwarding.py` and `topologies/*_spec.py`: forwarding paths, ports and host attachments.
- `docs/experiments/protocol-v1.md`, sections 7 and 9: existing symptom prompts and main-topology family/location scoring.

The tree rubrics use the current seven-switch forwarding plan for supporting symptoms. Some tree catalogue scope descriptions still refer to the earlier layout: F1 partitions h1–h4 from h5–h8; F5 prevents h1–h4 from reaching h5 through s2.

These files prepare a future LLM judge only. No judge API calls, UI integration or changes to `experiments/evaluator.py` are included. That evaluator continues to use main-topology locations. Ring/tree rubrics describe the implemented catalogues and do not certify a live testbed run.

