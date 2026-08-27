"""ONOS experiment-flow helpers for F3/F4 (neutral app identity).

Operator/evaluator only. Does not leak fault labels beyond appId
org.coms6200.experiment (neutral; not F3/F4/acl/fault).
"""

from __future__ import annotations

import time
from typing import Any

from forwarding.baseline_forwarding import OnosClient, credentials_from_env, list_all_flows
from faults.common import FaultError
from faults.scenarios import EXPERIMENT_APP_ID
from topologies.spec import DEVICE_IDS


def onos_client() -> OnosClient:
    user, password, url = credentials_from_env()
    return OnosClient(url, user, password)


def experiment_flow_json(
    *,
    switch: str,
    priority: int,
    criteria: list[dict[str, str]],
    outputs: list[int] | None,
) -> dict[str, Any]:
    if outputs is None:
        treatment: dict[str, Any] = {"instructions": []}
    else:
        treatment = {
            "instructions": [{"type": "OUTPUT", "port": str(port)} for port in outputs]
        }
    return {
        "priority": priority,
        "timeout": 0,
        "isPermanent": True,
        "deviceId": DEVICE_IDS[switch],
        "tableId": 0,
        "appId": EXPERIMENT_APP_ID,
        "selector": {"criteria": criteria},
        "treatment": treatment,
    }


def eth_src_dst_criteria(eth_src: str, eth_dst: str) -> list[dict[str, str]]:
    return [
        {"type": "ETH_SRC", "mac": eth_src},
        {"type": "ETH_DST", "mac": eth_dst},
    ]


def list_experiment_flows(client: OnosClient | None = None) -> list[dict[str, Any]]:
    client = client or onos_client()
    return [
        flow
        for flow in list_all_flows(client)
        if str(flow.get("appId", "")) == EXPERIMENT_APP_ID
    ]


def install_experiment_flows(flows: list[dict[str, Any]], timeout_s: float = 15.0) -> list[dict[str, Any]]:
    if not flows:
        raise FaultError("INTERNAL_ERROR", "no experiment flows to install")
    client = onos_client()
    client.post("flows", {"flows": flows}, query={"appId": EXPERIMENT_APP_ID})
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        present = list_experiment_flows(client)
        if len(present) >= len(flows) and all(str(f.get("state")) == "ADDED" for f in present):
            return present
        time.sleep(0.4)
    raise FaultError(
        "FLOW_INSTALL_TIMEOUT",
        "experiment flows did not reach ADDED",
        {"count": len(list_experiment_flows(client))},
    )


def remove_experiment_flows(timeout_s: float = 15.0) -> int:
    client = onos_client()
    flows = list_experiment_flows(client)
    if not flows:
        return 0
    body = {
        "flows": [
            {"deviceId": flow["deviceId"], "flowId": flow["id"]}
            for flow in flows
            if flow.get("deviceId") and flow.get("id") is not None
        ]
    }
    if body["flows"]:
        client.delete("flows", body=body)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        remaining = list_experiment_flows(client)
        if not remaining:
            return len(flows)
        time.sleep(0.3)
    raise FaultError(
        "FLOW_REMOVE_TIMEOUT",
        "experiment flows remain after delete",
        {"remaining": len(list_experiment_flows(client))},
    )
