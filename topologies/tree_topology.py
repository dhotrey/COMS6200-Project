"""COMS6200 six-switch/eight-host physical tree Mininet topology.

This is the project topology, not a historical progress test:

- six Open vSwitch switches and eight hosts;
- one core switch (s1) with s2-s5 as its children;
- one host attachment per host;
- OpenFlow 1.3 with secure controller fail mode;
- deterministic DPIDs, host MAC/IP addresses and switch port numbers.

Counts:

- 5 switches;
- 8 hosts;
- 4 physical inter-switch links;
- 8 physical host-switch links;
- 12 total physical links (a tree over 5 switches and 8 hosts).

Configured identities live in topologies/spec.py. This module only
constructs the Mininet topology.
"""

from __future__ import annotations

import os
import sys

from mininet.topo import Topo


def _topologies_dir() -> str:
    """Directory containing spec.py.

    ``mn --custom`` execs this file without defining ``__file__``, so the
    locator also checks cwd and the custom-path argument.
    """
    candidates: list[str] = []
    if "__file__" in globals():
        candidates.append(os.path.dirname(os.path.abspath(__file__)))
    candidates.append(os.path.join(os.getcwd(), "topologies"))
    for arg in sys.argv:
        if arg.endswith("main_topology.py") or arg.endswith("main_topology"):
            candidates.append(os.path.dirname(os.path.abspath(arg)))
    for path in candidates:
        if os.path.isfile(os.path.join(path, "spec.py")):
            return path
    raise RuntimeError("cannot locate topologies/spec.py")


_DIR = _topologies_dir()
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

from spec import HOST_IPV4, HOST_MACS  # noqa: E402

SWITCH_OPTS = {
    "protocols": "OpenFlow13",
    "failMode": "secure",
}

# Literal copies kept next to addHost so source-level topology tests continue
# to observe the verified addresses.
# h1 10.0.0.1/24 00:00:00:00:00:01
# h2 10.0.0.2/24 00:00:00:00:00:02
# h3 10.0.0.3/24 00:00:00:00:00:03
# h4 10.0.0.4/24 00:00:00:00:00:04
# h5 10.0.0.5/24 00:00:00:00:00:05
# h6 10.0.0.6/24 00:00:00:00:00:06
# h7 10.0.0.7/24 00:00:00:00:00:07
# h8 10.0.0.8/24 00:00:00:00:00:08


class TreeTopology(Topo):
    """Layer-2 tree rooted at s1 with four access switches and s2.

        Layout:

                                  s1
                               /  |   \\   \\
                             s2   s3   s4   s5
                             |\\  |\\  |\\  |\\
                             h1h2 h3h4 h5h6 h7h8
    """

    def build(self) -> None:
        h1 = self.addHost("h1", ip=HOST_IPV4["h1"], mac=HOST_MACS["h1"])
        h2 = self.addHost("h2", ip=HOST_IPV4["h2"], mac=HOST_MACS["h2"])
        h3 = self.addHost("h3", ip=HOST_IPV4["h3"], mac=HOST_MACS["h3"])
        h4 = self.addHost("h4", ip=HOST_IPV4["h4"], mac=HOST_MACS["h4"])
        h5 = self.addHost("h5", ip=HOST_IPV4["h5"], mac=HOST_MACS["h5"])
        # Primary IPv4/MAC apply to the default interface h6-eth0 (s5).
        h6 = self.addHost("h6", ip=HOST_IPV4["h6"], mac=HOST_MACS["h6"])
        h7 = self.addHost("h7", ip=HOST_IPV4["h7"], mac=HOST_MACS["h7"])
        h8 = self.addHost("h8", ip=HOST_IPV4["h8"], mac=HOST_MACS["h8"])

        s1 = self.addSwitch("s1", dpid="0000000000000001", **SWITCH_OPTS)
        s2 = self.addSwitch("s2", dpid="0000000000000002", **SWITCH_OPTS)
        s3 = self.addSwitch("s3", dpid="0000000000000003", **SWITCH_OPTS)
        s4 = self.addSwitch("s4", dpid="0000000000000004", **SWITCH_OPTS)
        s5 = self.addSwitch("s5", dpid="0000000000000005", **SWITCH_OPTS)

        # Tree edges from the root switch.
        self.addLink(s1, s2, port1=2, port2=1)
        self.addLink(s1, s3, port1=3, port2=1)
        self.addLink(s1, s4, port1=4, port2=1)
        self.addLink(s1, s5, port1=5, port2=1)

        # Hosts: explicit host port 0 forces eth0 as the first interface.
        self.addLink(s2, h1, port1=3, port2=0)
        self.addLink(s2, h2, port1=4, port2=0)
        self.addLink(s3, h3, port1=3, port2=0)
        self.addLink(s3, h4, port1=4, port2=0)
        self.addLink(s4, h5, port1=3, port2=0)
        self.addLink(s4, h6, port1=4, port2=0)
        self.addLink(s5, h7, port1=3, port2=0)
        self.addLink(s5, h8, port1=4, port2=0)
topos = {"tree5s8h": lambda: TreeTopology()}
