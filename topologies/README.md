# Topologies

## Final six-switch/eight-host project topology

This is the actual COMS6200 physical topology. It is not a progress-capability
test.

File: `main_topology.py`

Registered Mininet topo name: `main6s8h`

Controller: `controllers/main_controller.py`

This topology contains redundant physical links and **MUST** be run with the
project controller. It is not intended for `ovsbr` standalone bridge mode.

```
                    s1 -------- s2
                   /|\\          /|\\
                  / | \\        / | \\
                 /  |  \\      /  |  \\
               s3   s4   s5   s6
               |\\   |\\   |\\   |\\
               h1   h3   h5   h7
               h2   h4   h6   h8
```

Roles:

- s1 = Core A (initial active core)
- s2 = Core B (physically present; excluded from baseline host forwarding)
- s3 = User Access A (h1, h2)
- s4 = User Access B (h3, h4)
- s5 = Server Access (h5, h6)
- s6 = Admin/Test Access (h7, h8)

All hosts are in `10.0.0.0/24` with deterministic MACs `00:00:00:00:00:0N`.
All switches request OpenFlow 1.3 and `failMode=secure`. STP is not enabled.

### Port map

| Link | Port A | Port B |
|------|--------|--------|
| s1-s2 | s1:1 | s2:1 |
| s1-s3 | s1:2 | s3:1 |
| s1-s4 | s1:3 | s4:1 |
| s1-s5 | s1:4 | s5:1 |
| s1-s6 | s1:5 | s6:1 |
| s2-s3 | s2:2 | s3:2 |
| s2-s4 | s2:3 | s4:2 |
| s2-s5 | s2:4 | s5:2 |
| s2-s6 | s2:5 | s6:2 |
| s3-h1 | s3:3 | h1 |
| s3-h2 | s3:4 | h2 |
| s4-h3 | s4:3 | h3 |
| s4-h4 | s4:4 | h4 |
| s5-h5 | s5:3 | h5 |
| s5-h6 | s5:4 | h6 |
| s6-h7 | s6:3 | h7 |
| s6-h8 | s6:4 | h8 |

Total: 6 switches, 8 hosts, 17 links.

### Launch workflow

The controller is **ONOS 2.7.0**, running in a Docker container. It was verified
against this topology on the team server on 20 August 2026. See
`docs/setup/onos-setup.md` for installation and verification, and
`docs/decisions/onos-controller-decision.md` for why ONOS replaced the earlier
Ryu plan.

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

Verified against ONOS on 20 August 2026: all six switches connected over
OpenFlow 1.3, and ONOS discovered 6 devices (`of:0000000000000001` through
`of:0000000000000006`) and the 9 physical switch-switch links, reported as 18
directed links.

### Cleanup after exiting Mininet

```bash
sudo mn -c
```

## Custom progress topology

This topology reproduces the early five-switch/two-host Mininet progress
evidence and is **not** the final six-switch/eight-host Ryu/OpenFlow topology.

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

This starts the Mininet CLI. It does not start Ryu or configure OpenFlow 1.3.

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
