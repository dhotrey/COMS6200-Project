"""Five-switch/two-host Mininet topology used as early COMS6200 progress evidence.

This file reproduces the custom Python topology already verified in the lab
with addHost(), addSwitch(), addLink(), net, and h1-h2 ping.

It is NOT the final six-switch/eight-host project topology. It contains no
controller-specific logic, OpenFlow configuration, or traffic-impairment
settings.
"""

from mininet.topo import Topo


class ProgressCustomTopology(Topo):
    """Tree-like five-switch topology with two hosts.

          s1
          |
          s2
        / | \\
      s3  s4  s5
      |       |
      h1      h2
    """

    def build(self) -> None:
        h1 = self.addHost("h1")
        h2 = self.addHost("h2")

        s1 = self.addSwitch("s1")
        s2 = self.addSwitch("s2")
        s3 = self.addSwitch("s3")
        s4 = self.addSwitch("s4")
        s5 = self.addSwitch("s5")

        self.addLink(s1, s2)
        self.addLink(s2, s3)
        self.addLink(s2, s4)
        self.addLink(s2, s5)
        self.addLink(s3, h1)
        self.addLink(s5, h2)


topos = {"progress5s2h": lambda: ProgressCustomTopology()}
