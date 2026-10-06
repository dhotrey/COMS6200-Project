"""F1 link failure (main6s8h: primary s3–s1; ring5s5h: s3–s4)."""

from __future__ import annotations

from typing import Any

from faults.common import (
    FaultError,
    iface_operstate,
    require_root,
    set_link,
    validate_iface_bridge,
)
from faults.scenarios import LinkFailureScenario
from faults.state import clear_state, utc_now, write_state


def validate_endpoints(scenario: LinkFailureScenario) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for endpoint in scenario.endpoints:
        row = validate_iface_bridge(endpoint.interface, endpoint.switch)
        rows.append(
            {
                "switch": endpoint.switch,
                "port": endpoint.port,
                "interface": endpoint.interface,
                "bridge": row["bridge"],
                "operstate": row["operstate"],
            }
        )
    return rows


def inject_f1(scenario: LinkFailureScenario) -> dict[str, Any]:
    require_root()
    rows = validate_endpoints(scenario)
    down = [row["interface"] for row in rows if row["operstate"] != "up"]
    if down:
        raise FaultError("LINK_NOT_UP", "F1 endpoints must be UP before injection", {"down": down})

    pending = {
        "status": "PENDING",
        "scenario_id": "F1",
        "injected_at": utc_now(),
        "interfaces": list(scenario.interfaces),
        "endpoints": [
            {"switch": e.switch, "port": e.port, "interface": e.interface}
            for e in scenario.endpoints
        ],
        "ground_truth": scenario.ground_truth(),
        "note": "evaluator/operator only; never expose to telemetry or LLM tools",
    }
    write_state(pending)

    mutated: list[str] = []
    try:
        for iface in scenario.interfaces:
            set_link(iface, up=False)
            mutated.append(iface)
        after = validate_endpoints(scenario)
        still_up = [row["interface"] for row in after if row["operstate"] == "up"]
        if still_up:
            raise FaultError("LINK_STILL_UP", "F1 endpoints did not go down", {"still_up": still_up})
    except FaultError:
        for iface in reversed(mutated):
            try:
                set_link(iface, up=True)
            except FaultError:
                pass
        clear_state()
        raise

    active = dict(pending)
    active["status"] = "ACTIVE"
    active["verified_at"] = utc_now()
    active["endpoint_state"] = after
    write_state(active)
    return {
        "scenario_id": "F1",
        "status": "ACTIVE",
        "interfaces": list(scenario.interfaces),
        "endpoint_state": after,
        "ground_truth": scenario.ground_truth(),
    }


def reset_f1(
    scenario: LinkFailureScenario,
    *,
    force: bool = False,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    require_root()
    if payload is None:
        rows = validate_endpoints(scenario)
        down = [row for row in rows if row["operstate"] != "up"]
        if not down and not force:
            return {
                "status": "IDLE",
                "message": "no active fault state; F1 endpoints already UP",
                "endpoint_state": rows,
            }
        for iface in scenario.interfaces:
            set_link(iface, up=True)
        after = validate_endpoints(scenario)
        return {
            "status": "RECOVERED",
            "message": "restored canonical F1 endpoints without state file",
            "interfaces": list(scenario.interfaces),
            "endpoint_state": after,
        }

    recorded = payload.get("interfaces") or list(scenario.interfaces)
    if list(recorded) != list(scenario.interfaces):
        raise FaultError(
            "STATE_MISMATCH",
            "recorded interfaces do not match canonical F1 resources",
            {"recorded": recorded, "expected": list(scenario.interfaces)},
        )
    validate_endpoints(scenario)
    for iface in scenario.interfaces:
        set_link(iface, up=True)
    after = validate_endpoints(scenario)
    still_down = [row["interface"] for row in after if row["operstate"] != "up"]
    if still_down:
        raise FaultError(
            "RESET_INCOMPLETE",
            "one or more F1 endpoints remain down after reset",
            {"still_down": still_down},
        )
    clear_state()
    return {
        "status": "IDLE",
        "scenario_id": "F1",
        "interfaces": list(scenario.interfaces),
        "endpoint_state": after,
    }


def observe_f1_ifaces(scenario: LinkFailureScenario) -> dict[str, str]:
    try:
        return {iface: iface_operstate(iface) for iface in scenario.interfaces}
    except FaultError:
        return {}
