"""ring5s5h fault catalogue: F1–F5 placed on the five-switch ring.

Same fault families, mechanisms, rates and workloads as Fault Catalogue v1,
at hand-picked ring locations. Every scenario breaks or slows h1→h5, so the
v1 symptom prompts still apply. Baseline forwarding leaves s5–s1 unused
(chain s1-s2-s3-s4-s5), so h1→h5 crosses all four chain links even though
h1 and h5 sit on adjacent switches.

Draft until runtime verified. After verification, any change to a target,
selector, workload or reset behaviour needs a new catalogue version.

Operator/evaluator only. Never imported by telemetry.
"""

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
from topologies.ring_spec import INTER_SWITCH_LINKS, InterSwitchLink

CATALOGUE_VERSION = "ring5s5h-v1"
CATALOGUE_STATUS = "draft"


def _ring_link(a: str, a_port: int, b: str, b_port: int) -> InterSwitchLink:
    return _link(a, a_port, b, b_port, links=INTER_SWITCH_LINKS)


# Middle of the chain: splits {h1,h2,h3} from {h4,h5}. Static forwarding does
# not reroute over the unused s5–s1 link.
F1 = LinkFailureScenario(
    scenario_id="F1",
    fault_family="link_failure",
    description="Disable the s3–s4 ring link on the active chain",
    link=_ring_link("s3", 1, "s4", 2),
    affected_scope="pairs split by s3-s4: {h1,h2,h3} <-> {h4,h5}",
    expected_correction="restore s3-s4 link",
    catalogue_version=CATALOGUE_VERSION,
)

# Bottleneck on s2→s3; background h2→h4 and target h1→h5 both cross it.
F2 = CongestionScenario(
    scenario_id="F2",
    fault_family="congestion",
    description="Bounded TBF bottleneck on s2–s3 plus background cross traffic",
    link=_ring_link("s2", 1, "s3", 2),
    shape_switch="s2",
    rate="1mbit",
    burst="32kbit",
    latency="400ms",
    background_src="h2",
    background_dst="h4",
    target_src="h1",
    target_dst="h5",
    # 0 means the background iperf runs until F2 reset. It is not a 120-second timer.
    background_duration_s=0,
    iperf_port=5202,
    affected_scope="throughput on paths crossing s2→s3 (e.g. h1→h5)",
    expected_correction="remove TBF qdisc and stop background iperf",
    catalogue_version=CATALOGUE_VERSION,
)

# Mid-path transit switch, not h1's own switch.
F3 = AclScenario(
    scenario_id="F3",
    fault_family="acl_policy_error",
    description="High-priority selective DROP for h1→h5 on s4",
    switch="s4",
    src_host="h1",
    dst_host="h5",
    priority=EXPERIMENT_PRIORITY,
    app_id=EXPERIMENT_APP_ID,
    affected_scope="h1→h5 only; other hosts/paths remain reachable",
    expected_correction="remove experimental DROP rule",
    catalogue_version=CATALOGUE_VERSION,
)

# The ring's only cycle is the whole ring. Every hop goes clockwise, so s5
# sends h1→h5 back to s1 over the unused s5–s1 link instead of delivering it.
F4 = LoopScenario(
    scenario_id="F4",
    fault_family="forwarding_loop",
    description="Narrow h1→h5 unicast cycle around the ring s1→s2→s3→s4→s5→s1 with safety TBF",
    src_host="h1",
    dst_host="h5",
    hops=(
        LoopHop("s1", 1),  # to s2
        LoopHop("s2", 1),  # to s3
        LoopHop("s3", 1),  # to s4
        LoopHop("s4", 1),  # to s5
        LoopHop("s5", 1),  # to s1 over the unused s5-s1 link
    ),
    safety_link=_ring_link("s5", 1, "s1", 2),
    safety_shape_switch="s5",
    safety_rate="2mbit",
    safety_burst="32kbit",
    safety_latency="400ms",
    priority=EXPERIMENT_PRIORITY,
    app_id=EXPERIMENT_APP_ID,
    affected_scope="h1→h5 blackholed into a bounded loop",
    expected_correction="remove loop experiment flows and safety qdisc",
    catalogue_version=CATALOGUE_VERSION,
)

# s2 carries h1's and h2's traffic toward h5, as s3 does in main6s8h.
F5 = MissingFlowScenario(
    scenario_id="F5",
    fault_family="missing_flow",
    description="Remove s2 baseline unicast rule for destination h5",
    switch="s2",
    dst_host="h5",
    priority=41000,
    app_id="org.coms6200.baseline",
    affected_scope="hosts whose path to h5 crosses s2 (h1, h2) lose reachability to h5",
    expected_correction="reinstall baseline unicast rule for h5 on s2",
    catalogue_version=CATALOGUE_VERSION,
)

SCENARIOS: dict[str, Scenario] = {
    F1.scenario_id: F1,
    F2.scenario_id: F2,
    F3.scenario_id: F3,
    F4.scenario_id: F4,
    F5.scenario_id: F5,
}
