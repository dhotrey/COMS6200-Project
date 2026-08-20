# Deterministic baseline forwarding

M3 provisioner for the COMS6200 `main6s8h` topology. It installs explicit
ONOS 2.7.0 flow rules so the eight primary hosts can reach each other on a
single loop-free Layer-2 tree.

This is **not** the telemetry gateway, fault injector, scripted
troubleshooter, or LLM agent.

## Design

Active core: **s1**.

Normal remote paths:

- s3 → s1
- s4 → s1
- s5 → s1
- s6 → s1

Physically present but **outside** baseline forwarding:

- s2 and all s2 access uplinks
- s1–s2
- s3–s4 access-edge test link
- h6–s6 secondary (`h6-eth1`, no baseline IPv4)

The extra links remain discovered by ONOS for later controlled experiments.
They must not carry normal host traffic.

Do **not** enable `org.onosproject.fwd`, OVS `NORMAL`, STP, or `OFPP_FLOOD`.

## Host destination mapping

Unicast match: `ETH_DST` = primary host MAC.

| Switch | h1 | h2 | h3 | h4 | h5 | h6 | h7 | h8 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| s1 | 2 | 2 | 3 | 3 | 4 | 4 | 5 | 5 |
| s3 | 3 | 4 | 1 | 1 | 1 | 1 | 1 | 1 |
| s4 | 1 | 1 | 3 | 4 | 1 | 1 | 1 | 1 |
| s5 | 1 | 1 | 1 | 1 | 3 | 4 | 1 | 1 |
| s6 | 1 | 1 | 1 | 1 | 1 | 1 | 3 | 4 |
| s2 | — | — | — | — | — | — | — | — |

h6 baseline destination is the primary attachment on s5 (`h6-eth0`,
`00:00:00:00:00:06`). The secondary MAC `00:00:00:00:06:02` is unused.

## ARP

IPv4 ping needs ARP. Broadcast ARP requests are forwarded only on the active
tree, using ingress-specific rules:

- match `ETH_TYPE=0x0806`, `ETH_DST=ff:ff:ff:ff:ff:ff`, `IN_PORT=<ingress>`
- OUTPUT to every **other** active-tree port on that switch

Active ARP ports:

- s1: 2, 3, 4, 5
- s3 / s4 / s5 / s6: 1, 3, 4
- s2: none

ARP replies are unicast and use the destination-MAC rules.

The installer posts multiple `OUTPUT` instructions in one treatment. If a
future ONOS/OVS build rejects that, stop and use a controlled OpenFlow group;
do not fall back to FLOOD/NORMAL/STP/`fwd`.

## Application ownership

All baseline rules are owned by:

`org.coms6200.baseline`

ONOS registers that application ID when the first flow POST is accepted.
Later work can distinguish:

- ONOS system/control flows (`org.onosproject.core`, priority 40000)
- baseline forwarding (this app)
- future fault-injection / repair flows

`remove` deletes **only** this application's flows.

## Priority policy

Observed ONOS control flows on this testbed (LLDP/BDDP/ARP punt) use
priority **40000**.

| Role | Constant | Value |
| --- | --- | ---: |
| ONOS system/control | leave untouched | 40000 |
| Baseline unicast | `BASELINE_UNICAST_PRIORITY` | 41000 |
| Baseline ARP tree | `BASELINE_ARP_PRIORITY` | 42000 |
| Future injected faults | `FAULT_PRIORITY` | 50000 (reserved, not installed) |

Unicast 41000 outranks the generic ARP punt so ARP *replies* follow dest-MAC
forwarding. ARP-tree 42000 outranks it for broadcasts. Space above 42000 is
kept for later fault rules.

## Commands

From the repository root, on the Linux Mininet/ONOS host:

```bash
export ONOS_USER=onos
export ONOS_PASSWORD='<your ONOS REST password>'
# optional: export ONOS_URL=http://127.0.0.1:8181/onos/v1

python3 forwarding/baseline_forwarding.py install
python3 forwarding/baseline_forwarding.py status
python3 forwarding/baseline_forwarding.py verify
python3 forwarding/baseline_forwarding.py remove
```

`install` is idempotent: it drops stale `org.coms6200.baseline` flows, then
installs the canonical set and checks they reach `ADDED`. `remove` waits until
ONOS finishes `PENDING_REMOVE` so a follow-up `status` sees zero app flows.

ONOS `/hosts` may remain empty while ping works: ARP is forwarded in the data
plane, so `hostprovider` does not see PACKET_IN ARP. That is not a forwarding
failure.

Credentials are read from the environment only. They are never stored in this
repository and are never printed.

## Runtime prerequisites

1. ONOS 2.7.0 healthy (`./scripts/verify_onos.sh`).
2. `org.onosproject.fwd` remains inactive.
3. Clean Mininet, then:

```bash
sudo mn -c
sudo mn --custom topologies/main_topology.py \
  --topo main6s8h \
  --controller=remote,ip=127.0.0.1,port=6653 \
  --switch=ovsk
```

4. Run `install` from another shell. Do not use `--controller=none`, `ovsbr`,
   NORMAL, STP, or `fwd`.

Expected baseline count: **56** flows (40 unicast + 16 ARP-tree).
s1: 12, s2: 0, s3–s6: 11 each. ONOS system flows remain ~18 (3 per switch).

Static tests (no ONOS required):

```bash
python3 tests/test_baseline_forwarding.py
```

## Cleanup

```bash
python3 forwarding/baseline_forwarding.py remove
sudo mn -c
```

Removing baseline flows returns the fabric to discovery-only controller
rules. Host `pingall` will fail again until `install` is re-run. ONOS itself
stays up.

## Relationship to later faults

F4 can later override a narrow flow onto s3–s4. Failover experiments can
later use s2 or h6-eth1. Those rules must use a higher priority than the
baseline entries they intentionally replace. Do not implement faults in this
module.
