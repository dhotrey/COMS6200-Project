# Fault catalogues — operator/evaluator injector

**Not an LLM tool.** Telemetry and the diagnosing agent must never import this package
or read `/run/coms6200/fault-state.json`.

`COMS6200_TOPOLOGY` selects the catalogue (`registry.py`). All three catalogues use
the same scenario IDs, families, mechanisms and handlers. Only the locations
differ. The tree selector `tree5s8h` is defined in `tree_scenarios.py`. Its source
status, like the ring catalogue, remains `draft`. Both were used by the completed
sweep. The frozen live-verifier record is still main `v1`.

## Fault Catalogue v1 — `main6s8h` (frozen)

`FAULT_CATALOGUE_VERSION = "v1"` in `catalogue.py`; definitions in `scenarios.py`.

| ID | Family | Mechanism |
| --- | --- | --- |
| F1 | link_failure | `ip link set` down on s3–s1 |
| F2 | congestion | TBF on s1–s5 + background iperf |
| F3 | acl_policy_error | high-priority DROP (`org.coms6200.experiment`) |
| F4 | forwarding_loop | narrow h1→h5 cycle + safety TBF on s3–s4 |
| F5 | missing_flow | delete s3 baseline unicast for h5 |

## ring5s5h-v1 — `ring5s5h`

Definitions in `ring_scenarios.py`. `CATALOGUE_STATUS` remains `draft`. The
completed sweep ran these scenarios for five rounds. Same rates, priorities and
workloads as v1.
Every scenario breaks or slows h1→h5, so the v1 symptom prompts still apply.
Baseline forwarding leaves s5–s1 unused, so h1→h5 crosses s1–s2–s3–s4–s5.

| ID | Family | Mechanism | Expected symptoms |
| --- | --- | --- | --- |
| F1 | link_failure | `ip link set` down on s3–s4 (`s3-eth1`, `s4-eth2`) | {h1,h2,h3} ↔ {h4,h5} fail; 8 directed links |
| F2 | congestion | 1 Mbit/s TBF on `s2-eth1` (s2→s3) + background iperf h2→h4 | h1→h5 reachable, throughput ≤ 25% of healthy |
| F3 | acl_policy_error | DROP h1→h5 on s4 (`org.coms6200.experiment`) | h1→h5 fails; h2→h5, h1→h4 work |
| F4 | forwarding_loop | h1→h5 rules on every switch, all clockwise; 2 Mbit/s safety TBF on `s5-eth1` | h1→h5 fails; loop traffic on the unused s5–s1 link |
| F5 | missing_flow | delete s2 baseline unicast for h5 | h1→h5 and h2→h5 fail; h3→h5 works; 37 baseline flows |

After live verification, any change to a target, selector, workload or reset
behaviour needs a new catalogue version.

## Safety checks

- `inject` refuses unless the running switch ports (`sN-ethP` in
  `/sys/class/net`) are exactly the selected topology's (`TOPOLOGY_MISMATCH`).
  Every ring port name also exists in `main6s8h`, and `sudo` drops
  `COMS6200_TOPOLOGY` unless preserved, so the setting alone cannot prove
  which network is running.
- `reset` refuses a state file written by the other catalogue
  (`STATE_CATALOGUE_MISMATCH`). Reset with the `COMS6200_TOPOLOGY` the fault
  was injected under.
- ONOS experiment-flow checks only look at the selected topology's devices.

## CLI

```bash
python3 -m faults.cli inject --scenario F2
python3 -m faults.cli status
python3 -m faults.cli reset
```

Session wrapper (auto-resets an active fault before inject): `./scripts/testbed.sh inject F2`.

Requires root for mutations. Does not invoke `sudo` internally.
No `--interface`, `--cmd`, `--rate`, `--pid`, or arbitrary flow IDs.
For ring5s5h, keep the variable through sudo:
`sudo --preserve-env=COMS6200_TOPOLOGY,ONOS_USER,ONOS_PASSWORD python3 -m faults.cli ...`.

## Runtime state

`/run/coms6200/fault-state.json` (dir `0700`, file `0600`). One active fault.
Its `ground_truth.catalogue_version` records which catalogue injected it.

## Reset / recovery

`reset` clears the active scenario. `--force-scenario Fn` / `--force-f1`
recover the selected catalogue's resources when the state file is missing.
`./scripts/testbed.sh stop` retries `--force-scenario` for each of F1–F5 if the
normal reset fails.

## Verification

- main6s8h (frozen v1 record): `scripts/verify_fault_f1.sh` …
  `verify_fault_f5.sh`, `scripts/verify_fault_catalogue.sh`
- `scripts/verify_agent_scenarios.sh` — main6s8h scenarios through the chat
  harness load/reset and agent tool path (results in
  `docs/results/llm-diagnosis.md`)
- Any catalogue: `scripts/verify_faults.py` checks the expected symptoms in
  `expectations.py`. Healthy-gate counts come from the selected topology:
  directed links = 2 × inter-switch links, baseline flows from the forwarding
  plan, and every host pair.

```bash
export COMS6200_TOPOLOGY=ring5s5h ONOS_USER=onos ONOS_PASSWORD=rocks
sudo --preserve-env=COMS6200_TOPOLOGY,ONOS_USER,ONOS_PASSWORD python3 scripts/verify_faults.py
```

Static checks: `python3 tests/test_ring_faults.py` walks packets through the
baseline tables with each fault applied, and confirms the expected symptoms
follow from where each fault is placed, for both catalogues.
