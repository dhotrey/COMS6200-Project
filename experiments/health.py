"""Runner healthy gate. These checks are not diagnostic tool calls."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import urllib.request
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
RECOVERY_COMMANDS = (
    ["./scripts/testbed.sh", "stop"],
    ["./scripts/testbed.sh", "start"],
)


def ensure_healthy(
    probe: Callable[[], tuple[bool, str]] | None = None,
    recover: Callable[[], None] | None = None,
) -> tuple[bool, str]:
    """Check once. On failure, run normal stop then start, then check again."""
    probe = probe or live_probe
    ok, detail = probe()
    if ok:
        return True, detail
    if recover is None:
        _recover_live()
    else:
        recover()
    return probe()


def live_probe() -> tuple[bool, str]:
    reasons: list[str] = []
    try:
        devices, links, flows = _onos_snapshot()
    except Exception as exc:  # noqa: BLE001 — gate reports the class, not credentials
        return False, f"onos:{type(exc).__name__}"
    of13 = [
        item for item in devices
        if item.get("available")
        and str(item.get("id", "")).startswith("of:000000000000000")
        and (item.get("annotations") or {}).get("protocol") == "OF_13"
    ]
    expected = {f"of:000000000000000{i}" for i in range(1, 7)}
    if {item.get("id") for item in of13} != expected:
        reasons.append(f"devices:{len(of13)}")
    if len(links) != 20:
        reasons.append(f"links:{len(links)}")
    baseline = [
        flow for flow in flows
        if flow.get("appId") == "org.coms6200.baseline" and flow.get("state") == "ADDED"
    ]
    experiment = [flow for flow in flows if flow.get("appId") == "org.coms6200.experiment"]
    if len(baseline) != 56:
        reasons.append(f"baseline_flows:{len(baseline)}")
    if experiment:
        reasons.append(f"experiment_flows:{len(experiment)}")
    active, fault_error = _fault_active()
    if fault_error:
        reasons.append(fault_error)
    elif active:
        reasons.append("fault_active")
    if _iperf_running():
        reasons.append("iperf")
    if _tbf_present():
        reasons.append("tbf")
    if not reasons and not _reference_ping():
        reasons.append("ping_h1_h5")
    if reasons:
        return False, ",".join(reasons)
    return True, "healthy"


def _onos_snapshot() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    user = os.environ.get("ONOS_USER", "onos")
    password = os.environ.get("ONOS_PASSWORD", "rocks")
    api = os.environ.get("ONOS_API", "http://127.0.0.1:8181/onos/v1")
    token = base64.b64encode(f"{user}:{password}".encode()).decode()

    def get(path: str) -> dict[str, Any]:
        req = urllib.request.Request(api + path)
        req.add_header("Authorization", f"Basic {token}")
        with urllib.request.urlopen(req, timeout=5) as response:
            payload = json.load(response)
        if not isinstance(payload, dict):
            raise RuntimeError("onos payload")
        return payload

    devices = get("/devices").get("devices") or []
    links = get("/links").get("links") or []
    flows = get("/flows").get("flows") or []
    return devices, links, flows


def _fault_active() -> tuple[bool, str | None]:
    from faults.injector import status

    payload = status()
    if not payload.get("ok"):
        return False, "fault_status"
    data = payload.get("data") or {}
    return bool(data.get("active")), None


def _iperf_running() -> bool:
    completed = subprocess.run(["pgrep", "-x", "iperf3"], check=False, capture_output=True)
    return completed.returncode == 0


def _tbf_present() -> bool:
    completed = subprocess.run(["tc", "qdisc", "show"], check=False, capture_output=True, text=True)
    return "tbf" in (completed.stdout or "").lower()


def _reference_ping() -> bool:
    from telemetry.gateway import TelemetryGateway

    result = TelemetryGateway().ping("h1", "h5", count=1)
    data = result.get("data") or {}
    return bool(result.get("ok") and data.get("received"))


def _recover_live() -> None:
    for command in RECOVERY_COMMANDS:
        subprocess.run(command, cwd=ROOT, check=False, timeout=180)
