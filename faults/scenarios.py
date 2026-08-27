"""M5 fault injection scenarios.

Operator/evaluator only. Never imported by telemetry or future LLM tools.
Currently only F1 (primary s3–s1 link failure) is runnable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from topologies.spec import INTER_SWITCH_LINKS, InterSwitchLink


@dataclass(frozen=True)
class LinkEndpoint:
    switch: str
    port: int

    @property
    def interface(self) -> str:
        """Mininet/OVS data-plane interface name for an explicit port map."""
        return f"{self.switch}-eth{self.port}"


@dataclass(frozen=True)
class LinkFailureScenario:
    scenario_id: str
    fault_family: str
    description: str
    link: InterSwitchLink
    affected_scope: str
    expected_correction: str

    @property
    def endpoints(self) -> tuple[LinkEndpoint, LinkEndpoint]:
        return (
            LinkEndpoint(self.link.a, self.link.a_port),
            LinkEndpoint(self.link.b, self.link.b_port),
        )

    @property
    def interfaces(self) -> tuple[str, str]:
        left, right = self.endpoints
        return (left.interface, right.interface)

    def ground_truth(self) -> dict[str, Any]:
        left, right = self.endpoints
        return {
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


# Primary access-to-core uplink used by baseline h1/h2 remote paths.
F1 = LinkFailureScenario(
    scenario_id="F1",
    fault_family="link_failure",
    description="Disable the primary s3–s1 access-to-core uplink",
    link=_link("s1", 2, "s3", 1),
    affected_scope="h1/h2 remote connectivity via s1",
    expected_correction="restore primary s3-s1 link",
)

SCENARIOS: dict[str, LinkFailureScenario] = {
    F1.scenario_id: F1,
}

RUNNABLE: frozenset[str] = frozenset({"F1"})


def require_scenario(scenario_id: object) -> LinkFailureScenario:
    if not isinstance(scenario_id, str) or scenario_id not in SCENARIOS:
        raise ValueError(f"unknown scenario; allowed runnable: {sorted(RUNNABLE)}")
    if scenario_id not in RUNNABLE:
        raise ValueError(f"scenario {scenario_id} is defined but not yet runnable")
    return SCENARIOS[scenario_id]
