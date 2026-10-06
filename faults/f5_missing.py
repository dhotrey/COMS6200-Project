"""F5 missing baseline unicast rule (main6s8h: s3 dst h5; ring5s5h: s2 dst h5).

Baseline counts and the target rule come from the selected topology's
forwarding plan (main6s8h: 56 flows, s3 port 1).
"""

from __future__ import annotations

import time
from typing import Any

from forwarding.baseline_forwarding import (
    APP_NAME,
    BASELINE_UNICAST_PRIORITY,
    DEVICE_IDS,
    UNICAST_EGRESS,
    FlowSpec,
    OnosClient,
    credentials_from_env,
    expected_flow_count,
    flow_matches_spec,
    install_flows,
    list_baseline_flows,
)
from faults.common import FaultError, require_root
from faults.scenarios import MissingFlowScenario, host_mac
from faults.state import clear_state, utc_now, write_state


def _client() -> OnosClient:
    user, password, url = credentials_from_env()
    return OnosClient(url, user, password)


def _target_spec(scenario: MissingFlowScenario) -> FlowSpec:
    return FlowSpec(
        switch=scenario.switch,
        priority=BASELINE_UNICAST_PRIORITY,
        selector=(("ETH_DST", host_mac(scenario.dst_host)),),
        outputs=(UNICAST_EGRESS[scenario.switch][scenario.dst_host],),  # main6s8h: s3 → s1
        kind="unicast",
    )


def resolve_unique_baseline_flow(
    scenario: MissingFlowScenario, client: OnosClient | None = None
) -> dict[str, Any]:
    client = client or _client()
    spec = _target_spec(scenario)
    matches = [flow for flow in list_baseline_flows(client) if flow_matches_spec(flow, spec)]
    if len(matches) == 0:
        raise FaultError(
            "FLOW_NOT_FOUND",
            f"expected baseline unicast rule for destination {scenario.dst_host} on {scenario.switch} not found",
        )
    if len(matches) > 1:
        raise FaultError(
            "FLOW_AMBIGUOUS",
            f"multiple baseline flows match {scenario.switch} destination {scenario.dst_host}; refusing to mutate",
            {"count": len(matches)},
        )
    flow = matches[0]
    if str(flow.get("appId", "")) != APP_NAME:
        raise FaultError("FLOW_NOT_BASELINE", "matched flow is not baseline app")
    if int(flow.get("priority", -1)) != BASELINE_UNICAST_PRIORITY:
        raise FaultError("FLOW_PRIORITY_MISMATCH", "matched flow priority unexpected")
    if flow.get("deviceId") != DEVICE_IDS[scenario.switch]:
        raise FaultError("FLOW_DEVICE_MISMATCH", "matched flow device unexpected")
    return flow


def inject_f5(scenario: MissingFlowScenario) -> dict[str, Any]:
    require_root()
    client = _client()
    expected = expected_flow_count()
    before = list_baseline_flows(client)
    if len(before) != expected:
        raise FaultError(
            "BASELINE_COUNT",
            f"expected {expected} baseline flows before F5, found {len(before)}",
        )
    target = resolve_unique_baseline_flow(scenario, client)
    flow_id = target.get("id")
    device_id = target.get("deviceId")
    if flow_id is None or not device_id:
        raise FaultError("FLOW_ID_MISSING", "resolved flow lacks deviceId/id")

    pending = {
        "status": "PENDING",
        "scenario_id": "F5",
        "injected_at": utc_now(),
        "removed_flow": {"deviceId": device_id, "flowId": flow_id},
        "ground_truth": scenario.ground_truth(),
        "note": "evaluator/operator only; never expose to telemetry or LLM tools",
    }
    write_state(pending)
    try:
        client.delete(
            "flows",
            body={"flows": [{"deviceId": device_id, "flowId": flow_id}]},
        )
        deadline = time.time() + 10
        while time.time() < deadline:
            remaining = list_baseline_flows(client)
            still = [f for f in remaining if flow_matches_spec(f, _target_spec(scenario))]
            if not still and len(remaining) == expected - 1:
                break
            time.sleep(0.3)
        else:
            raise FaultError(
                "FLOW_DELETE_TIMEOUT",
                f"baseline {scenario.dst_host} rule still present or count unexpected after delete",
                {"count": len(list_baseline_flows(client))},
            )
    except Exception:
        try:
            import contextlib
            import io

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                install_flows(client, timeout_s=45.0)
        except Exception:
            pass
        clear_state()
        raise

    active = dict(pending)
    active["status"] = "ACTIVE"
    active["verified_at"] = utc_now()
    active["baseline_count"] = expected - 1
    write_state(active)
    return {
        "scenario_id": "F5",
        "status": "ACTIVE",
        "removed_flow": active["removed_flow"],
        "baseline_count": expected - 1,
        "ground_truth": scenario.ground_truth(),
    }


def reset_f5(
    scenario: MissingFlowScenario,
    *,
    force: bool = False,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    require_root()
    client = _client()
    expected = expected_flow_count()
    spec = _target_spec(scenario)
    ours = list_baseline_flows(client)
    matches = [flow for flow in ours if flow_matches_spec(flow, spec)]

    if len(matches) == 1 and len(ours) == expected:
        clear_state()
        return {
            "status": "IDLE",
            "scenario_id": "F5",
            "baseline_count": expected,
            "message": "baseline already complete; cleared fault state",
        }

    if len(matches) == 0:
        # Prefer restoring only the missing rule (avoids disrupting the others).
        from forwarding.baseline_forwarding import spec_to_onos_json

        client.post(
            "flows",
            {"flows": [spec_to_onos_json(spec)]},
            query={"appId": APP_NAME},
        )
        deadline = time.time() + 30
        while time.time() < deadline:
            ours = list_baseline_flows(client)
            matches = [flow for flow in ours if flow_matches_spec(flow, spec)]
            added = sum(1 for f in ours if str(f.get("state")) == "ADDED")
            if len(matches) == 1 and added == expected:
                break
            time.sleep(0.4)
        else:
            # Fallback: full deterministic reinstall with quiet stdout.
            import contextlib
            import io

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                install_flows(client, timeout_s=45.0)
            ours = list_baseline_flows(client)
            if len(ours) != expected:
                raise FaultError(
                    "RESET_INCOMPLETE",
                    f"expected {expected} baseline flows after F5 reset, found {len(ours)}",
                )
            resolve_unique_baseline_flow(scenario, client)
            clear_state()
            return {
                "status": "IDLE",
                "scenario_id": "F5",
                "baseline_count": expected,
                "message": "restored via full baseline install_flows fallback",
            }

    ours = list_baseline_flows(client)
    if len(ours) != expected:
        raise FaultError(
            "RESET_INCOMPLETE",
            f"expected {expected} baseline flows after F5 reset, found {len(ours)}",
        )
    resolve_unique_baseline_flow(scenario, client)
    clear_state()
    return {
        "status": "IDLE",
        "scenario_id": "F5",
        "baseline_count": expected,
        "message": f"restored missing {scenario.switch}→{scenario.dst_host} baseline unicast rule",
    }
