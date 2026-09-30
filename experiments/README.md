# Protocol v1 evaluator and dry-run runner

`experiments/evaluator.py` scores a diagnosis with the protocol v1 family,
location, and hedge rules. LLM scoring uses the final conclusion paragraph, not a markdown heading.

`experiments/runner.py` runs one non-formal trial: healthy gate, inject, one
diagnosis, score, reset, healthy gate. The diagnostic method is given the
symptom prompt only. Records go to
`evidence/experiments/protocol-v1/dry-runs.jsonl` and are labelled
`DRY RUN / NOT FORMAL DATA`. Formal `runs.jsonl` is not written.

```bash
python3 -m experiments check-order
python3 -m experiments dry-run --method baseline --scenario F1
python3 -m experiments paired-dry-run --scenario F2
python3 -m experiments formal
```

`formal` exits non-zero. It checks that the live agent reports default model `gpt-5.6-sol`, effort `medium`, 14 tool calls, 300 seconds, and zero delay. The launcher is disarmed, and it also requires freeze
metadata that this tree does not have: approved model id, effort `medium`,
14 tool calls, 300 seconds, zero tool delay, frozen commit, baseline version,
scoring version, and seeds 6200 and 6201. The approved model id in metadata must be `gpt-5.6-sol`.
