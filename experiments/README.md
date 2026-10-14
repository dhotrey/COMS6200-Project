# Protocol v1 evaluator and the completed sweep

`experiments/evaluator.py` scores a diagnosis with the protocol v1 family,
location, and hedge rules. LLM scoring uses the final conclusion paragraph, not a markdown heading.

`experiments/runner.py` runs one non-formal trial: healthy gate, inject, one
diagnosis, score, reset, healthy gate. The diagnostic method is given the
symptom prompt only. Records go to
`evidence/experiments/protocol-v1/dry-runs.jsonl` and are labelled
`DRY RUN / NOT FORMAL DATA`. Formal `runs.jsonl` is not written. These dry runs
are not the completed dataset.

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

## Completed multi-topology evaluation

`experiments/sweep.py` compares the scripted baseline and the study models
(`gpt-5.6-luna`, `gpt-5.6-terra`, `gpt-5.6-sol`, `gpt-6-astra`, `gpt-4.1-mini`,
`gpt-4.1-nano`) on every topology (`main6s8h`, `ring5s5h`, `tree5s8h`) and fault
(F1–F5). The archived records are labelled `EXPLORATORY SWEEP / NOT PROTOCOL V1`
because they are not the protocol-v1 80-trial matrix above. That label is left
unchanged. The sweep is the project's completed repeated evaluation.

The committed run is `evidence/experiments/sweep/sweep-2026-10/` (seed 6202): 525 completed trials, 527 `trials.jsonl` rows, two retried infrastructure failures. Its judge verdicts came from the OpenAI Decisions judge (`gpt-6-luna`). Those stored results are preserved and are not recomputed or rewritten. The protocol-v1 runner above is unchanged and still `main6s8h`-only.

The rule cross-check and the semantic judge are different instruments. The rule scorer reads one conclusion paragraph. The judge reads the answer against a rubric and cannot see the tool trace. Disagreement is expected.

On `ring5s5h`, baseline v1 looks for F1 and F2 on the shortest configured path. Ring forwarding does not use that shortcut, so those two faults sit off the path the baseline checks. That is a baseline limitation, not a testbed failure. The baseline was not changed to match the sweep.

It runs in rounds. Each `run` runs one round on one topology (every method on
every fault once, freshly shuffled) and adds it to the same sweep; repeating the
command adds the next round, and `summary` pools them. Each trial: restart the
network, healthy gate, inject, one diagnosis from the symptom prompt only (new
conversation for models), reset, then score. A preflight first sends each model
one tiny tool-free turn. Infrastructure failures are retried once, then excluded
and reported.

Scoring: the agent's LLM judge (`agent/judge.py` with the `judge/` rubrics) is
primary; `experiments/sweep_scoring.py` applies the protocol v1 keyword rubric
with each catalogue's locations as a cross-check (on main6s8h it matches
`evaluator.py`, checked in `tests/test_sweep.py`). Trials are published to the
agent's D1 benchmark tables (`experiments/sweep_publish.py`), so sweeps appear on
the results page next to its own benchmarks.

```bash
~/.venvs/coms6200-agent/bin/python -m experiments.sweep plan
sudo ~/.venvs/coms6200-agent/bin/python -m experiments.sweep run --run-id sweep-2026-10 --topology ring5s5h
~/.venvs/coms6200-agent/bin/python -m experiments.sweep publish --run-id sweep-2026-10
python3 -m experiments.sweep summary --run-id sweep-2026-10
```

Setup, options and outputs: `docs/user-guide.md`, section "Multi-topology model
sweep".
