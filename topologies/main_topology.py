"""Final COMS6200 six-switch/eight-host physical Mininet topology.

This is the project topology, not a historical progress test:

- six Open vSwitch switches and eight hosts;
- dual-core redundant physical connectivity (s1/s2);
- one access-edge test link (s3-s4);
- one optional secondary host attachment (h6-s6);
- OpenFlow 1.3 with secure controller fail mode;
- deterministic DPIDs, host MAC/IP addresses and switch port numbers.

Counts:

- 6 switches;
- 8 hosts;
- 10 physical inter-switch links;
- 9 physical host-switch links;
- 19 total physical links.

Redundant physical paths exist so later fault and failover experiments can
use alternate uplinks. Normal forwarding will be installed later as a
deterministic loop-free active tree through s1. The following links remain
physically present but are reserved for controlled experiments and are not
part of baseline forwarding:

- s2 redundant access uplinks;
- s1-s2 inter-core link;
- s3-s4 access-edge test link;
- h6-s6 secondary host attachment.

h6 remains primarily attached to s5 (h6-eth0, 10.0.0.6/24). The secondary
interface h6-eth1 attaches to s6 without a baseline IPv4 address. No Linux
bonding, LACP, MLAG, VRRP or automatic host failover is implemented.

This module contains topology construction only. It does not implement
controller logic, telemetry, fault injection or LLM integration.
"""

from mininet.topo import Topo

SWITCH_OPTS = {
    "protocols": "OpenFlow13",
    "failMode": "secure",
}


class MainProjectTopology(Topo):
    """Dual-core Layer-2 fabric with four dual-homed access switches.

    Layout (physical, not the baseline forwarding tree):

                    s1 -------- s2
                   /|\\          /|\\
                  / | \\        / | \\
                 /  |  \\      /  |  \\
               s3---s4   s5   s6
               |\\   |\\   |\\   |\\
               h1h2 h3h4 h5   h7h8
                          \\   /
                           h6
    """

    def build(self) -> None:
        h1 = self.addHost("h1", ip="10.0.0.1/24", mac="00:00:00:00:00:01")
        h2 = self.addHost("h2", ip="10.0.0.2/24", mac="00:00:00:00:00:02")
        h3 = self.addHost("h3", ip="10.0.0.3/24", mac="00:00:00:00:00:03")
        h4 = self.addHost("h4", ip="10.0.0.4/24", mac="00:00:00:00:00:04")
        h5 = self.addHost("h5", ip="10.0.0.5/24", mac="00:00:00:00:00:05")
        # Primary IPv4/MAC apply to the default interface h6-eth0 (s5).
        h6 = self.addHost("h6", ip="10.0.0.6/24", mac="00:00:00:00:00:06")
        h7 = self.addHost("h7", ip="10.0.0.7/24", mac="00:00:00:00:00:07")
        h8 = self.addHost("h8", ip="10.0.0.8/24", mac="00:00:00:00:00:08")

        s1 = self.addSwitch("s1", dpid="0000000000000001", **SWITCH_OPTS)
        s2 = self.addSwitch("s2", dpid="0000000000000002", **SWITCH_OPTS)
        s3 = self.addSwitch("s3", dpid="0000000000000003", **SWITCH_OPTS)
        s4 = self.addSwitch("s4", dpid="0000000000000004", **SWITCH_OPTS)
        s5 = self.addSwitch("s5", dpid="0000000000000005", **SWITCH_OPTS)
        s6 = self.addSwitch("s6", dpid="0000000000000006", **SWITCH_OPTS)

        # Core
        self.addLink(s1, s2, port1=1, port2=1)

        # Active-core access uplinks (s1)
        self.addLink(s1, s3, port1=2, port2=1)
        self.addLink(s1, s4, port1=3, port2=1)
        self.addLink(s1, s5, port1=4, port2=1)
        self.addLink(s1, s6, port1=5, port2=1)

        # Redundant-core access uplinks (s2)
        self.addLink(s2, s3, port1=2, port2=2)
        self.addLink(s2, s4, port1=3, port2=2)
        self.addLink(s2, s5, port1=4, port2=2)
        self.addLink(s2, s6, port1=5, port2=2)

        # Access-edge test link (controlled loop / core-bypass experiments)
        self.addLink(s3, s4, port1=5, port2=5)

        # Hosts: explicit host port 0 forces eth0 as the first interface.
        self.addLink(s3, h1, port1=3, port2=0)
        self.addLink(s3, h2, port1=4, port2=0)
        self.addLink(s4, h3, port1=3, port2=0)
        self.addLink(s4, h4, port1=4, port2=0)
        self.addLink(s5, h5, port1=3, port2=0)
        self.addLink(s5, h6, port1=4, port2=0, intfName2="h6-eth0")
        self.addLink(s6, h7, port1=3, port2=0)
        self.addLink(s6, h8, port1=4, port2=0)
        # Optional secondary h6 attachment. No baseline IPv4: Mininet applies
        # the host IP only to the default interface (h6-eth0).
        self.addLink(
            s6,
            h6,
            port1=5,
            port2=1,
            intfName2="h6-eth1",
            addr2="00:00:00:00:06:02",
        )


topos = {"main6s8h": lambda: MainProjectTopology()}
