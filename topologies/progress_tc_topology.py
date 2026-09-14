"""TCLink progress topologies for early COMS6200 bandwidth, delay and loss tests.

These topologies reproduce the simple h1--s1--h2 Mininet experiments used as
Section 7 progress evidence. They are NOT the final six-switch/eight-host
project topology. They contain no controller-specific logic, OpenFlow
configuration, ACL rules, fault injection or LLM integration.

Launch with Mininet ``--link tc`` so the bw/delay/loss parameters take effect.
Runtime results must be collected on a Mininet server; creating these files
does not mean the repository-backed tests have already been run.
"""

from mininet.topo import Topo


class ProgressBandwidthTopology(Topo):
    """h1--s1--h2 with a 10 Mbit/s TCLink on h1-s1 only.

    h1 ---- s1 ---- h2
    """

    def build(self) -> None:
        h1 = self.addHost("h1")
        h2 = self.addHost("h2")
        s1 = self.addSwitch("s1")

        self.addLink(h1, s1, bw=10)
        self.addLink(s1, h2)


class ProgressImpairedTopology(Topo):
    """h1--s1--h2 with 1 Mbit/s, 5 ms delay and 10% loss on h1-s1.

    h1 ---- s1 ---- h2
    """

    def build(self) -> None:
        h1 = self.addHost("h1")
        h2 = self.addHost("h2")
        s1 = self.addSwitch("s1")

        self.addLink(h1, s1, bw=1, delay="5ms", loss=10)
        self.addLink(s1, h2)


topos = {
    "progressbw10": lambda: ProgressBandwidthTopology(),
    "progressimpaired": lambda: ProgressImpairedTopology(),
}
