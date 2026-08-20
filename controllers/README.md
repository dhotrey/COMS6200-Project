# Controllers

## Main OpenFlow 1.3 controller

File: `main_controller.py`

This is a deterministic baseline forwarding application for
`topologies/main_topology.py`. It is not a learning switch.

- OpenFlow 1.3 only
- active core: s1
- redundant core s2 stays connected but is not used for ordinary host forwarding
- destination-MAC unicast flows, cookie `0x1000`, priority 100
- loop-free ARP PacketOut on the active tree only

Do not run this topology in standalone `ovsbr` mode.

See `topologies/README.md` for the two-terminal launch procedure.
