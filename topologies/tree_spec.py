"""Configured identities and attachments for the tree5s8h topology."""

from __future__ import annotations

from .spec import HOSTS, HOST_IPV4, HOST_MACS, HostAttachment, InterSwitchLink

SWITCHES: tuple[str, ...] = ("s1", "s2", "s3", "s4", "s5")

DEVICE_IDS: dict[str, str] = {
    switch: f"of:{int(switch[1:]):016d}"
    for switch in SWITCHES
}

SWITCH_NAMES: dict[str, str] = {device_id: name for name, device_id in DEVICE_IDS.items()}

INTER_SWITCH_LINKS: tuple[InterSwitchLink, ...] = (
    InterSwitchLink("s1", 2, "s2", 1),
    InterSwitchLink("s1", 3, "s3", 1),
    InterSwitchLink("s1", 4, "s4", 1),
    InterSwitchLink("s1", 5, "s5", 1),
)

HOST_ATTACHMENTS: tuple[HostAttachment, ...] = (
    HostAttachment("h1", "s2", 3, 0, "h1-eth0", HOST_MACS["h1"], HOST_IPV4["h1"], "primary"),
    HostAttachment("h2", "s2", 4, 0, "h2-eth0", HOST_MACS["h2"], HOST_IPV4["h2"], "primary"),
    HostAttachment("h3", "s3", 3, 0, "h3-eth0", HOST_MACS["h3"], HOST_IPV4["h3"], "primary"),
    HostAttachment("h4", "s3", 4, 0, "h4-eth0", HOST_MACS["h4"], HOST_IPV4["h4"], "primary"),
    HostAttachment("h5", "s4", 3, 0, "h5-eth0", HOST_MACS["h5"], HOST_IPV4["h5"], "primary"),
    HostAttachment("h6", "s4", 4, 0, "h6-eth0", HOST_MACS["h6"], HOST_IPV4["h6"], "primary"),
    HostAttachment("h7", "s5", 3, 0, "h7-eth0", HOST_MACS["h7"], HOST_IPV4["h7"], "primary"),
    HostAttachment("h8", "s5", 4, 0, "h8-eth0", HOST_MACS["h8"], HOST_IPV4["h8"], "primary"),
)
