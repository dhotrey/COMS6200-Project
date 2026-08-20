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
