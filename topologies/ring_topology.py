"""Five-switch/five-host ring Mininet topology.

- five Open vSwitch switches in a single physical ring s1-s2-s3-s4-s5-s1;
- one host per switch (hN on sN port 3);
- OpenFlow 1.3 with secure controller fail mode;
- deterministic DPIDs, host MAC/IP addresses and switch port numbers.

Counts:

- 5 switches;
- 5 hosts;
- 5 physical inter-switch links;
- 5 physical host-switch links;
- 10 total physical links.

The ring is a physical loop and STP is not enabled, so it must run with the
project controller. Baseline forwarding, telemetry and faults do not support
this topology yet.

Configured identities and the port map live in topologies/ring_spec.py. This
module only constructs the Mininet topology from them.
"""

from __future__ import annotations

import os
import sys

from mininet.topo import Topo


def _topologies_dir() -> str:
    """Directory containing ring_spec.py.

    ``mn --custom`` execs this file without defining ``__file__``, so the
    locator also checks cwd and the custom-path argument.
    """
    candidates: list[str] = []
    if "__file__" in globals():
        candidates.append(os.path.dirname(os.path.abspath(__file__)))
    candidates.append(os.path.join(os.getcwd(), "topologies"))
    for arg in sys.argv:
        path = arg.split("=", 1)[-1]  # accept --custom=<path>
        if path.endswith("ring_topology.py") or path.endswith("ring_topology"):
            candidates.append(os.path.dirname(os.path.abspath(path)))
    for path in candidates:
        if os.path.isfile(os.path.join(path, "ring_spec.py")):
            return path
    raise RuntimeError("cannot locate topologies/ring_spec.py")


# Import ring_spec as topologies.ring_spec so it shares record types with
# topologies.spec instead of loading a second copy.
_ROOT = os.path.dirname(_topologies_dir())
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from topologies.ring_spec import (  # noqa: E402
    DEVICE_IDS,
    HOST_ATTACHMENTS,
    HOST_IPV4,
    HOST_MACS,
    HOSTS,
    INTER_SWITCH_LINKS,
    SWITCH_OPTS,
    SWITCHES,
)


class RingTopology(Topo):
    """Five switches in one physical ring, one host per switch.

                  h1
                  |
                  s1
                /    \\
         h5 - s5      s2 - h2
               |      |
         h4 - s4 ---- s3 - h3
    """

    def build(self) -> None:
        for host in HOSTS:
            self.addHost(host, ip=HOST_IPV4[host], mac=HOST_MACS[host])

        for switch in SWITCHES:
            self.addSwitch(switch, dpid=DEVICE_IDS[switch].removeprefix("of:"), **SWITCH_OPTS)

        for link in INTER_SWITCH_LINKS:
            self.addLink(link.a, link.b, port1=link.a_port, port2=link.b_port)

        # Explicit host port 0 forces hN-eth0.
        for attachment in HOST_ATTACHMENTS:
            self.addLink(
                attachment.switch,
                attachment.host,
                port1=attachment.switch_port,
                port2=attachment.host_port,
            )


topos = {"ring5s5h": lambda: RingTopology()}
