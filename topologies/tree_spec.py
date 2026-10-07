"""Canonical identities and attachments for the tree7s8h topology."""

from __future__ import annotations

from topologies.spec import HostAttachment, InterSwitchLink

SWITCH_OPTS: dict[str, str] = {"protocols": "OpenFlow13", "failMode": "secure"}
SWITCHES: tuple[str, ...] = ("s1", "s2", "s3", "s4", "s5", "s6", "s7")
HOSTS: tuple[str, ...] = ("h1", "h2", "h3", "h4", "h5", "h6", "h7", "h8")

# Keep tree device IDs separate from the main and ring testbeds.
DEVICE_IDS: dict[str, str] = {
    switch: f"of:{0x200 + index:016x}" for index, switch in enumerate(SWITCHES, start=1)
}
SWITCH_NAMES: dict[str, str] = {device_id: name for name, device_id in DEVICE_IDS.items()}

HOST_IPV4: dict[str, str] = {
    host: f"10.0.0.{index}/24" for index, host in enumerate(HOSTS, start=1)
}
HOST_MACS: dict[str, str] = {
    host: f"00:00:00:00:00:{index:02x}" for index, host in enumerate(HOSTS, start=1)
}
PRIMARY_IPV4: dict[str, str] = {
    host: address.split("/", 1)[0] for host, address in HOST_IPV4.items()
}

INTER_SWITCH_LINKS: tuple[InterSwitchLink, ...] = (
    InterSwitchLink("s1", 1, "s2", 1),
    InterSwitchLink("s1", 2, "s3", 1),
    InterSwitchLink("s2", 2, "s4", 1),
    InterSwitchLink("s2", 3, "s5", 1),
    InterSwitchLink("s3", 2, "s6", 1),
    InterSwitchLink("s3", 3, "s7", 1),
)
HOST_ATTACHMENTS: tuple[HostAttachment, ...] = (
    HostAttachment("h1", "s4", 2, 0, "h1-eth0", HOST_MACS["h1"], HOST_IPV4["h1"], "primary"),
    HostAttachment("h2", "s4", 3, 0, "h2-eth0", HOST_MACS["h2"], HOST_IPV4["h2"], "primary"),
    HostAttachment("h3", "s5", 2, 0, "h3-eth0", HOST_MACS["h3"], HOST_IPV4["h3"], "primary"),
    HostAttachment("h4", "s5", 3, 0, "h4-eth0", HOST_MACS["h4"], HOST_IPV4["h4"], "primary"),
    HostAttachment("h5", "s6", 2, 0, "h5-eth0", HOST_MACS["h5"], HOST_IPV4["h5"], "primary"),
    HostAttachment("h6", "s6", 3, 0, "h6-eth0", HOST_MACS["h6"], HOST_IPV4["h6"], "primary"),
    HostAttachment("h7", "s7", 2, 0, "h7-eth0", HOST_MACS["h7"], HOST_IPV4["h7"], "primary"),
    HostAttachment("h8", "s7", 3, 0, "h8-eth0", HOST_MACS["h8"], HOST_IPV4["h8"], "primary"),
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
            return {"kind": "host", "id": attachment.host, "intf": attachment.host_intf, "role": attachment.role}
    return None