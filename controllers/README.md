# Controllers

## Status: historical Ryu reference

ONOS 2.7.0 is the runtime controller. See
`docs/decisions/onos-controller-decision.md` and `docs/setup/onos-setup.md`.
Deterministic forwarding is installed by `forwarding/baseline_forwarding.py`
(unicast priority 41000, ARP-tree priority 42000).

`main_controller.py` was written for the earlier Ryu plan. Ryu is not installed.
Do not run this file. It is kept as a design note, not as the next milestone.
Its priorities and cookie do not match the implemented ONOS baseline. The
historical sketch used priority 100 and cookie `0x1000`. The running provisioner
uses priorities 41000 and 42000. Do not re-implement this file.

## Ryu-era files

| File | Status |
| --- | --- |
| `main_controller.py` | Historical Ryu sketch. Not runnable. Not the ONOS baseline. |

Do not run `topologies/main_topology.py` in standalone `ovsbr` mode. It has
redundant physical links and must be driven by a controller.
