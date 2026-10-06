"""F4 narrow unicast forwarding loop with a safety TBF on a non-baseline link."""

from __future__ import annotations

from typing import Any

from faults.common import (
    FaultError,
    require_root,
    tc_del_root,
    tc_replace_tbf,
    tc_show,
    validate_iface_bridge,
)
from faults.onos_experiment import (
    eth_src_dst_criteria,
    experiment_flow_json,
    install_experiment_flows,
    list_experiment_flows,
    remove_experiment_flows,
)
from faults.scenarios import LoopScenario, host_mac
from faults.state import clear_state, utc_now, write_state


def inject_f4(scenario: LoopScenario) -> dict[str, Any]:
    require_root()
    if list_experiment_flows():
        raise FaultError(
            "EXPERIMENT_FLOWS_PRESENT",
            "org.coms6200.experiment flows already present; reset first",
        )
    iface = scenario.safety_iface
    row = validate_iface_bridge(iface, scenario.safety_shape_switch)
    if row["operstate"] != "up":
        raise FaultError("LINK_NOT_UP", f"safety iface {iface} must be UP")

    eth_src = host_mac(scenario.src_host)
    eth_dst = host_mac(scenario.dst_host)
    flows = [
        experiment_flow_json(
            switch=hop.switch,
            priority=scenario.priority,
            criteria=eth_src_dst_criteria(eth_src, eth_dst),
            outputs=[hop.out_port],
        )
        for hop in scenario.hops
    ]

    pending = {
        "status": "PENDING",
        "scenario_id": "F4",
        "injected_at": utc_now(),
        "safety_interface": iface,
        "ground_truth": scenario.ground_truth(),
        "note": "evaluator/operator only; never expose to telemetry or LLM tools",
    }
    write_state(pending)

    try:
        # Safety qdisc BEFORE installing the cycle.
        tc_replace_tbf(
            iface,
            scenario.safety_rate,
            scenario.safety_burst,
            scenario.safety_latency,
        )
        installed = install_experiment_flows(flows)
    except Exception:
        try:
            remove_experiment_flows()
        except FaultError:
            pass
        tc_del_root(iface)
        clear_state()
        raise

    active = dict(pending)
    active["status"] = "ACTIVE"
    active["verified_at"] = utc_now()
    active["flow_ids"] = [
        {"deviceId": f.get("deviceId"), "flowId": f.get("id")} for f in installed
    ]
    active["tc_show"] = tc_show(iface).strip()
    write_state(active)
    return {
        "scenario_id": "F4",
        "status": "ACTIVE",
        "hops": [{"switch": h.switch, "out_port": h.out_port} for h in scenario.hops],
        "safety_interface": iface,
        "tc_show": active["tc_show"],
        "flow_count": len(installed),
        "ground_truth": scenario.ground_truth(),
    }


def reset_f4(
    scenario: LoopScenario,
    *,
    force: bool = False,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    require_root()
    iface = scenario.safety_iface
    try:
        validate_iface_bridge(iface, scenario.safety_shape_switch)
    except FaultError:
        pass
    removed = remove_experiment_flows()
    tc_del_root(iface)
    clear_state()
    remaining = list_experiment_flows()
    if remaining:
        raise FaultError(
            "RESET_INCOMPLETE",
            "experiment flows remain after F4 reset",
            {"remaining": len(remaining)},
        )
    return {
        "status": "IDLE",
        "scenario_id": "F4",
        "removed": removed,
        "safety_interface": iface,
        "tc_show": tc_show(iface).strip(),
        "message": "removed F4 loop flows and safety qdisc",
    }
