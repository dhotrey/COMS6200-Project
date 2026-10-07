"""tree5s8h fault catalogue: F1-F5 on the active tree."""

from __future__ import annotations

from faults.scenarios import (
    EXPERIMENT_APP_ID,
    EXPERIMENT_PRIORITY,
    AclScenario,
    CongestionScenario,
    LinkFailureScenario,
    LoopHop,
    LoopScenario,
    MissingFlowScenario,
    Scenario,
    _link,
)
from topologies.tree_spec import INTER_SWITCH_LINKS

CATALOGUE_VERSION = "tree5s8h-v1"
CATALOGUE_STATUS = "draft"


def _tree_link(a: str, a_port: int, b: str, b_port: int):
    return _link(a, a_port, b, b_port, links=INTER_SWITCH_LINKS)


TREE_CORE_LINK = _tree_link("s1", 1, "s2", 1)

F1 = LinkFailureScenario(
    scenario_id="F1", fault_family="link_failure",
    description="Disable the s1-s2 access link",
    link=TREE_CORE_LINK,
    affected_scope="h1,h2 are isolated from h3-h8",
    expected_correction="restore s1-s2 link",
    catalogue_version=CATALOGUE_VERSION,
)
F2 = CongestionScenario(
    scenario_id="F2", fault_family="congestion",
    description="Bounded TBF bottleneck on s1-s2 plus background cross traffic",
    link=TREE_CORE_LINK, shape_switch="s2", rate="1mbit", burst="32kbit",
    latency="400ms", background_src="h2", background_dst="h5",
    target_src="h1", target_dst="h5", background_duration_s=0, iperf_port=5202,
    affected_scope="throughput on paths between s2 and the other access switches",
    expected_correction="remove TBF qdisc and stop background iperf",
    catalogue_version=CATALOGUE_VERSION,
)
F3 = AclScenario(
    scenario_id="F3", fault_family="acl_policy_error",
    description="High-priority selective DROP for h1 to h5 on s1",
    switch="s1", src_host="h1", dst_host="h5", priority=EXPERIMENT_PRIORITY,
    app_id=EXPERIMENT_APP_ID, affected_scope="h1 to h5 only",
    expected_correction="remove experimental DROP rule",
    catalogue_version=CATALOGUE_VERSION,
)
F4 = LoopScenario(
    scenario_id="F4", fault_family="forwarding_loop",
    description="Bounce h1 to h5 between s1 and s2 with a bounded safety qdisc",
    src_host="h1", dst_host="h5", hops=(LoopHop("s1", 1), LoopHop("s2", 1)),
    safety_link=TREE_CORE_LINK, safety_shape_switch="s1", safety_rate="2mbit",
    safety_burst="32kbit", safety_latency="400ms", priority=EXPERIMENT_PRIORITY,
    app_id=EXPERIMENT_APP_ID, affected_scope="h1 to h5 blackholed in a two-switch loop",
    expected_correction="remove loop experiment flows and safety qdisc",
    catalogue_version=CATALOGUE_VERSION,
)
F5 = MissingFlowScenario(
    scenario_id="F5", fault_family="missing_flow",
    description="Remove s2 baseline unicast rule for destination h5",
    switch="s2", dst_host="h5", priority=41000, app_id="org.coms6200.baseline",
    affected_scope="hosts on s2 lose reachability to h5",
    expected_correction="reinstall baseline unicast rule for h5 on s2",
    catalogue_version=CATALOGUE_VERSION,
)

SCENARIOS: dict[str, Scenario] = {scenario.scenario_id: scenario for scenario in (F1, F2, F3, F4, F5)}