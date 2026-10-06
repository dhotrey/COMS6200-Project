"""Configured identities for the operator-selected topology.

``COMS6200_TOPOLOGY`` picks the spec: ``main6s8h`` (default) or ``ring5s5h``.
Telemetry, forwarding and the testbed helper import topology facts from here
so one setting switches them together. It is operator configuration read at
import time; the agent cannot change it.

``sudo`` drops environment variables by default. Root commands for a
non-default topology need ``sudo --preserve-env=COMS6200_TOPOLOGY``.
"""

from __future__ import annotations

import os
from types import ModuleType

from topologies import ring_spec
from topologies import spec as main_spec

DEFAULT_TOPOLOGY = "main6s8h"

SPECS: dict[str, ModuleType] = {
    "main6s8h": main_spec,
    "ring5s5h": ring_spec,
}


def _selected() -> str:
    name = os.environ.get("COMS6200_TOPOLOGY", "").strip() or DEFAULT_TOPOLOGY
    if name not in SPECS:
        raise RuntimeError(f"COMS6200_TOPOLOGY={name!r} is not one of {sorted(SPECS)}")
    return name


TOPOLOGY = _selected()
_spec = SPECS[TOPOLOGY]

SWITCHES: tuple[str, ...] = _spec.SWITCHES
HOSTS: tuple[str, ...] = _spec.HOSTS
DEVICE_IDS: dict[str, str] = _spec.DEVICE_IDS
SWITCH_NAMES: dict[str, str] = _spec.SWITCH_NAMES
HOST_IPV4: dict[str, str] = _spec.HOST_IPV4
HOST_MACS: dict[str, str] = _spec.HOST_MACS
PRIMARY_IPV4: dict[str, str] = _spec.PRIMARY_IPV4
INTER_SWITCH_LINKS: tuple[main_spec.InterSwitchLink, ...] = _spec.INTER_SWITCH_LINKS
HOST_ATTACHMENTS: tuple[main_spec.HostAttachment, ...] = _spec.HOST_ATTACHMENTS
switch_name = _spec.switch_name
peer_of = _spec.peer_of
