# Topologies

## Final six-switch/eight-host project topology

This is the actual COMS6200 physical topology. It is not a progress-capability
test.

Configured identities live in `spec.py` and are imported by
`main_topology.py` (Mininet construction) and the telemetry gateway.
Do not add a second independently maintained host/port map.


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

Run these commands from the repository root on the Linux Mininet host
(Ubuntu 24.04 verified reference, or the UQ Kali VM as a compatibility target).

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

Session helper (background, no CLI): `./scripts/testbed.sh start` from the repository root. That also starts OVS/ONOS if needed and installs baseline flows. Manual equivalent:

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
./scripts/verify_onos.sh
```

Both scripts are read-only. `verify_main_openflow.sh` prints bridge protocols,
fail-mode, controller attachment and OpenFlow 1.3 flow tables.
`verify_onos.sh` prints controller-side device, link, host and flow state.

**`pingall` succeeds only after M3 baseline flows are installed.** From another shell:

```bash
export ONOS_USER=onos
export ONOS_PASSWORD=rocks
python3 forwarding/baseline_forwarding.py install
```

Do not work around missing flows by enabling OVS NORMAL mode, standalone bridge mode, STP, or ONOS reactive forwarding. See `forwarding/README.md`.

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

## Five-switch ring topology

A second ONOS topology for running fault scenarios on a different shape. It
does not replace `main6s8h`.

Configured identities and the port map live in `ring_spec.py`.
`ring_topology.py` builds the Mininet topology directly from that spec, so
there is no second port map to keep in sync.

Registered Mininet topo name: `ring5s5h`. Select it with
`COMS6200_TOPOLOGY=ring5s5h`, which switches baseline forwarding, the telemetry
gateway, `scripts/testbed.sh` and the fault catalogue. The completed sweep ran
five rounds on this topology. `CATALOGUE_STATUS` in `ring_scenarios.py` is still
`draft`. A healthy session is 5 OF_13 devices, 10 directed links and 38 baseline
flows. `verify_main_openflow.sh` does not check the ring. Live checks for the
selected catalogue are `scripts/verify_faults.py`. See `faults/README.md`.

```
              h1
              |
              s1
            /    \
     h5 - s5      s2 - h2
           |      |
     h4 - s4 ---- s3 - h3
```

The ring is a physical loop and STP is not enabled. This topology **MUST** be
run with the project controller. It is not intended for `ovsbr` standalone
bridge mode.

All hosts are in `10.0.0.0/24` with deterministic MACs `00:00:00:00:00:0N`.
All switches request OpenFlow 1.3 and `failMode=secure`.

### Counts

| Class | Count |
|-------|------:|
| Switches | 5 |
| Hosts | 5 |
| Inter-switch physical links | 5 |
| Host-switch physical links | 5 |
| Total physical links | 10 |

### Port map

Every switch `sN` uses the same convention: port 1 goes to the next switch
clockwise, port 2 to the previous switch, and port 3 to host `hN`.

| Link | Port A | Port B |
|------|--------|--------|
| s1-s2 | s1:1 | s2:2 |
| s2-s3 | s2:1 | s3:2 |
| s3-s4 | s3:1 | s4:2 |
| s4-s5 | s4:1 | s5:2 |
| s5-s1 | s5:1 | s1:2 |
| s1-h1 | s1:3 | h1-eth0 |
| s2-h2 | s2:3 | h2-eth0 |
| s3-h3 | s3:3 | h3-eth0 |
| s4-h4 | s4:3 | h4-eth0 |
| s5-h5 | s5:3 | h5-eth0 |

### DPIDs

| Switch | ONOS device ID |
|--------|----------------|
| s1 | `of:0000000000000101` |
| s2 | `of:0000000000000102` |
| s3 | `of:0000000000000103` |
| s4 | `of:0000000000000104` |
| s5 | `of:0000000000000105` |

These deliberately differ from `main6s8h` (`of:0000000000000001` …
`of:0000000000000006`). ONOS keeps flow rules for a device ID across
disconnects and can re-push them when that ID reconnects. Separate IDs stop
stale `main6s8h` rules from landing on ring switches when both topologies are
used against the same ONOS instance.

### Launch workflow

Only one topology can run at a time, because both use the switch names
`s1`–`s5`. Stop the running one first with `./scripts/testbed.sh stop` (or
exit Mininet and run `sudo mn -c`), using the same `COMS6200_TOPOLOGY` it was
started with.

Session helper (ONOS, background Mininet and the 38 ring baseline flows):

```bash
export COMS6200_TOPOLOGY=ring5s5h
./scripts/testbed.sh start
./scripts/testbed.sh status
./scripts/testbed.sh stop     # also removes the ring baseline flows
```

Keep `COMS6200_TOPOLOGY` exported for every command in the session, including
`telemetry.cli` and the agent server. Root commands need
`sudo --preserve-env=COMS6200_TOPOLOGY,...`, because `sudo` drops it otherwise.

Manual equivalent: start ONOS as in STEP 1 above, then from the repository root:

```bash
sudo mn \
  --custom topologies/ring_topology.py \
  --topo ring5s5h \
  --controller=remote,ip=127.0.0.1,port=6653 \
  --switch=ovsk
```

Inside Mininet:

```
nodes
net
links
```

From another shell, inspect the switches and controller state. Do not use
`verify_main_openflow.sh` here; it checks `main6s8h` bridges s1–s6.

```bash
sudo ovs-vsctl show
sudo ovs-ofctl -O OpenFlow13 show s1
./scripts/verify_onos.sh
```

`pingall` fails until the ring baseline flows are installed. From another
shell:

```bash
export COMS6200_TOPOLOGY=ring5s5h ONOS_USER=onos ONOS_PASSWORD=rocks
python3 forwarding/baseline_forwarding.py install
```

Baseline forwarding leaves the s5–s1 link unused, so traffic follows the chain
s1–s2–s3–s4–s5 (`forwarding/README.md`). ONOS reactive forwarding
(`org.onosproject.fwd`) must stay disabled. Before exiting Mininet, run
`python3 forwarding/baseline_forwarding.py remove` with the same setting.

Runtime verification still to do: ONOS should list five OF_13 devices
`of:0000000000000101` … `of:0000000000000105` and 10 directed links (the five
ring links in both directions), `verify` should pass with 38 flows, and
`pingall` should succeed. Record the result under `evidence/progress/` once
observed.

Static checks (no Mininet required):

```bash
python3 tests/test_ring_static.py
```

### Cleanup after exiting Mininet

```bash
sudo mn -c
```

## Seven-switch/eight-host tree topology

The tree topology is a selectable seven-switch testbed with the same eight
primary hosts and deterministic addressing as the main topology. It is
selected with `COMS6200_TOPOLOGY=tree5s8h` and registered as Mininet topo
`tree5s8h` in `tree_topology.py`.

The selector keeps the original `tree5s8h` name for compatibility with the
existing scripts; the physical topology is now the seven-switch tree below.
It uses OpenFlow 1.3 and secure switch fail mode, and must run against the
project ONOS controller rather than standalone `ovsbr` mode.

```
                              s1
                            /    \
                          s2      s3
                         /  \    /  \
                       s4   s5  s6   s7
                     / |   / |  | \   | \
                    h1 h2 h3 h4 h5 h6 h7 h8
```

| Class | Count |
|-------|------:|
| Switches | 7 |
| Hosts | 8 |
| Inter-switch physical links | 6 |
| Host-switch physical links | 8 |
| Total physical links | 14 |

The physical tree is rooted at s1. Intermediate switches s2 and s3 each have
two leaf switches: s4 carries h1-h2, s5 carries h3-h4, s6 carries h5-h6,
and s7 carries h7-h8. Baseline forwarding uses all six links and installs 76
flows. Tree DPIDs are `0x201`-`0x207`, separate from the main and ring testbeds.
`COMS6200_TOPOLOGY=tree5s8h` selects this topology and its F1–F5 catalogue.
The completed sweep ran five rounds here. The catalogue source status remains
`draft`.

### Port map

Every switch-to-switch link uses port 1 on the child. The root uses ports 1
and 2 for s2 and s3; each intermediate switch uses ports 2 and 3 for its
leaf switches. Host ports are explicit so every host uses `eth0`.

| Link | Port A | Port B |
|------|--------|--------|
| s1-s2 | s1:1 | s2:1 |
| s1-s3 | s1:2 | s3:1 |
| s2-s4 | s2:2 | s4:1 |
| s2-s5 | s2:3 | s5:1 |
| s3-s6 | s3:2 | s6:1 |
| s3-s7 | s3:3 | s7:1 |
| s4-h1 | s4:2 | h1-eth0 |
| s4-h2 | s4:3 | h2-eth0 |
| s5-h3 | s5:2 | h3-eth0 |
| s5-h4 | s5:3 | h4-eth0 |
| s6-h5 | s6:2 | h5-eth0 |
| s6-h6 | s6:3 | h6-eth0 |
| s7-h7 | s7:2 | h7-eth0 |
| s7-h8 | s7:3 | h8-eth0 |

### Switch identities

| Switch | ONOS device ID |
|--------|----------------|
| s1 | `of:0000000000000201` |
| s2 | `of:0000000000000202` |
| s3 | `of:0000000000000203` |
| s4 | `of:0000000000000204` |
| s5 | `of:0000000000000205` |
| s6 | `of:0000000000000206` |
| s7 | `of:0000000000000207` |

The tree's device IDs are deliberately separate from both `main6s8h` and
`ring5s5h`, preventing stale ONOS flow rules from being reused when switching
between testbeds.

### Launch workflow

The normal helper starts ONOS, the background Mininet network, and the
derived baseline forwarding rules:

```bash
export COMS6200_TOPOLOGY=tree5s8h
./scripts/testbed.sh start
./scripts/testbed.sh status
```

Use the same environment setting when injecting or resetting the draft F1-F5
fault catalogue:

```bash
./scripts/testbed.sh inject F1
./scripts/testbed.sh reset
./scripts/testbed.sh stop
```

For a manual Mininet session, start ONOS first and run:

```bash
sudo --preserve-env=COMS6200_TOPOLOGY mn \
  --custom topologies/tree_topology.py \
  --topo tree5s8h \
  --controller=remote,ip=127.0.0.1,port=6653 \
  --switch=ovsk
```

After starting Mininet manually, install and verify the deterministic
forwarding rules from another shell:

```bash
export COMS6200_TOPOLOGY=tree5s8h
python3 forwarding/baseline_forwarding.py install
python3 forwarding/baseline_forwarding.py verify
```

The generic tree derivation installs 56 destination-MAC unicast rules and
the corresponding ARP-tree rules, 76 flows in total (`expected_flow_count()`).
The completed sweep ran this topology for five rounds. `verify_main_openflow.sh`
does not check it.

### Cleanup

Remove baseline rules before disconnecting a manually started network, then
clear Mininet state:

```bash
export COMS6200_TOPOLOGY=tree5s8h
python3 forwarding/baseline_forwarding.py remove
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
