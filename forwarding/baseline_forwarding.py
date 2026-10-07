#!/usr/bin/env python3
"""Deterministic loop-free Layer-2 baseline forwarding.

Installs explicit ONOS flow rules over an active tree for the topology chosen
by COMS6200_TOPOLOGY (topologies/active.py). main6s8h uses the verified M3
s1 tree. ring5s5h leaves the s5-s1 ring link unused, giving the chain
s1-s2-s3-s4-s5. tree5s8h uses all four links. Redundant and test links stay
physically present but are unused by baseline forwarding.

This module is the M3 provisioner. It is not the telemetry gateway, fault
injector, scripted troubleshooter, or LLM agent.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

# Also run as a script (python3 forwarding/baseline_forwarding.py), where only
# forwarding/ is on sys.path.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from topologies import active  # noqa: E402
from topologies.spec import HostAttachment, InterSwitchLink  # noqa: E402

APP_NAME = "org.coms6200.baseline"
DEFAULT_ONOS_URL = "http://127.0.0.1:8181/onos/v1"

# Observed ONOS org.onosproject.core control flows on this testbed:
#   ETH_TYPE 0x88cc LLDP  priority 40000
#   ETH_TYPE 0x8942 BDDP  priority 40000
#   ETH_TYPE 0x0806 ARP   priority 40000
# Unicast dest-MAC rules must outrank the generic ARP punt so ARP replies
# forward in the data plane. ARP-tree rules must outrank it for broadcasts.
# Future injected faults should use FAULT_PRIORITY >= 50000 (not installed here).
BASELINE_UNICAST_PRIORITY = 41000
BASELINE_ARP_PRIORITY = 42000
FAULT_PRIORITY = 50000  # documented reservation only; unused by this module

ETH_TYPE_ARP = 0x0806
BROADCAST_MAC = "ff:ff:ff:ff:ff:ff"

HOST_MACS: dict[str, str] = {
    "h1": "00:00:00:00:00:01",
    "h2": "00:00:00:00:00:02",
    "h3": "00:00:00:00:00:03",
    "h4": "00:00:00:00:00:04",
    "h5": "00:00:00:00:00:05",
    "h6": "00:00:00:00:00:06",  # primary h6-eth0 only
    "h7": "00:00:00:00:00:07",
    "h8": "00:00:00:00:00:08",
}

DEVICE_IDS: dict[str, str] = {
    "s1": "of:0000000000000001",
    "s2": "of:0000000000000002",
    "s3": "of:0000000000000003",
    "s4": "of:0000000000000004",
    "s5": "of:0000000000000005",
    "s6": "of:0000000000000006",
}

# Destination-MAC -> egress port on the active tree. s2 has none.
UNICAST_EGRESS: dict[str, dict[str, int]] = {
    "s1": {"h1": 2, "h2": 2, "h3": 3, "h4": 3, "h5": 4, "h6": 4, "h7": 5, "h8": 5},
    "s3": {"h1": 3, "h2": 4, "h3": 1, "h4": 1, "h5": 1, "h6": 1, "h7": 1, "h8": 1},
    "s4": {"h1": 1, "h2": 1, "h3": 3, "h4": 4, "h5": 1, "h6": 1, "h7": 1, "h8": 1},
    "s5": {"h1": 1, "h2": 1, "h3": 1, "h4": 1, "h5": 3, "h6": 4, "h7": 1, "h8": 1},
    "s6": {"h1": 1, "h2": 1, "h3": 1, "h4": 1, "h5": 1, "h6": 1, "h7": 3, "h8": 4},
}

# Ingress ports that may carry ARP broadcasts on the active tree.
ARP_ACTIVE_PORTS: dict[str, tuple[int, ...]] = {
    "s1": (2, 3, 4, 5),
    "s2": (),
    "s3": (1, 3, 4),
    "s4": (1, 3, 4),
    "s5": (1, 3, 4),
    "s6": (1, 3, 4),
}

# Ports that must never appear in baseline OUTPUT actions.
RESERVED_PORTS: dict[str, frozenset[int]] = {
    "s1": frozenset({1}),  # s1-s2
    "s2": frozenset({1, 2, 3, 4, 5}),
    "s3": frozenset({2, 5}),  # s2 uplink, s3-s4
    "s4": frozenset({2, 5}),  # s2 uplink, s4-s3
    "s5": frozenset({2}),  # s2 uplink
    "s6": frozenset({2, 5}),  # s2 uplink, h6-eth1
}

# Ring link left physically present but unused by baseline forwarding.
# Leaving s5-s1 out gives the loop-free active chain s1-s2-s3-s4-s5.
RING_RESERVED_LINKS: tuple[InterSwitchLink, ...] = (InterSwitchLink("s5", 1, "s1", 2),)


def tree_forwarding(
    switches: Iterable[str],
    links: Iterable[InterSwitchLink],
    attachments: Iterable[HostAttachment],
    reserved_links: Iterable[InterSwitchLink],
) -> tuple[dict[str, dict[str, int]], dict[str, tuple[int, ...]], dict[str, frozenset[int]]]:
    """Derive UNICAST_EGRESS, ARP_ACTIVE_PORTS and RESERVED_PORTS for one tree.

    Active links are the configured links minus ``reserved_links``. They must
    form one loop-free tree that reaches every primary host attachment.
    Switches outside that tree get no host forwarding. Reserved links and
    non-primary host attachments become reserved ports.
    """
    switches = tuple(switches)
    links = tuple(links)
    reserved = set(reserved_links)
    unknown = reserved - set(links)
    if unknown:
        raise ValueError(f"reserved links are not configured links: {sorted(map(str, unknown))}")
    hosts = [item for item in attachments if item.role == "primary"]
    if not hosts:
        raise ValueError("no primary host attachments")

    # switch -> [(local port, peer switch, peer port)] over active links only
    neighbours: dict[str, list[tuple[int, str, int]]] = {switch: [] for switch in switches}
    active_links = [link for link in links if link not in reserved]
    for link in active_links:
        neighbours[link.a].append((link.a_port, link.b, link.b_port))
        neighbours[link.b].append((link.b_port, link.a, link.a_port))

    def ports_toward(target: str) -> dict[str, int]:
        """For each other tree switch, the port whose next hop leads toward target."""
        toward: dict[str, int] = {}
        seen = {target}
        queue = deque([target])
        while queue:
            current = queue.popleft()
            for _port, peer, peer_port in neighbours[current]:
                if peer not in seen:
                    seen.add(peer)
                    toward[peer] = peer_port
                    queue.append(peer)
        return toward

    tree = {hosts[0].switch, *ports_toward(hosts[0].switch)}
    off_tree = sorted({item.switch for item in hosts} - tree)
    if off_tree:
        raise ValueError(f"primary hosts on {off_tree} are not on the active tree")
    if sum(1 for link in active_links if link.a in tree) != len(tree) - 1:
        raise ValueError("active links contain a loop")

    unicast: dict[str, dict[str, int]] = {switch: {} for switch in switches if switch in tree}
    for item in hosts:
        toward = ports_toward(item.switch)
        for switch, egress in unicast.items():
            egress[item.host] = item.switch_port if switch == item.switch else toward[switch]

    arp_ports: dict[str, tuple[int, ...]] = {}
    for switch in switches:
        if switch not in tree:
            arp_ports[switch] = ()
            continue
        ports = [port for port, _peer, _peer_port in neighbours[switch]]
        ports += [item.switch_port for item in hosts if item.switch == switch]
        arp_ports[switch] = tuple(sorted(ports))

    reserved_ports: dict[str, set[int]] = {switch: set() for switch in switches}
    for link in reserved:
        reserved_ports[link.a].add(link.a_port)
        reserved_ports[link.b].add(link.b_port)
    for item in attachments:
        if item.role != "primary":
            reserved_ports[item.switch].add(item.switch_port)
    return unicast, arp_ports, {switch: frozenset(ports) for switch, ports in reserved_ports.items()}


# The main6s8h tables above are the verified M3 literals. Other topologies
# derive theirs from the selected spec and their reserved links.
if active.TOPOLOGY == "ring5s5h":
    HOST_MACS = dict(active.HOST_MACS)
    DEVICE_IDS = dict(active.DEVICE_IDS)
    UNICAST_EGRESS, ARP_ACTIVE_PORTS, RESERVED_PORTS = tree_forwarding(
        active.SWITCHES,
        active.INTER_SWITCH_LINKS,
        active.HOST_ATTACHMENTS,
        RING_RESERVED_LINKS,
    )
elif active.TOPOLOGY == "tree5s8h":
    HOST_MACS = dict(active.HOST_MACS)
    DEVICE_IDS = dict(active.DEVICE_IDS)
    UNICAST_EGRESS, ARP_ACTIVE_PORTS, RESERVED_PORTS = tree_forwarding(
        active.SWITCHES,
        active.INTER_SWITCH_LINKS,
        active.HOST_ATTACHMENTS,
        (),
    )
elif active.TOPOLOGY != "main6s8h":
    raise RuntimeError(f"no baseline forwarding plan for {active.TOPOLOGY}")

SWITCH_NAMES = {device_id: name for name, device_id in DEVICE_IDS.items()}


@dataclass(frozen=True)
class FlowSpec:
    switch: str
    priority: int
    selector: tuple[tuple[str, str], ...]
    outputs: tuple[int, ...]
    kind: str

    @property
    def device_id(self) -> str:
        return DEVICE_IDS[self.switch]


def _mac(value: str) -> str:
    return value.strip().lower()


def arp_outputs(switch: str, in_port: int) -> tuple[int, ...]:
    return tuple(port for port in ARP_ACTIVE_PORTS[switch] if port != in_port)


def expected_flow_specs() -> tuple[FlowSpec, ...]:
    specs: list[FlowSpec] = []
    for switch, destinations in UNICAST_EGRESS.items():
        for host, port in destinations.items():
            specs.append(
                FlowSpec(
                    switch=switch,
                    priority=BASELINE_UNICAST_PRIORITY,
                    selector=(("ETH_DST", _mac(HOST_MACS[host])),),
                    outputs=(port,),
                    kind="unicast",
                )
            )
    for switch, ports in ARP_ACTIVE_PORTS.items():
        for in_port in ports:
            outs = arp_outputs(switch, in_port)
            if not outs:
                continue
            specs.append(
                FlowSpec(
                    switch=switch,
                    priority=BASELINE_ARP_PRIORITY,
                    selector=(
                        ("ETH_TYPE", hex(ETH_TYPE_ARP)),
                        ("ETH_DST", BROADCAST_MAC),
                        ("IN_PORT", str(in_port)),
                    ),
                    outputs=outs,
                    kind="arp",
                )
            )
    return tuple(specs)


def expected_flow_count() -> int:
    return len(expected_flow_specs())


def expected_count_by_switch() -> dict[str, int]:
    counts = {name: 0 for name in DEVICE_IDS}
    for spec in expected_flow_specs():
        counts[spec.switch] += 1
    return counts


def spec_to_onos_json(spec: FlowSpec) -> dict[str, Any]:
    criteria: list[dict[str, str]] = []
    for key, value in spec.selector:
        if key == "ETH_DST":
            criteria.append({"type": "ETH_DST", "mac": value})
        elif key == "ETH_TYPE":
            criteria.append({"type": "ETH_TYPE", "ethType": value})
        elif key == "IN_PORT":
            criteria.append({"type": "IN_PORT", "port": value})
        else:
            raise ValueError(f"unsupported selector {key}")
    return {
        "priority": spec.priority,
        "timeout": 0,
        "isPermanent": True,
        "deviceId": spec.device_id,
        "tableId": 0,
        "appId": APP_NAME,
        "selector": {"criteria": criteria},
        "treatment": {
            "instructions": [{"type": "OUTPUT", "port": str(port)} for port in spec.outputs]
        },
    }


def _eth_type_int(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text.startswith("0x"):
        return int(text, 16)
    try:
        return int(text)
    except ValueError:
        return None


def _criterion_key(criterion: dict[str, Any]) -> tuple[str, str] | None:
    kind = str(criterion.get("type", "")).upper()
    if kind == "ETH_DST":
        return ("ETH_DST", _mac(str(criterion.get("mac", ""))))
    if kind == "ETH_TYPE":
        parsed = _eth_type_int(criterion.get("ethType"))
        if parsed is None:
            return None
        return ("ETH_TYPE", hex(parsed))
    if kind == "IN_PORT":
        return ("IN_PORT", str(criterion.get("port")))
    return None


def _output_ports(flow: dict[str, Any]) -> list[int]:
    instructions = (flow.get("treatment") or {}).get("instructions") or []
    ports: list[int] = []
    for instruction in instructions:
        if str(instruction.get("type", "")).upper() != "OUTPUT":
            continue
        port = instruction.get("port")
        if port is None:
            continue
        text = str(port)
        if text.isdigit():
            ports.append(int(text))
    return ports


def flow_matches_spec(flow: dict[str, Any], spec: FlowSpec) -> bool:
    if flow.get("deviceId") != spec.device_id:
        return False
    if int(flow.get("priority", -1)) != spec.priority:
        return False
    actual = {
        item
        for item in (_criterion_key(c) for c in (flow.get("selector") or {}).get("criteria") or [])
        if item is not None
    }
    expected = set(spec.selector)
    if actual != expected:
        return False
    return tuple(_output_ports(flow)) == spec.outputs


def is_baseline_flow(flow: dict[str, Any]) -> bool:
    return str(flow.get("appId", "")) == APP_NAME


def credentials_from_env() -> tuple[str, str, str]:
    user = os.environ.get("ONOS_USER", "").strip()
    password = os.environ.get("ONOS_PASSWORD", "")
    url = os.environ.get("ONOS_URL", DEFAULT_ONOS_URL).strip() or DEFAULT_ONOS_URL
    if not user or not password:
        raise SystemExit(
            "ONOS_USER and ONOS_PASSWORD must be set in the environment.\n"
            "Example (do not commit the password):\n"
            "  export ONOS_USER=onos\n"
            "  export ONOS_PASSWORD='<your ONOS REST password>'\n"
            "Optional: export ONOS_URL=http://127.0.0.1:8181/onos/v1"
        )
    return user, password, url.rstrip("/")


class OnosClient:
    def __init__(self, url: str, user: str, password: str) -> None:
        self.url = url.rstrip("/")
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        self._auth = f"Basic {token}"

    def request(
        self,
        method: str,
        path: str,
        body: Any | None = None,
        query: dict[str, str] | None = None,
    ) -> tuple[int, Any]:
        encoded = ""
        if query:
            encoded = "?" + urllib.parse.urlencode(query)
        url = f"{self.url}/{path.lstrip('/')}{encoded}"
        data = None
        headers = {"Accept": "application/json", "Authorization": self._auth}
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
                payload: Any = {}
                if raw:
                    payload = json.loads(raw.decode())
                return response.status, payload
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            detail = raw.decode(errors="replace")[:500]
            raise RuntimeError(f"ONOS {method} /{path} HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"ONOS {method} /{path} failed: {exc.reason}") from exc

    def get(self, path: str) -> Any:
        _status, payload = self.request("GET", path)
        return payload

    def post(self, path: str, body: Any, query: dict[str, str] | None = None) -> Any:
        _status, payload = self.request("POST", path, body=body, query=query)
        return payload

    def delete(self, path: str, body: Any | None = None) -> Any:
        _status, payload = self.request("DELETE", path, body=body)
        return payload


def application_entry(client: OnosClient) -> dict[str, Any] | None:
    payload = client.get("applications/ids")
    for entry in payload.get("applicationIds", []):
        if entry.get("name") == APP_NAME:
            return entry
    return None


def list_all_flows(client: OnosClient) -> list[dict[str, Any]]:
    return list(client.get("flows").get("flows") or [])


def list_baseline_flows(client: OnosClient) -> list[dict[str, Any]]:
    """Baseline flows on this topology's devices only.

    ONOS keeps rules for switches that have disconnected, such as the other
    topology's DPIDs after a switch-over. Those are not this topology's flows
    and cannot be removed until their devices reconnect.
    """
    devices = set(DEVICE_IDS.values())
    return [
        flow
        for flow in list_all_flows(client)
        if is_baseline_flow(flow) and flow.get("deviceId") in devices
    ]


def list_devices(client: OnosClient) -> list[dict[str, Any]]:
    return list(client.get("devices").get("devices") or [])


def require_topology(client: OnosClient) -> None:
    devices = {item.get("id"): item for item in list_devices(client)}
    missing = [name for name, device_id in DEVICE_IDS.items() if device_id not in devices]
    if missing:
        raise RuntimeError(
            f"ONOS does not currently have the {active.TOPOLOGY} devices: "
            + ", ".join(missing)
            + f". Launch Mininet with --topo {active.TOPOLOGY} and a remote ONOS controller first."
        )
    unavailable = [
        name
        for name, device_id in DEVICE_IDS.items()
        if not devices[device_id].get("available", False)
    ]
    if unavailable:
        raise RuntimeError("ONOS devices not available: " + ", ".join(unavailable))


def install_flows(client: OnosClient, timeout_s: float = 20.0) -> list[dict[str, Any]]:
    require_topology(client)
    existing = list_baseline_flows(client)
    if existing:
        print(f"Removing {len(existing)} stale {APP_NAME} flow(s) before install")
        remove_flows(client, timeout_s=timeout_s)
    specs = expected_flow_specs()
    body = {"flows": [spec_to_onos_json(spec) for spec in specs]}
    print(f"Installing {len(specs)} {APP_NAME} flow rules")
    client.post("flows", body, query={"appId": APP_NAME})
    deadline = time.time() + timeout_s
    while True:
        flows = list_baseline_flows(client)
        states = {str(flow.get("state")) for flow in flows}
        if len(flows) == len(specs) and states == {"ADDED"}:
            print(f"All {len(flows)} baseline flows are ADDED")
            return flows
        if time.time() >= deadline:
            by_state: dict[str, int] = {}
            for flow in flows:
                state = str(flow.get("state", "UNKNOWN"))
                by_state[state] = by_state.get(state, 0) + 1
            raise RuntimeError(
                f"Baseline flows did not all reach ADDED within {timeout_s:.0f}s: "
                f"count={len(flows)}/{len(specs)} states={by_state}"
            )
        time.sleep(0.4)


def remove_flows(client: OnosClient, timeout_s: float = 20.0) -> int:
    flows = list_baseline_flows(client)
    if not flows:
        print(f"No {APP_NAME} flows to remove")
        return 0
    body = {
        "flows": [
            {"deviceId": flow["deviceId"], "flowId": int(str(flow["id"]))}
            for flow in flows
            if flow.get("id") is not None
        ]
    }
    client.delete("flows", body=body)
    deadline = time.time() + timeout_s
    while True:
        remaining = list_baseline_flows(client)
        if not remaining:
            print(f"Removed {len(flows)} {APP_NAME} flow(s)")
            return len(flows)
        if time.time() >= deadline:
            raise RuntimeError(
                f"{len(remaining)} {APP_NAME} flow(s) remain after remove "
                f"waited {timeout_s:.0f}s"
            )
        time.sleep(0.4)


def _count_by_device(flows: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts = {name: 0 for name in DEVICE_IDS}
    for flow in flows:
        name = SWITCH_NAMES.get(str(flow.get("deviceId")), "other")
        counts[name] = counts.get(name, 0) + 1
    return counts


def status_report(client: OnosClient, verbose: bool = False) -> dict[str, Any]:
    app = application_entry(client)
    all_flows = list_all_flows(client)
    devices = set(DEVICE_IDS.values())
    ours = [flow for flow in all_flows if is_baseline_flow(flow) and flow.get("deviceId") in devices]
    other = [flow for flow in all_flows if is_baseline_flow(flow) and flow.get("deviceId") not in devices]
    system = [flow for flow in all_flows if not is_baseline_flow(flow)]
    states: dict[str, int] = {}
    for flow in ours:
        state = str(flow.get("state", "UNKNOWN"))
        states[state] = states.get(state, 0) + 1
    expected = expected_flow_specs()
    matched = [spec for spec in expected if any(flow_matches_spec(flow, spec) for flow in ours)]
    report = {
        "appId": APP_NAME,
        "topology": active.TOPOLOGY,
        "otherDeviceAppFlows": len(other),
        "numericId": None if app is None else app.get("id"),
        "expectedFlowCount": len(expected),
        "actualAppFlowCount": len(ours),
        "systemFlowCount": len(system),
        "totalFlowCount": len(all_flows),
        "perDeviceAppFlows": _count_by_device(ours),
        "states": states,
        "matchedExpected": len(matched),
        "missingExpected": len(expected) - len(matched),
        "unicastPriority": BASELINE_UNICAST_PRIORITY,
        "arpPriority": BASELINE_ARP_PRIORITY,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    if verbose:
        for flow in sorted(ours, key=lambda item: (str(item.get("deviceId")), int(item.get("priority", 0)))):
            print(
                flow.get("deviceId"),
                flow.get("state"),
                "prio",
                flow.get("priority"),
                flow.get("selector"),
                "->",
                _output_ports(flow),
            )
    return report


def verify_flows(client: OnosClient) -> int:
    ours = list_baseline_flows(client)
    failures: list[str] = []
    expected = expected_flow_specs()
    if len(ours) != len(expected):
        failures.append(f"count {len(ours)} != expected {len(expected)}")

    for spec in expected:
        if not any(flow_matches_spec(flow, spec) for flow in ours):
            failures.append(
                f"missing {spec.kind} on {spec.switch} selector={dict(spec.selector)} outs={spec.outputs}"
            )

    # Switches off the active tree (main6s8h: s2) must carry no host forwarding.
    idle = [switch for switch, count in expected_count_by_switch().items() if count == 0]
    for switch in idle:
        idle_flows = [flow for flow in ours if flow.get("deviceId") == DEVICE_IDS[switch]]
        if idle_flows:
            failures.append(f"{switch} has {len(idle_flows)} baseline flow(s); expected 0")

    for flow in ours:
        switch = SWITCH_NAMES.get(str(flow.get("deviceId")))
        if switch is None:
            failures.append(f"baseline flow on unexpected device {flow.get('deviceId')}")
            continue
        reserved = RESERVED_PORTS.get(switch, frozenset())
        used = set(_output_ports(flow))
        bad = sorted(used & reserved)
        if bad:
            failures.append(f"{switch} baseline flow outputs reserved ports {bad}")
        if flow.get("priority") == BASELINE_ARP_PRIORITY:
            in_port = next(
                (str(c.get("port")) for c in (flow.get("selector") or {}).get("criteria") or [] if c.get("type") == "IN_PORT"),
                None,
            )
            if in_port and in_port.isdigit() and int(in_port) in used:
                failures.append(f"{switch} ARP rule outputs back to ingress {in_port}")

    banned_actions = {"NORMAL", "FLOOD", "TABLE"}
    for flow in ours:
        for instruction in (flow.get("treatment") or {}).get("instructions") or []:
            port = str(instruction.get("port", "")).upper()
            if port in banned_actions:
                failures.append(f"baseline flow uses {port}")

    if failures:
        print("VERIFY FAIL")
        for item in failures:
            print(" -", item)
        return 1
    print("VERIFY PASS")
    idle_text = "".join(f"{switch} host forwarding=0; " for switch in idle)
    print(
        f"{APP_NAME}: {len(ours)} ADDED flows; {idle_text}"
        "no reserved-link outputs; no NORMAL/FLOOD"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install, inspect or remove deterministic ONOS baseline forwarding."
    )
    parser.add_argument("command", choices=("install", "status", "remove", "verify"))
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--timeout", type=float, default=20.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    user, password, url = credentials_from_env()
    client = OnosClient(url, user, password)
    if args.command == "install":
        install_flows(client, timeout_s=args.timeout)
        return verify_flows(client)
    if args.command == "status":
        status_report(client, verbose=args.verbose)
        return 0
    if args.command == "remove":
        remove_flows(client, timeout_s=args.timeout)
        return 0
    return verify_flows(client)


if __name__ == "__main__":
    sys.exit(main())
