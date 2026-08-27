# Faults package (M5)

Operator/evaluator fault injection for COMS6200. **Not** an LLM tool and
**not** imported by `telemetry/`.

Currently runnable:

- **F1** — primary `s3`↔`s1` link failure (`s3-eth1` / `s1-eth2` from
  `topologies/spec.py`)

Planned later: F2–F5.

## CLI

```bash
# Requires root (does not invoke sudo itself)
python3 -m faults.cli inject --scenario F1
python3 -m faults.cli status
python3 -m faults.cli reset
python3 -m faults.cli reset --force-f1   # crash recovery for known F1 ifaces
```

JSON on stdout. No `--interface`, `--cmd`, `--pid`, or arbitrary links.

## Design

| Piece | Role |
| --- | --- |
| `scenarios.py` | Allow-listed scenarios + evaluator ground truth |
| `injector.py` | Validate OVS bridges, `ip link set` down/up, rollback on failure |
| `state.py` | Ephemeral `/run/coms6200/fault-state.json` (0600) |
| `cli.py` | Thin operator CLI |

Mechanism: fixed argv `ip link set dev <iface> down|up` on both veth ends.
Before mutation: interface exists and `ovs-vsctl port-to-br` matches the
expected switch.

## Ground truth boundary

State may include evaluator-only fields (`scenario_id`, `fault_family`,
location, expected correction). Telemetry must never read this file or import
`faults`.

## Verification

```bash
python3 tests/test_faults.py
./scripts/verify_fault_f1.sh
```

Live script requires healthy ONOS + `main6s8h` + M3 baseline first.
