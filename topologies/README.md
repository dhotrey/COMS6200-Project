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
