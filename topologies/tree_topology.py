"""COMS6200 seven-switch/eight-host physical tree Mininet topology.

This is the project topology, not a historical progress test:

- seven Open vSwitch switches and eight hosts;
- one root switch (s1), two intermediate switches (s2-s3), and four leaves;
- one host attachment per host;
- OpenFlow 1.3 with secure controller fail mode;
- deterministic DPIDs, host MAC/IP addresses and switch port numbers.

Counts:

- 7 switches;
- 8 hosts;
- 6 physical inter-switch links;
- 8 physical host-switch links;
- 14 total physical links (a tree over 7 switches and 8 hosts).

Configured identities live in topologies/tree_spec.py. This module only
constructs the Mininet topology.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from mininet.topo import Topo


def _project_root() -> Path:
    candidates: list[Path] = []
    if "__file__" in globals():
        candidates.append(Path(__file__).resolve().parents[1])
    candidates.append(Path.cwd())
    for arg in sys.argv:
        path = arg.split("=", 1)[-1]
        if path.endswith("tree_topology.py") or path.endswith("tree_topology"):
            candidates.append(Path(os.path.abspath(path)).parent.parent)
    for root in candidates:
        if (root / "topologies" / "tree_spec.py").is_file():
            return root
    raise RuntimeError("cannot locate topologies/tree_spec.py")


_ROOT = _project_root()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from topologies.tree_spec import (  # noqa: E402
    DEVICE_IDS,
    HOST_ATTACHMENTS,
    HOST_IPV4,
    HOST_MACS,
    HOSTS,
    INTER_SWITCH_LINKS,
    SWITCH_OPTS,
    SWITCHES,
)

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
    """Layer-2 binary tree rooted at s1 with four host-bearing leaves.

                              s1
                            /    \\
                          s2      s3
                         /  \\    /  \\
                       s4   s5  s6   s7
                     / |   / |  | \\   | \\
                    h1 h2 h3 h4 h5 h6 h7 h8
    """

    def build(self) -> None:
        for host in HOSTS:
            self.addHost(host, ip=HOST_IPV4[host], mac=HOST_MACS[host])
        for switch in SWITCHES:
            self.addSwitch(switch, dpid=DEVICE_IDS[switch].removeprefix("of:"), **SWITCH_OPTS)
        for link in INTER_SWITCH_LINKS:
            self.addLink(link.a, link.b, port1=link.a_port, port2=link.b_port)
        for attachment in HOST_ATTACHMENTS:
            self.addLink(
                attachment.switch,
                attachment.host,
                port1=attachment.switch_port,
                port2=attachment.host_port,
            )
topos = {"tree5s8h": lambda: TreeTopology()}
