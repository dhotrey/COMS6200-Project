"""Fault Catalogue v1 scenario registry (operator/evaluator only).

Never imported by telemetry or future LLM tools.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from faults.catalogue import FAULT_CATALOGUE_VERSION
from topologies.spec import HOST_MACS, INTER_SWITCH_LINKS, InterSwitchLink, PRIMARY_IPV4


@dataclass(frozen=True)
class LinkEndpoint:
    switch: str
    port: int

    @property
    def interface(self) -> str:
        return f"{self.switch}-eth{self.port}"


def _link(a: str, a_port: int, b: str, b_port: int) -> InterSwitchLink:
    for item in INTER_SWITCH_LINKS:
        if (
            item.a == a
            and item.a_port == a_port
            and item.b == b
            and item.b_port == b_port
        ):
            return item
        if (
            item.a == b
            and item.a_port == b_port
            and item.b == a
            and item.b_port == a_port
        ):
            return item
    raise RuntimeError(f"canonical link {a}:{a_port}<->{b}:{b_port} missing from spec")


def _endpoints(link: InterSwitchLink) -> tuple[LinkEndpoint, LinkEndpoint]:
    return (
        LinkEndpoint(link.a, link.a_port),
        LinkEndpoint(link.b, link.b_port),
    )


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    fault_family: str
    description: str
    affected_scope: str
    expected_correction: str

    def ground_truth(self) -> dict[str, Any]:
        raise NotImplementedError


@dataclass(frozen=True)
class LinkFailureScenario(Scenario):
    link: InterSwitchLink

    @property
    def endpoints(self) -> tuple[LinkEndpoint, LinkEndpoint]:
        return _endpoints(self.link)

    @property
    def interfaces(self) -> tuple[str, str]:
        left, right = self.endpoints
        return (left.interface, right.interface)

    def ground_truth(self) -> dict[str, Any]:
        left, right = self.endpoints
        return {
            "catalogue_version": FAULT_CATALOGUE_VERSION,
            "scenario_id": self.scenario_id,
            "fault_family": self.fault_family,
            "location": {
                "link": [left.switch, right.switch],
                "ports": {left.switch: left.port, right.switch: right.port},
                "interfaces": list(self.interfaces),
            },
            "affected_scope": self.affected_scope,
            "expected_correction": self.expected_correction,
        }


@dataclass(frozen=True)
class CongestionScenario(Scenario):
    link: InterSwitchLink
    shape_switch: str  # which endpoint receives the tbf qdisc
    rate: str
    burst: str
    latency: str
    background_src: str
    background_dst: str
    target_src: str
    target_dst: str
    background_duration_s: int
    iperf_port: int

    @property
    def endpoints(self) -> tuple[LinkEndpoint, LinkEndpoint]:
        return _endpoints(self.link)

    @property
    def shape_iface(self) -> str:
        for endpoint in self.endpoints:
            if endpoint.switch == self.shape_switch:
                return endpoint.interface
        raise RuntimeError(f"shape switch {self.shape_switch} not on link")

    def ground_truth(self) -> dict[str, Any]:
        left, right = self.endpoints
        return {
            "catalogue_version": FAULT_CATALOGUE_VERSION,
            "scenario_id": self.scenario_id,
            "fault_family": self.fault_family,
            "location": {
                "link": [left.switch, right.switch],
                "ports": {left.switch: left.port, right.switch: right.port},
                "shape_interface": self.shape_iface,
                "background": [self.background_src, self.background_dst],
                "target": [self.target_src, self.target_dst],
            },
            "affected_scope": self.affected_scope,
            "expected_correction": self.expected_correction,
        }


@dataclass(frozen=True)
class AclScenario(Scenario):
    switch: str
    src_host: str
    dst_host: str
    priority: int
    app_id: str

    def ground_truth(self) -> dict[str, Any]:
        return {
            "catalogue_version": FAULT_CATALOGUE_VERSION,
            "scenario_id": self.scenario_id,
            "fault_family": self.fault_family,
            "location": {
                "switch": self.switch,
                "src_host": self.src_host,
                "dst_host": self.dst_host,
                "eth_src": HOST_MACS[self.src_host],
                "eth_dst": HOST_MACS[self.dst_host],
                "priority": self.priority,
            },
            "affected_scope": self.affected_scope,
            "expected_correction": self.expected_correction,
        }


@dataclass(frozen=True)
class LoopHop:
    switch: str
    out_port: int


@dataclass(frozen=True)
class LoopScenario(Scenario):
    src_host: str
    dst_host: str
    hops: tuple[LoopHop, ...]
    safety_link: InterSwitchLink
    safety_shape_switch: str
    safety_rate: str
    safety_burst: str
    safety_latency: str
    priority: int
    app_id: str

    @property
    def safety_iface(self) -> str:
        for endpoint in _endpoints(self.safety_link):
            if endpoint.switch == self.safety_shape_switch:
                return endpoint.interface
        raise RuntimeError("safety shape switch not on safety link")

    def ground_truth(self) -> dict[str, Any]:
        return {
            "catalogue_version": FAULT_CATALOGUE_VERSION,
            "scenario_id": self.scenario_id,
            "fault_family": self.fault_family,
            "location": {
                "src_host": self.src_host,
                "dst_host": self.dst_host,
                "hops": [
                    {"switch": h.switch, "out_port": h.out_port} for h in self.hops
                ],
                "safety_interface": self.safety_iface,
            },
            "affected_scope": self.affected_scope,
            "expected_correction": self.expected_correction,
        }


@dataclass(frozen=True)
class MissingFlowScenario(Scenario):
    switch: str
    dst_host: str
    priority: int
    app_id: str

    def ground_truth(self) -> dict[str, Any]:
        return {
            "catalogue_version": FAULT_CATALOGUE_VERSION,
            "scenario_id": self.scenario_id,
            "fault_family": self.fault_family,
            "location": {
                "switch": self.switch,
                "dst_host": self.dst_host,
                "eth_dst": HOST_MACS[self.dst_host],
                "priority": self.priority,
                "app_id": self.app_id,
            },
            "affected_scope": self.affected_scope,
            "expected_correction": self.expected_correction,
        }


# Neutral experimental app identity — visible in flows but not a fault label.
EXPERIMENT_APP_ID = "org.coms6200.experiment"
EXPERIMENT_PRIORITY = 50000  # reserved in forwarding/baseline_forwarding.py

F1 = LinkFailureScenario(
    scenario_id="F1",
    fault_family="link_failure",
    description="Disable the primary s3–s1 access-to-core uplink",
    link=_link("s1", 2, "s3", 1),
    affected_scope="h1/h2 remote connectivity via s1",
    expected_correction="restore primary s3-s1 link",
)

# Bottleneck on s1→s5 primary server-access path; bg h3→h6 and target h1→h5 cross it.
F2 = CongestionScenario(
    scenario_id="F2",
    fault_family="congestion",
    description="Bounded TBF bottleneck on s1–s5 plus background cross traffic",
    link=_link("s1", 4, "s5", 1),
    shape_switch="s1",
    rate="1mbit",
    burst="32kbit",
    latency="400ms",
    background_src="h3",
    background_dst="h6",
    target_src="h1",
    target_dst="h5",
    background_duration_s=120,
    iperf_port=5202,
    affected_scope="throughput on paths crossing s1-s5 (e.g. h1→h5)",
    expected_correction="remove TBF qdisc and stop background iperf",
)

F3 = AclScenario(
    scenario_id="F3",
    fault_family="acl_policy_error",
    description="High-priority selective DROP for h1→h5 on s3",
    switch="s3",
    src_host="h1",
    dst_host="h5",
    priority=EXPERIMENT_PRIORITY,
    app_id=EXPERIMENT_APP_ID,
    affected_scope="h1→h5 only; other hosts/paths remain reachable",
    expected_correction="remove experimental DROP rule",
)

# Narrow unicast cycle: s3 → s4 (test link) → s1 → s3 for h1→h5 only.
F4 = LoopScenario(
    scenario_id="F4",
    fault_family="forwarding_loop",
    description="Narrow h1→h5 unicast forwarding cycle s3→s4→s1→s3 with safety TBF",
    src_host="h1",
    dst_host="h5",
    hops=(
        LoopHop("s3", 5),  # to s4 via s3-s4
        LoopHop("s4", 1),  # to s1
        LoopHop("s1", 2),  # to s3
    ),
    safety_link=_link("s3", 5, "s4", 5),
    safety_shape_switch="s3",
    safety_rate="2mbit",
    safety_burst="32kbit",
    safety_latency="400ms",
    priority=EXPERIMENT_PRIORITY,
    app_id=EXPERIMENT_APP_ID,
    affected_scope="h1→h5 blackholed into a bounded loop",
    expected_correction="remove loop experiment flows and safety qdisc",
)

F5 = MissingFlowScenario(
    scenario_id="F5",
    fault_family="missing_flow",
    description="Remove s3 baseline unicast rule for destination h5",
    switch="s3",
    dst_host="h5",
    priority=41000,
    app_id="org.coms6200.baseline",
    affected_scope="hosts on s3 lose reachability to h5",
    expected_correction="reinstall baseline unicast rule for h5 on s3",
)

SCENARIOS: dict[str, Scenario] = {
    F1.scenario_id: F1,
    F2.scenario_id: F2,
    F3.scenario_id: F3,
    F4.scenario_id: F4,
    F5.scenario_id: F5,
}

RUNNABLE: frozenset[str] = frozenset(SCENARIOS)


def require_scenario(scenario_id: object) -> Scenario:
    if not isinstance(scenario_id, str) or scenario_id not in SCENARIOS:
        raise ValueError(f"unknown scenario; allowed runnable: {sorted(RUNNABLE)}")
    if scenario_id not in RUNNABLE:
        raise ValueError(f"scenario {scenario_id} is defined but not yet runnable")
    return SCENARIOS[scenario_id]


# Host IP helpers used by handlers (not exposed to telemetry).
def host_ip(host: str) -> str:
    return PRIMARY_IPV4[host]


def host_mac(host: str) -> str:
    return HOST_MACS[host]
