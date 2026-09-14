"""F5 missing baseline unicast rule (s3 destination h5)."""

from __future__ import annotations

import time
from typing import Any

from forwarding.baseline_forwarding import (
    APP_NAME,
    BASELINE_UNICAST_PRIORITY,
    FlowSpec,
    OnosClient,
    credentials_from_env,
    flow_matches_spec,
    install_flows,
    list_baseline_flows,
)
from faults.common import FaultError, require_root
from faults.scenarios import F5, host_mac
from faults.state import clear_state, utc_now, write_state
from topologies.spec import DEVICE_IDS


def _client() -> OnosClient:
    user, password, url = credentials_from_env()
    return OnosClient(url, user, password)


def _target_spec() -> FlowSpec:
    scenario = F5
    return FlowSpec(
        switch=scenario.switch,
        priority=BASELINE_UNICAST_PRIORITY,
        selector=(("ETH_DST", host_mac(scenario.dst_host)),),
        outputs=(1,),  # s3 → s1 for remote destinations including h5
        kind="unicast",
    )


def resolve_unique_baseline_flow(client: OnosClient | None = None) -> dict[str, Any]:
    client = client or _client()
    spec = _target_spec()
    matches = [flow for flow in list_baseline_flows(client) if flow_matches_spec(flow, spec)]
    if len(matches) == 0:
        raise FaultError(
            "FLOW_NOT_FOUND",
            "expected baseline unicast rule for destination h5 on s3 not found",
        )
    if len(matches) > 1:
        raise FaultError(
            "FLOW_AMBIGUOUS",
            "multiple baseline flows match s3 destination h5; refusing to mutate",
            {"count": len(matches)},
        )
    flow = matches[0]
    if str(flow.get("appId", "")) != APP_NAME:
        raise FaultError("FLOW_NOT_BASELINE", "matched flow is not baseline app")
    if int(flow.get("priority", -1)) != BASELINE_UNICAST_PRIORITY:
        raise FaultError("FLOW_PRIORITY_MISMATCH", "matched flow priority unexpected")
    if flow.get("deviceId") != DEVICE_IDS[F5.switch]:
        raise FaultError("FLOW_DEVICE_MISMATCH", "matched flow device unexpected")
    return flow


def inject_f5() -> dict[str, Any]:
    require_root()
    client = _client()
    before = list_baseline_flows(client)
    if len(before) != 56:
        raise FaultError(
            "BASELINE_COUNT",
            f"expected 56 baseline flows before F5, found {len(before)}",
        )
    target = resolve_unique_baseline_flow(client)
    flow_id = target.get("id")
    device_id = target.get("deviceId")
    if flow_id is None or not device_id:
        raise FaultError("FLOW_ID_MISSING", "resolved flow lacks deviceId/id")

    pending = {
        "status": "PENDING",
        "scenario_id": "F5",
        "injected_at": utc_now(),
        "removed_flow": {"deviceId": device_id, "flowId": flow_id},
        "ground_truth": F5.ground_truth(),
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
            still = [f for f in remaining if flow_matches_spec(f, _target_spec())]
            if not still and len(remaining) == 55:
                break
            time.sleep(0.3)
        else:
            raise FaultError(
                "FLOW_DELETE_TIMEOUT",
                "baseline h5 rule still present or count unexpected after delete",
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
    active["baseline_count"] = 55
    write_state(active)
    return {
        "scenario_id": "F5",
        "status": "ACTIVE",
        "removed_flow": active["removed_flow"],
        "baseline_count": 55,
        "ground_truth": F5.ground_truth(),
    }


def reset_f5(*, force: bool = False, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    require_root()
    client = _client()
    spec = _target_spec()
    ours = list_baseline_flows(client)
    matches = [flow for flow in ours if flow_matches_spec(flow, spec)]

    if len(matches) == 1 and len(ours) == 56:
        clear_state()
        return {
            "status": "IDLE",
            "scenario_id": "F5",
            "baseline_count": 56,
            "message": "baseline already complete; cleared fault state",
        }

    if len(matches) == 0:
        # Prefer restoring only the missing rule (avoids disrupting the other 55).
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
            if len(matches) == 1 and added == 56:
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
            if len(ours) != 56:
                raise FaultError(
                    "RESET_INCOMPLETE",
                    f"expected 56 baseline flows after F5 reset, found {len(ours)}",
                )
            resolve_unique_baseline_flow(client)
            clear_state()
            return {
                "status": "IDLE",
                "scenario_id": "F5",
                "baseline_count": 56,
                "message": "restored via full baseline install_flows fallback",
            }

    ours = list_baseline_flows(client)
    if len(ours) != 56:
        raise FaultError(
            "RESET_INCOMPLETE",
            f"expected 56 baseline flows after F5 reset, found {len(ours)}",
        )
    resolve_unique_baseline_flow(client)
    clear_state()
    return {
        "status": "IDLE",
        "scenario_id": "F5",
        "baseline_count": 56,
        "message": "restored missing s3→h5 baseline unicast rule",
    }
