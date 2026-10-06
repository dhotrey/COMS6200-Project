"""F3 ACL/policy error: high-priority selective DROP for h1→h5 (main6s8h: s3; ring5s5h: s4)."""

from __future__ import annotations

from typing import Any

from faults.common import FaultError, require_root
from faults.onos_experiment import (
    eth_src_dst_criteria,
    experiment_flow_json,
    install_experiment_flows,
    list_experiment_flows,
    remove_experiment_flows,
)
from faults.scenarios import AclScenario, host_mac
from faults.state import clear_state, utc_now, write_state


def inject_f3(scenario: AclScenario) -> dict[str, Any]:
    require_root()
    if list_experiment_flows():
        raise FaultError(
            "EXPERIMENT_FLOWS_PRESENT",
            "org.coms6200.experiment flows already present; reset first",
        )
    flow = experiment_flow_json(
        switch=scenario.switch,
        priority=scenario.priority,
        criteria=eth_src_dst_criteria(host_mac(scenario.src_host), host_mac(scenario.dst_host)),
        outputs=None,  # empty treatment => drop
    )
    pending = {
        "status": "PENDING",
        "scenario_id": "F3",
        "injected_at": utc_now(),
        "switch": scenario.switch,
        "ground_truth": scenario.ground_truth(),
        "note": "evaluator/operator only; never expose to telemetry or LLM tools",
    }
    write_state(pending)
    try:
        installed = install_experiment_flows([flow])
    except Exception:
        try:
            remove_experiment_flows()
        except FaultError:
            pass
        clear_state()
        raise
    active = dict(pending)
    active["status"] = "ACTIVE"
    active["verified_at"] = utc_now()
    active["flow_ids"] = [
        {"deviceId": f.get("deviceId"), "flowId": f.get("id")} for f in installed
    ]
    write_state(active)
    return {
        "scenario_id": "F3",
        "status": "ACTIVE",
        "switch": scenario.switch,
        "priority": scenario.priority,
        "app_id": scenario.app_id,
        "flow_count": len(installed),
        "ground_truth": scenario.ground_truth(),
    }


def reset_f3(
    scenario: AclScenario,
    *,
    force: bool = False,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    require_root()
    removed = remove_experiment_flows()
    clear_state()
    remaining = list_experiment_flows()
    if remaining:
        raise FaultError(
            "RESET_INCOMPLETE",
            "experiment flows remain after F3 reset",
            {"remaining": len(remaining)},
        )
    return {
        "status": "IDLE",
        "scenario_id": "F3",
        "removed": removed,
        "message": "removed F3 experiment DROP rule",
    }
