"""Canonical main6s8h identities and attachments.

This module is the shared source of configured topology facts for Mininet
construction and the M4 telemetry gateway. Observed ONOS device/link/port
state is never stored here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

SWITCHES: tuple[str, ...] = ("s1", "s2", "s3", "s4", "s5", "s6")
HOSTS: tuple[str, ...] = ("h1", "h2", "h3", "h4", "h5", "h6", "h7", "h8")

DEVICE_IDS: dict[str, str] = {
    "s1": "of:0000000000000001",
    "s2": "of:0000000000000002",
    "s3": "of:0000000000000003",
    "s4": "of:0000000000000004",
    "s5": "of:0000000000000005",
    "s6": "of:0000000000000006",
}

SWITCH_NAMES: dict[str, str] = {device_id: name for name, device_id in DEVICE_IDS.items()}

SWITCH_OPTS: dict[str, str] = {
    "protocols": "OpenFlow13",
    "failMode": "secure",
}

HOST_IPV4: dict[str, str] = {
    "h1": "10.0.0.1/24",
    "h2": "10.0.0.2/24",
    "h3": "10.0.0.3/24",
    "h4": "10.0.0.4/24",
    "h5": "10.0.0.5/24",
    "h6": "10.0.0.6/24",
    "h7": "10.0.0.7/24",
    "h8": "10.0.0.8/24",
}

HOST_MACS: dict[str, str] = {
    "h1": "00:00:00:00:00:01",
    "h2": "00:00:00:00:00:02",
    "h3": "00:00:00:00:00:03",
    "h4": "00:00:00:00:00:04",
    "h5": "00:00:00:00:00:05",
    "h6": "00:00:00:00:00:06",
    "h7": "00:00:00:00:00:07",
    "h8": "00:00:00:00:00:08",
}

H6_SECONDARY_MAC = "00:00:00:00:06:02"

PRIMARY_IPV4: dict[str, str] = {
    name: address.split("/", 1)[0] for name, address in HOST_IPV4.items()
}


@dataclass(frozen=True)
class InterSwitchLink:
    a: str
    a_port: int
    b: str
    b_port: int


@dataclass(frozen=True)
class HostAttachment:
    host: str
    switch: str
    switch_port: int
    host_port: int
    host_intf: str
    mac: str
    ipv4: str | None
    role: str


# Order matches topologies/main_topology.py addLink sequence.
INTER_SWITCH_LINKS: tuple[InterSwitchLink, ...] = (
    InterSwitchLink("s1", 1, "s2", 1),
    InterSwitchLink("s1", 2, "s3", 1),
    InterSwitchLink("s1", 3, "s4", 1),
    InterSwitchLink("s1", 4, "s5", 1),
    InterSwitchLink("s1", 5, "s6", 1),
    InterSwitchLink("s2", 2, "s3", 2),
    InterSwitchLink("s2", 3, "s4", 2),
    InterSwitchLink("s2", 4, "s5", 2),
    InterSwitchLink("s2", 5, "s6", 2),
    InterSwitchLink("s3", 5, "s4", 5),
)

HOST_ATTACHMENTS: tuple[HostAttachment, ...] = (
    HostAttachment("h1", "s3", 3, 0, "h1-eth0", HOST_MACS["h1"], HOST_IPV4["h1"], "primary"),
    HostAttachment("h2", "s3", 4, 0, "h2-eth0", HOST_MACS["h2"], HOST_IPV4["h2"], "primary"),
    HostAttachment("h3", "s4", 3, 0, "h3-eth0", HOST_MACS["h3"], HOST_IPV4["h3"], "primary"),
    HostAttachment("h4", "s4", 4, 0, "h4-eth0", HOST_MACS["h4"], HOST_IPV4["h4"], "primary"),
    HostAttachment("h5", "s5", 3, 0, "h5-eth0", HOST_MACS["h5"], HOST_IPV4["h5"], "primary"),
    HostAttachment("h6", "s5", 4, 0, "h6-eth0", HOST_MACS["h6"], HOST_IPV4["h6"], "primary"),
    HostAttachment("h7", "s6", 3, 0, "h7-eth0", HOST_MACS["h7"], HOST_IPV4["h7"], "primary"),
    HostAttachment("h8", "s6", 4, 0, "h8-eth0", HOST_MACS["h8"], HOST_IPV4["h8"], "primary"),
    HostAttachment("h6", "s6", 5, 1, "h6-eth1", H6_SECONDARY_MAC, None, "secondary"),
)


def dpid(switch: str) -> str:
    return DEVICE_IDS[switch]


def switch_name(device_id: str) -> str | None:
    return SWITCH_NAMES.get(device_id)


def peer_of(switch: str, port: int) -> dict[str, str | int] | None:
    for link in INTER_SWITCH_LINKS:
        if link.a == switch and link.a_port == port:
            return {"kind": "switch", "id": link.b, "port": link.b_port}
        if link.b == switch and link.b_port == port:
            return {"kind": "switch", "id": link.a, "port": link.a_port}
    for attachment in HOST_ATTACHMENTS:
        if attachment.switch == switch and attachment.switch_port == port:
            return {
                "kind": "host",
                "id": attachment.host,
                "intf": attachment.host_intf,
                "role": attachment.role,
            }
    return None


def iter_port_peers() -> Iterator[tuple[str, int, dict[str, str | int]]]:
    for switch in SWITCHES:
        seen: set[int] = set()
        for link in INTER_SWITCH_LINKS:
            if link.a == switch and link.a_port not in seen:
                seen.add(link.a_port)
                peer = peer_of(switch, link.a_port)
                if peer is not None:
                    yield switch, link.a_port, peer
            if link.b == switch and link.b_port not in seen:
                seen.add(link.b_port)
                peer = peer_of(switch, link.b_port)
                if peer is not None:
                    yield switch, link.b_port, peer
        for attachment in HOST_ATTACHMENTS:
            if attachment.switch == switch and attachment.switch_port not in seen:
                seen.add(attachment.switch_port)
                peer = peer_of(switch, attachment.switch_port)
                if peer is not None:
                    yield switch, attachment.switch_port, peer
