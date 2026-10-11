"""Configured identities for the operator-selected topology.

``COMS6200_TOPOLOGY`` picks the spec: ``main6s8h`` (default), ``ring5s5h`` or
``tree5s8h``.
Telemetry, forwarding and the testbed helper import topology facts from here
so one setting switches them together. It is operator configuration read at
import time; the agent cannot change it.

``sudo`` drops environment variables by default. Root commands for a
non-default topology need ``sudo --preserve-env=COMS6200_TOPOLOGY``.
"""

from __future__ import annotations

import os
from types import ModuleType

from topologies import ring_spec, tree_spec
from topologies import spec as main_spec

DEFAULT_TOPOLOGY = "main6s8h"

SPECS: dict[str, ModuleType] = {
    "main6s8h": main_spec,
    "ring5s5h": ring_spec,
    "tree5s8h": tree_spec,
}


def _selected() -> str:
    name = os.environ.get("COMS6200_TOPOLOGY", "").strip() or DEFAULT_TOPOLOGY
    if name not in SPECS:
        raise RuntimeError(f"COMS6200_TOPOLOGY={name!r} is not one of {sorted(SPECS)}")
    return name


def select(name: str) -> None:
    """Select configured facts while the local agent has network operations locked.

    Runtime consumers must read attributes from this module, rather than keep
    copies imported with `from topologies.active import ...`.
    """
    if name not in SPECS:
        raise ValueError(f"unknown topology: {name}")
    global TOPOLOGY, SWITCHES, HOSTS, DEVICE_IDS, SWITCH_NAMES
    global HOST_IPV4, HOST_MACS, PRIMARY_IPV4, INTER_SWITCH_LINKS, HOST_ATTACHMENTS
    global switch_name, peer_of
    spec = SPECS[name]
    TOPOLOGY = name
    SWITCHES = spec.SWITCHES
    HOSTS = spec.HOSTS
    DEVICE_IDS = spec.DEVICE_IDS
    SWITCH_NAMES = spec.SWITCH_NAMES
    HOST_IPV4 = spec.HOST_IPV4
    HOST_MACS = spec.HOST_MACS
    PRIMARY_IPV4 = spec.PRIMARY_IPV4
    INTER_SWITCH_LINKS = spec.INTER_SWITCH_LINKS
    HOST_ATTACHMENTS = spec.HOST_ATTACHMENTS
    switch_name = spec.switch_name
    peer_of = spec.peer_of


select(_selected())
