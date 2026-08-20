# Controllers

## Status: provisional, superseded as executable code

ONOS 2.7.0 was adopted as the project SDN controller on 20 August 2026 after
runtime verification on the team server. See
`docs/decisions/onos-controller-decision.md` and `docs/setup/onos-setup.md`.

`main_controller.py` was written for the earlier Ryu plan. Ryu is not installed
and is no longer on the critical path, so this file is **not currently
runnable** in the project environment.

It is kept deliberately, not deleted, because its design is still the
specification for the next milestone:

- s1 as the active core, s2 as a redundant core excluded from baseline forwarding
- a deterministic loop-free active tree over the physically cyclic topology
- the explicit destination-MAC to output-port map for s1 and s3–s6
- loop-free ARP handling restricted to active-tree ports
- baseline flow identity: priority 100, cookie `0x1000`

That forwarding design must be re-expressed against ONOS (for example through
flow objectives or intents) rather than as a Ryu application. Removing or
refactoring these files will be a separate, deliberate commit.

## Ryu-era files

| File | Status |
| --- | --- |
| `main_controller.py` | Provisional Ryu implementation. Not runnable. Design reference only. |

Do not run `topologies/main_topology.py` in standalone `ovsbr` mode. It has
redundant physical links and must be driven by a controller.
