# Fault Catalogue v1 — operator/evaluator injector

**Not an LLM tool.** Telemetry and future agents must never import this package
or read `/run/coms6200/fault-state.json`.

## Catalogue

`FAULT_CATALOGUE_VERSION = "v1"` in `catalogue.py`.

| ID | Family | Mechanism |
| --- | --- | --- |
| F1 | link_failure | `ip link set` down on s3–s1 |
| F2 | congestion | TBF on s1–s5 + background iperf |
| F3 | acl_policy_error | high-priority DROP (`org.coms6200.experiment`) |
| F4 | forwarding_loop | narrow h1→h5 cycle + safety TBF on s3–s4 |
| F5 | missing_flow | delete s3 baseline unicast for h5 |

## CLI

```bash
python3 -m faults.cli inject --scenario F2
python3 -m faults.cli status
python3 -m faults.cli reset
```

Session wrapper (auto-resets an active fault before inject): `./scripts/testbed.sh inject F2`.

Requires root for mutations. Does not invoke `sudo` internally.
No `--interface`, `--cmd`, `--rate`, `--pid`, or arbitrary flow IDs.

## Runtime state

`/run/coms6200/fault-state.json` (dir `0700`, file `0600`). One active fault.

## Reset / recovery

`reset` clears the active scenario. `--force-scenario Fn` / `--force-f1`
recover canonical resources when the state file is missing.

## Verification

- `scripts/verify_fault_f1.sh` … `verify_fault_f5.sh`
- `scripts/verify_fault_catalogue.sh`
