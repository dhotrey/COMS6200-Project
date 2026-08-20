# Topologies

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

Runtime results for this repository-backed TCLink test must be collected on
the Mininet server. Creating the topology file does not mean the bandwidth
test has already been run.

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

This topology is for later reproduction of delay and packet-loss evidence.
Fresh runtime results for `progressimpaired` must also be collected on the
Mininet server; they have not been recorded yet.
