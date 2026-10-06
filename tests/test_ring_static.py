"""Static checks for the ring5s5h topology and its spec.

Does not start Mininet or ONOS. The topology module is executed the way
``mn --custom`` does (no ``__file__``) against a recording stand-in for
``mininet.topo.Topo``, so these checks run without Mininet installed.
"""

from __future__ import annotations

import contextlib
import os
import pathlib
import sys
import tempfile
import types
from typing import Any, Iterator

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from topologies import spec as main_spec  # noqa: E402
from topologies.ring_spec import (  # noqa: E402
    DEVICE_IDS,
    HOST_ATTACHMENTS,
    HOST_IPV4,
    HOST_MACS,
    HOSTS,
    INTER_SWITCH_LINKS,
    PRIMARY_IPV4,
    SWITCH_OPTS,
    SWITCHES,
    peer_of,
    switch_name,
)

TOPO = ROOT / "topologies" / "ring_topology.py"


class _RecordingTopo:
    """Stand-in for mininet.topo.Topo that records build() calls."""

    def __init__(self) -> None:
        self.host_opts: dict[str, dict[str, Any]] = {}
        self.switch_opts: dict[str, dict[str, Any]] = {}
        self.link_ports: list[tuple[str, str, int | None, int | None]] = []
        self.build()

    def build(self) -> None:
        pass

    def addHost(self, name: str, **opts: Any) -> str:
        self.host_opts[name] = opts
        return name

    def addSwitch(self, name: str, **opts: Any) -> str:
        self.switch_opts[name] = opts
        return name

    def addLink(
        self,
        node1: str,
        node2: str,
        port1: int | None = None,
        port2: int | None = None,
        **opts: Any,
    ) -> None:
        self.link_ports.append((node1, node2, port1, port2))


@contextlib.contextmanager
def _mn_custom_context(argv: list[str], cwd: str) -> Iterator[None]:
    saved_modules = {name: sys.modules.get(name) for name in ("mininet", "mininet.topo")}
    saved_argv = sys.argv
    saved_cwd = os.getcwd()
    mininet = types.ModuleType("mininet")
    topo_module = types.ModuleType("mininet.topo")
    topo_module.Topo = _RecordingTopo  # type: ignore[attr-defined]
    mininet.topo = topo_module  # type: ignore[attr-defined]
    sys.modules["mininet"] = mininet
    sys.modules["mininet.topo"] = topo_module
    sys.argv = argv
    os.chdir(cwd)
    try:
        yield
    finally:
        os.chdir(saved_cwd)
        sys.argv = saved_argv
        for name, module in saved_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def _load_topos(argv: list[str], cwd: str) -> dict[str, Any]:
    """Exec ring_topology.py like ``mn --custom`` (no ``__file__``)."""
    namespace: dict[str, Any] = {}
    with _mn_custom_context(argv, cwd):
        exec(compile(TOPO.read_text(encoding="utf-8"), str(TOPO), "exec"), namespace)
    return namespace["topos"]


def test_spec_counts() -> None:
    assert len(SWITCHES) == 5, f"expected 5 switches, got {len(SWITCHES)}"
    assert len(HOSTS) == 5, f"expected 5 hosts, got {len(HOSTS)}"
    assert len(INTER_SWITCH_LINKS) == 5, f"expected 5 ring links, got {len(INTER_SWITCH_LINKS)}"
    assert len(HOST_ATTACHMENTS) == 5, f"expected 5 host links, got {len(HOST_ATTACHMENTS)}"


def test_spec_is_single_ring() -> None:
    neighbours: dict[str, set[str]] = {switch: set() for switch in SWITCHES}
    for link in INTER_SWITCH_LINKS:
        neighbours[link.a].add(link.b)
        neighbours[link.b].add(link.a)
    for switch, peers in neighbours.items():
        assert len(peers) == 2, f"{switch} has neighbours {sorted(peers)}"
    # A single cycle returns to s1 only after visiting every switch.
    previous: str | None = None
    current = "s1"
    visited: list[str] = []
    while current not in visited:
        visited.append(current)
        previous, current = current, next(
            peer for peer in sorted(neighbours[current]) if peer != previous
        )
    assert current == "s1" and len(visited) == len(SWITCHES), f"walk {visited} -> {current}"


def test_no_switch_port_reused() -> None:
    used: set[tuple[str, int]] = set()
    ends = [(link.a, link.a_port) for link in INTER_SWITCH_LINKS]
    ends += [(link.b, link.b_port) for link in INTER_SWITCH_LINKS]
    ends += [(item.switch, item.switch_port) for item in HOST_ATTACHMENTS]
    for end in ends:
        assert end not in used, f"switch port used twice: {end}"
        used.add(end)
    assert len(used) == 15


def test_port_convention() -> None:
    for index, switch in enumerate(SWITCHES):
        clockwise = SWITCHES[(index + 1) % len(SWITCHES)]
        anticlockwise = SWITCHES[index - 1]
        host = HOSTS[index]
        peers = {port: peer_of(switch, port) for port in (1, 2, 3, 4)}
        assert peers[1] == {"kind": "switch", "id": clockwise, "port": 2}, (switch, peers)
        assert peers[2] == {"kind": "switch", "id": anticlockwise, "port": 1}, (switch, peers)
        assert peers[3] == {
            "kind": "host",
            "id": host,
            "intf": f"{host}-eth0",
            "role": "primary",
        }, (switch, peers)
        assert peers[4] is None, (switch, peers)


def test_spec_identities() -> None:
    for index, switch in enumerate(SWITCHES, start=1):
        assert DEVICE_IDS[switch] == f"of:{0x100 + index:016x}", DEVICE_IDS[switch]
        assert switch_name(DEVICE_IDS[switch]) == switch
    shared = set(DEVICE_IDS.values()) & set(main_spec.DEVICE_IDS.values())
    assert not shared, f"ring DPIDs reuse main6s8h DPIDs: {sorted(shared)}"
    for index, host in enumerate(HOSTS, start=1):
        assert HOST_IPV4[host] == f"10.0.0.{index}/24"
        assert PRIMARY_IPV4[host] == f"10.0.0.{index}"
        assert HOST_MACS[host] == f"00:00:00:00:00:{index:02x}"
    assert SWITCH_OPTS == {"protocols": "OpenFlow13", "failMode": "secure"}


def test_topology_builds_from_spec() -> None:
    topos = _load_topos(["mn", "--custom", str(TOPO), "--topo", "ring5s5h"], cwd=str(ROOT))
    assert set(topos) == {"ring5s5h"}, sorted(topos)
    topo = topos["ring5s5h"]()

    assert set(topo.host_opts) == set(HOSTS)
    for host, opts in topo.host_opts.items():
        assert opts == {"ip": HOST_IPV4[host], "mac": HOST_MACS[host]}, (host, opts)

    assert set(topo.switch_opts) == set(SWITCHES)
    for index, switch in enumerate(SWITCHES, start=1):
        expected = {"dpid": f"{0x100 + index:016x}", **SWITCH_OPTS}
        assert topo.switch_opts[switch] == expected, (switch, topo.switch_opts[switch])

    expected_links = {(link.a, link.b, link.a_port, link.b_port) for link in INTER_SWITCH_LINKS}
    expected_links |= {
        (item.switch, item.host, item.switch_port, item.host_port) for item in HOST_ATTACHMENTS
    }
    assert len(topo.link_ports) == 10, f"expected 10 links, got {len(topo.link_ports)}"
    assert set(topo.link_ports) == expected_links


def test_locator_uses_custom_argument() -> None:
    with tempfile.TemporaryDirectory() as elsewhere:
        for argv in (
            ["mn", "--custom", str(TOPO), "--topo", "ring5s5h"],
            ["mn", f"--custom={TOPO}", "--topo", "ring5s5h"],
        ):
            assert "ring5s5h" in _load_topos(argv, cwd=elsewhere), argv
        try:
            _load_topos(["mn", "--topo", "ring5s5h"], cwd=elsewhere)
        except RuntimeError as exc:
            assert "ring_spec.py" in str(exc)
        else:
            raise AssertionError("locator should fail without cwd or --custom path")


def main() -> int:
    checks = (
        test_spec_counts,
        test_spec_is_single_ring,
        test_no_switch_port_reused,
        test_port_convention,
        test_spec_identities,
        test_topology_builds_from_spec,
        test_locator_uses_custom_argument,
    )
    failed = 0
    for check in checks:
        try:
            check()
            print(f"PASS {check.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {check.__name__}: {exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
