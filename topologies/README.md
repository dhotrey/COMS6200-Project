# Topologies

## Final six-switch/eight-host project topology

This is the actual COMS6200 physical topology. It is not a progress-capability
test.

File: `main_topology.py`

Registered Mininet topo name: `main6s8h`

Controller: ONOS 2.7.0 (`docs/setup/onos-setup.md`). The earlier Ryu file
`controllers/main_controller.py` is retained only as a forwarding-design
reference and is not used to launch this topology.

This topology contains redundant physical links and **MUST** be run with the
project controller. It is not intended for `ovsbr` standalone bridge mode.

```
                    s1 -------- s2
                   /|\\          /|\\
                  / | \\        / | \\
                 /  |  \\      /  |  \\
               s3---s4   s5   s6
               |\\   |\\   |\\   |\\
               h1   h3   h5   h7
               h2   h4    \\   h8
                          h6 (eth0->s5, eth1->s6)
```

Roles:

- s1 = Core A (initial active core)
- s2 = Core B (physically present; excluded from baseline host forwarding)
- s3 = User Access A (h1, h2)
- s4 = User Access B (h3, h4)
- s5 = Server Access (h5, h6 primary)
- s6 = Admin/Test Access (h7, h8; optional h6 secondary)

The extra links increase diagnostic diversity, not topology size for its own
sake:

- `s3-s4` is a dedicated **access-edge test link** for controlled
  forwarding-loop and unexpected/core-bypass experiments.
- `h6-s6` is an **optional** secondary physical attachment for a later
  multihomed-host/failover experiment. It is not one of the five mandatory
  fault scenarios.

All hosts are in `10.0.0.0/24` with deterministic MACs `00:00:00:00:00:0N`.
All switches request OpenFlow 1.3 and `failMode=secure`. STP is not enabled.

### Counts

| Class | Count |
|-------|------:|
| Switches | 6 |
| Hosts | 8 |
| Inter-switch physical links | 10 |
| Host-switch physical links | 9 |
| Total physical links | 19 |

### Port map

| Link | Port A | Port B | Baseline use |
|------|--------|--------|--------------|
| s1-s2 | s1:1 | s2:1 | unused (inter-core) |
| s1-s3 | s1:2 | s3:1 | used (active core) |
| s1-s4 | s1:3 | s4:1 | used (active core) |
| s1-s5 | s1:4 | s5:1 | used (active core) |
| s1-s6 | s1:5 | s6:1 | used (active core) |
| s2-s3 | s2:2 | s3:2 | unused (redundant core) |
| s2-s4 | s2:3 | s4:2 | unused (redundant core) |
| s2-s5 | s2:4 | s5:2 | unused (redundant core) |
| s2-s6 | s2:5 | s6:2 | unused (redundant core) |
| s3-s4 | s3:5 | s4:5 | unused (access-edge test) |
| s3-h1 | s3:3 | h1-eth0 | used |
| s3-h2 | s3:4 | h2-eth0 | used |
| s4-h3 | s4:3 | h3-eth0 | used |
| s4-h4 | s4:4 | h4-eth0 | used |
| s5-h5 | s5:3 | h5-eth0 | used |
| s5-h6 | s5:4 | h6-eth0 | used (h6 primary) |
| s6-h7 | s6:3 | h7-eth0 | used |
| s6-h8 | s6:4 | h8-eth0 | used |
| s6-h6 | s6:5 | h6-eth1 | unused (h6 secondary) |

Baseline forwarding, when implemented, still uses s1 as the active core.
Remote access-switch traffic is s3/s4/s5/s6 → s1. The s2 uplinks, s1-s2,
s3-s4 and h6-s6 links stay physically present but are reserved for
controlled experiments.

### h6 dual attachment

- Primary: `h6-eth0` ↔ `s5:4`, IPv4 `10.0.0.6/24`, MAC `00:00:00:00:00:06`.
- Secondary: `h6-eth1` ↔ `s6:5`, MAC `00:00:00:00:06:02`, **no baseline IPv4**.

Mininet applies the host IPv4 address only to the default interface
(`h6-eth0`). The secondary interface is created without an IPv4 address so
normal behaviour stays deterministic. No bonding, LACP, MLAG, VRRP or
automatic host failover is implemented. The secondary path is activated only
by a later optional experiment.

### Launch workflow

The controller is **ONOS 2.7.0**, running in a Docker container. See
`docs/setup/onos-setup.md` for installation and verification, and
`docs/decisions/onos-controller-decision.md` for why ONOS replaced the earlier
Ryu plan. The enhanced 19-link topology was runtime-verified against ONOS on
20 August 2026.

Run these commands from the repository root on the Ubuntu Mininet server.

**STEP 1 — Ensure ONOS is running**

```bash
./setup/setup_onos.sh          # first run, or after the container was removed
docker start onos              # if the container already exists
./scripts/verify_onos.sh       # read-only health and topology check
```

Wait until ONOS is listening on `127.0.0.1:6653` before starting Mininet. On a
small server this takes roughly 60–90 seconds.

The earlier Ryu workflow (`ryu-manager controllers/main_controller.py`) no longer
applies. Ryu is not installed, and `controllers/main_controller.py` is retained
only as a design reference.

**STEP 2 — Mininet**

```bash
sudo mn \
  --custom topologies/main_topology.py \
  --topo main6s8h \
  --controller=remote,ip=127.0.0.1,port=6653 \
  --switch=ovsk
```

The topology itself requests OpenFlow 1.3 and secure fail mode, so no extra
switch options are needed.

Inside Mininet, the initial verification commands are:

```
nodes
net
links
```

Also:

```
sh ovs-vsctl show
```

From another shell while Mininet is running:

```bash
sudo ./scripts/verify_main_openflow.sh
sudo ./scripts/verify_onos.sh
```

Both scripts are read-only. `verify_main_openflow.sh` prints bridge protocols,
fail-mode, controller attachment and OpenFlow 1.3 flow tables.
`verify_onos.sh` prints controller-side device, link, host and flow state.

**`pingall` does not succeed yet, and that is expected.** No forwarding
application is active, so the switches only carry ONOS's LLDP/BDDP/ARP
punt-to-controller rules. Deterministic loop-free forwarding across the
redundant links is the next milestone. Do not work around this by enabling OVS
NORMAL mode, standalone bridge mode, STP, or ONOS reactive forwarding.

Verified against ONOS on 20 August 2026 for this enhanced 19-link topology:
all six switches connected over OpenFlow 1.3 with secure fail mode; ONOS
discovered 6 devices (`of:0000000000000001` through `of:0000000000000006`) and
20 directed links representing the 10 physical switch-switch links, including
`s3:5 ↔ s4:5`. Host `h6` had `h6-eth0` on `s5:4` and `h6-eth1` on `s6:5`. See
`evidence/progress/onos/main6s8h-enhanced-2026-08-20.txt`.

### Cleanup after exiting Mininet

```bash
sudo mn -c
```

## Custom progress topology

This topology reproduces the early five-switch/two-host Mininet progress
evidence and is **not** the final six-switch/eight-host OpenFlow topology.

Topology:

```
          s1
          |
          s2
        / | \
      s3  s4  s5
      |       |
      h1      h2
```

File: `progress_custom_topology.py`

Registered Mininet topo name: `progress5s2h`

### Launch from repository root

```bash
sudo mn --custom topologies/progress_custom_topology.py --topo progress5s2h --controller=none --switch ovsbr
```

This starts the Mininet CLI. It does not start ONOS or configure OpenFlow 1.3.

### Useful Mininet commands

```
nodes
net
links
h1 ping -c 5 h2
```

### Cleanup after exit

```bash
sudo mn -c
```

This cleanup command is separate from the launch command.

## 10 Mbit/s bandwidth progress test

Simple topology: `h1 ---- s1 ---- h2`

The `h1-s1` link is configured with `bw=10`. The `s1-h2` link is unconstrained.

File: `progress_tc_topology.py`

Registered Mininet topo name: `progressbw10`

Launch from repository root:

```bash
sudo mn --custom topologies/progress_tc_topology.py \
  --topo progressbw10 \
  --link tc \
  --controller=none \
  --switch ovsbr
```

Inside Mininet:

```
nodes
net
links
h2 iperf3 -s -D
h1 iperf3 -c 10.0.0.2 -t 5
h2 pkill -f iperf3
```

Cleanup after exit:

```bash
sudo mn -c
```

Observed result on the Mininet server (20 Aug 2026):

- configured: 10 Mbit/s on `h1-s1`
- iperf3 receiver: 9.38 Mbit/s over 5.03 s (`h1 iperf3 -c 10.0.0.2 -t 5`)
- sender rate 12.2 Mbit/s is not the delivered bottleneck measurement

This is an early Mininet/TCLink capability test, not a final LLM troubleshooting
experiment result.

## Impaired progress test

Same structure: `h1 ---- s1 ---- h2`

The `h1-s1` link is configured with `bw=1`, `delay='5ms'` and `loss=10`.

Registered Mininet topo name: `progressimpaired`

Launch from repository root:

```bash
sudo mn --custom topologies/progress_tc_topology.py \
  --topo progressimpaired \
  --link tc \
  --controller=none \
  --switch ovsbr
```

Observed result on the Mininet server (20 Aug 2026):

- configured: 1 Mbit/s, 5 ms delay, 10% loss per affected direction
- 100-packet ping (`h1 ping -c 100 -i 0.2 h2`): 81/100 replies, 19% round-trip loss
- RTT min/avg/max/mdev = 10.115/10.171/10.690/0.063 ms
- iperf3 receiver: 832 Kbit/s over 10.08 s (`h1 iperf3 -c 10.0.0.2 -t 10`)
- 77 TCP retransmissions

Configured per-direction loss remains 10%. The 19% figure is observed
end-to-end ICMP round-trip loss, not a claim that the configured loss was 19%.

This is an early Mininet/TCLink capability test, not a final LLM troubleshooting
experiment result.
