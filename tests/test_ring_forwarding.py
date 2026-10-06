"""Static checks for derived baseline forwarding and the ring5s5h plan.

Does not contact ONOS or Mininet. Packet walks over the configured port map
stand in for pingall: every unicast pair must arrive, and every ARP broadcast
must reach each other host exactly once without revisiting a switch.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "forwarding"))
sys.path.insert(0, str(ROOT))

# These checks compare against the verified main6s8h literals, so pin the
# selector regardless of the caller's shell.
os.environ["COMS6200_TOPOLOGY"] = "main6s8h"

import baseline_forwarding as bf  # noqa: E402
from topologies import ring_spec  # noqa: E402
from topologies import spec as main_spec  # noqa: E402
from topologies.spec import InterSwitchLink  # noqa: E402

# Links main6s8h baseline forwarding leaves unused (topologies/README.md).
MAIN_RESERVED_LINKS = (
    InterSwitchLink("s1", 1, "s2", 1),
    InterSwitchLink("s2", 2, "s3", 2),
    InterSwitchLink("s2", 3, "s4", 2),
    InterSwitchLink("s2", 4, "s5", 2),
    InterSwitchLink("s2", 5, "s6", 2),
    InterSwitchLink("s3", 5, "s4", 5),
)

RING_UNICAST = {
    "s1": {"h1": 3, "h2": 1, "h3": 1, "h4": 1, "h5": 1},
    "s2": {"h1": 2, "h2": 3, "h3": 1, "h4": 1, "h5": 1},
    "s3": {"h1": 2, "h2": 2, "h3": 3, "h4": 1, "h5": 1},
    "s4": {"h1": 2, "h2": 2, "h3": 2, "h4": 3, "h5": 1},
    "s5": {"h1": 2, "h2": 2, "h3": 2, "h4": 2, "h5": 3},
}
RING_ARP = {"s1": (1, 3), "s2": (1, 2, 3), "s3": (1, 2, 3), "s4": (1, 2, 3), "s5": (2, 3)}
RING_RESERVED = {
    "s1": frozenset({2}),
    "s2": frozenset(),
    "s3": frozenset(),
    "s4": frozenset(),
    "s5": frozenset({1}),
}


def _ring_plan() -> tuple[dict[str, dict[str, int]], dict[str, tuple[int, ...]], dict[str, frozenset[int]]]:
    return bf.tree_forwarding(
        ring_spec.SWITCHES,
        ring_spec.INTER_SWITCH_LINKS,
        ring_spec.HOST_ATTACHMENTS,
        bf.RING_RESERVED_LINKS,
    )


def _walk_unicast(spec: ModuleType, unicast: dict[str, dict[str, int]]) -> None:
    primary = [item for item in spec.HOST_ATTACHMENTS if item.role == "primary"]
    for src in primary:
        for dst in primary:
            if src.host == dst.host:
                continue
            switch = src.switch
            for _hop in range(len(spec.SWITCHES)):
                peer = spec.peer_of(switch, unicast[switch][dst.host])
                assert peer is not None, (src.host, dst.host, switch)
                if peer["kind"] == "host":
                    assert peer["id"] == dst.host, f"{src.host}->{dst.host} delivered to {peer['id']}"
                    break
                switch = str(peer["id"])
            else:
                raise AssertionError(f"{src.host}->{dst.host} did not arrive (loop?)")


def _walk_arp(spec: ModuleType, arp_ports: dict[str, tuple[int, ...]]) -> None:
    primary = [item for item in spec.HOST_ATTACHMENTS if item.role == "primary"]
    for src in primary:
        received: list[str] = []
        visited: set[str] = set()
        pending = [(src.switch, src.switch_port)]
        while pending:
            switch, in_port = pending.pop()
            assert switch not in visited, f"ARP from {src.host} revisits {switch}"
            visited.add(switch)
            for port in arp_ports[switch]:
                if port == in_port:
                    continue
                peer = spec.peer_of(switch, port)
                assert peer is not None, (switch, port)
                if peer["kind"] == "host":
                    received.append(str(peer["id"]))
                else:
                    pending.append((str(peer["id"]), int(peer["port"])))
        expected = sorted(item.host for item in primary if item.host != src.host)
        assert sorted(received) == expected, f"ARP from {src.host} reached {sorted(received)}"


def test_derivation_reproduces_verified_main6s8h_tables() -> None:
    derived = bf.tree_forwarding(
        main_spec.SWITCHES,
        main_spec.INTER_SWITCH_LINKS,
        main_spec.HOST_ATTACHMENTS,
        MAIN_RESERVED_LINKS,
    )
    assert derived[0] == bf.UNICAST_EGRESS, derived[0]
    assert derived[1] == bf.ARP_ACTIVE_PORTS, derived[1]
    assert derived[2] == bf.RESERVED_PORTS, derived[2]


def test_ring_tables() -> None:
    unicast, arp_ports, reserved = _ring_plan()
    assert unicast == RING_UNICAST, unicast
    assert arp_ports == RING_ARP, arp_ports
    assert reserved == RING_RESERVED, reserved
    for switch, ports in arp_ports.items():
        assert set(ports).isdisjoint(reserved[switch]), switch
    for switch, egress in unicast.items():
        assert set(egress.values()).isdisjoint(reserved[switch]), switch


def test_packet_walks_main6s8h() -> None:
    _walk_unicast(main_spec, bf.UNICAST_EGRESS)
    _walk_arp(main_spec, bf.ARP_ACTIVE_PORTS)


def test_packet_walks_ring5s5h() -> None:
    unicast, arp_ports, _reserved = _ring_plan()
    _walk_unicast(ring_spec, unicast)
    _walk_arp(ring_spec, arp_ports)


def test_tree_forwarding_rejects_bad_plans() -> None:
    cases = (
        ((), "loop"),
        ((InterSwitchLink("s1", 4, "s3", 2),), "not configured"),
        (
            (InterSwitchLink("s1", 1, "s2", 2), InterSwitchLink("s3", 1, "s4", 2)),
            "not on the active tree",
        ),
    )
    for reserved, message in cases:
        try:
            bf.tree_forwarding(
                ring_spec.SWITCHES,
                ring_spec.INTER_SWITCH_LINKS,
                ring_spec.HOST_ATTACHMENTS,
                reserved,
            )
        except ValueError as exc:
            assert message in str(exc), (reserved, str(exc))
        else:
            raise AssertionError(f"reserved={reserved} should be rejected")


def test_selector_switches_provisioner_to_ring() -> None:
    code = (
        "import json, sys; sys.path.insert(0, 'forwarding')\n"
        "import baseline_forwarding as bf\n"
        "specs = bf.expected_flow_specs()\n"
        "print(json.dumps({\n"
        "  'count': len(specs),\n"
        "  'by_switch': bf.expected_count_by_switch(),\n"
        "  'devices': sorted({s.device_id for s in specs}),\n"
        "  'reserved_outputs': [s.switch for s in specs if set(s.outputs) & bf.RESERVED_PORTS[s.switch]],\n"
        "  'macs': bf.HOST_MACS,\n"
        "}))\n"
    )
    env = dict(os.environ, COMS6200_TOPOLOGY="ring5s5h")
    completed = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["count"] == 38, result
    assert result["by_switch"] == {"s1": 7, "s2": 8, "s3": 8, "s4": 8, "s5": 7}, result
    assert result["devices"] == sorted(ring_spec.DEVICE_IDS.values()), result
    assert result["reserved_outputs"] == [], result
    assert result["macs"] == ring_spec.HOST_MACS, result


def main() -> int:
    checks = (
        test_derivation_reproduces_verified_main6s8h_tables,
        test_ring_tables,
        test_packet_walks_main6s8h,
        test_packet_walks_ring5s5h,
        test_tree_forwarding_rejects_bad_plans,
        test_selector_switches_provisioner_to_ring,
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
