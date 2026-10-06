"""Canonical ring5s5h identities and attachments.

Configured topology facts for the five-switch ring, using the same names as
topologies/spec.py (main6s8h) so later consumers can select either spec.
Observed ONOS device/link/port state is never stored here.

Port convention on every switch sN:

- port 1: next switch clockwise (s5 wraps to s1);
- port 2: previous switch;
- port 3: host hN (hN-eth0).
"""

from __future__ import annotations

# Shared with main6s8h: OpenFlow 1.3, secure fail mode, same record types.
from topologies.spec import SWITCH_OPTS, HostAttachment, InterSwitchLink  # noqa: F401

SWITCHES: tuple[str, ...] = ("s1", "s2", "s3", "s4", "s5")
HOSTS: tuple[str, ...] = ("h1", "h2", "h3", "h4", "h5")

# DPIDs 0x101-0x105, not main6s8h's 0x1-0x6. ONOS keeps flow rules for a
# device ID across disconnects and re-pushes them when that ID reconnects, so
# sharing IDs would let stale main6s8h rules land on ring switches.
DEVICE_IDS: dict[str, str] = {
    "s1": "of:0000000000000101",
    "s2": "of:0000000000000102",
    "s3": "of:0000000000000103",
    "s4": "of:0000000000000104",
    "s5": "of:0000000000000105",
}

SWITCH_NAMES: dict[str, str] = {device_id: name for name, device_id in DEVICE_IDS.items()}

HOST_IPV4: dict[str, str] = {
    "h1": "10.0.0.1/24",
    "h2": "10.0.0.2/24",
    "h3": "10.0.0.3/24",
    "h4": "10.0.0.4/24",
    "h5": "10.0.0.5/24",
}

HOST_MACS: dict[str, str] = {
    "h1": "00:00:00:00:00:01",
    "h2": "00:00:00:00:00:02",
    "h3": "00:00:00:00:00:03",
    "h4": "00:00:00:00:00:04",
    "h5": "00:00:00:00:00:05",
}

PRIMARY_IPV4: dict[str, str] = {
    name: address.split("/", 1)[0] for name, address in HOST_IPV4.items()
}

# Clockwise: sN port 1 -> s(N+1) port 2.
INTER_SWITCH_LINKS: tuple[InterSwitchLink, ...] = (
    InterSwitchLink("s1", 1, "s2", 2),
    InterSwitchLink("s2", 1, "s3", 2),
    InterSwitchLink("s3", 1, "s4", 2),
    InterSwitchLink("s4", 1, "s5", 2),
    InterSwitchLink("s5", 1, "s1", 2),
)

HOST_ATTACHMENTS: tuple[HostAttachment, ...] = (
    HostAttachment("h1", "s1", 3, 0, "h1-eth0", HOST_MACS["h1"], HOST_IPV4["h1"], "primary"),
    HostAttachment("h2", "s2", 3, 0, "h2-eth0", HOST_MACS["h2"], HOST_IPV4["h2"], "primary"),
    HostAttachment("h3", "s3", 3, 0, "h3-eth0", HOST_MACS["h3"], HOST_IPV4["h3"], "primary"),
    HostAttachment("h4", "s4", 3, 0, "h4-eth0", HOST_MACS["h4"], HOST_IPV4["h4"], "primary"),
    HostAttachment("h5", "s5", 3, 0, "h5-eth0", HOST_MACS["h5"], HOST_IPV4["h5"], "primary"),
)


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
