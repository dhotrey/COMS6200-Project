"""Operator catalogue inject/reset for the harness UI.

Not an LLM tool. Do not add these functions to telemetry schemas or chat
history. The assistant must not receive scenario ids or ground truth.
"""

from __future__ import annotations

import os
import json
import subprocess
import sys
from typing import Any

from topologies import active
from . import topology_control

RUNNABLE = frozenset({"F1", "F2", "F3", "F4", "F5"})


def _fault_command(command: str, scenario: str | None = None) -> dict[str, Any]:
    # A fresh CLI process imports the selected catalogue and forwarding tables.
    argv = [sys.executable, "-m", "faults.cli", command]
    if scenario is not None:
        if scenario not in RUNNABLE:
            raise ValueError("scenario must be F1–F5")
        argv += ["--scenario", scenario]
    try:
        result = subprocess.run(
            argv, cwd=topology_control.ROOT, env=topology_control.environment(),
            capture_output=True, text=True, timeout=90, check=False,
        )
        payload = json.loads(result.stdout)
        if not isinstance(payload, dict) or not isinstance(payload.get("ok"), bool):
            raise ValueError("invalid fault response")
        return payload
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {"ok": False, "error": {"message": "Fault operation failed; check the testbed."}}


def inject(scenario: str) -> dict[str, Any]:
    return _fault_command("inject", scenario)


def reset() -> dict[str, Any]:
    return _fault_command("reset")


def status() -> dict[str, Any]:
    return _fault_command("status")


def public_status() -> dict[str, Any]:
    result = status()
    error = result.get("error") or {}
    data = result.get("data") or {}
    state = data.get("state") if isinstance(data.get("state"), dict) else {}
    is_active = bool(data.get("active"))
    scenario_id = state.get("scenario_id") if is_active else None
    if scenario_id is not None and scenario_id not in RUNNABLE:
        scenario_id = None
    return {
        "ok": bool(result.get("ok")),
        "active": is_active,
        "scenario_id": scenario_id,
        "runnable": sorted(RUNNABLE),
        "error": error.get("message"),
        "topology": active.TOPOLOGY,
        "topologies": list(topology_control.TOPOLOGIES),
        "network_error": topology_control.error,
        "running": topology_control.running_topology() == active.TOPOLOGY,
    }


def load_scenario(scenario_id: str, topology: str | None = None) -> dict[str, Any]:
    if os.geteuid() != 0:
        return {
            "ok": False,
            "active": False,
            "scenario_id": None,
            "runnable": sorted(RUNNABLE),
            "error": "Fault injection needs root. Restart with python -m agent so it can re-exec sudo.",
        }
    if topology is not None:
        topology_control.load_topology(topology)
    if topology_control.error:
        raise RuntimeError(topology_control.error)
    result = reset()
    if not result.get("ok"):
        status_now = public_status()
        status_now["ok"] = False
        status_now["error"] = (result.get("error") or {}).get("message") or "reset failed"
        return status_now
    result = inject(scenario_id)
    if not result.get("ok"):
        error = (result.get("error") or {}).get("message") or "inject failed"
        status_now = public_status()
        status_now["ok"] = False
        status_now["error"] = error
        return status_now
    return public_status()


def reset_scenario() -> dict[str, Any]:
    if os.geteuid() != 0:
        return {
            "ok": False,
            "active": False,
            "scenario_id": None,
            "runnable": sorted(RUNNABLE),
            "error": "Fault reset needs root. Restart with python -m agent so it can re-exec sudo.",
        }
    result = reset()
    if not result.get("ok"):
        error = (result.get("error") or {}).get("message") or "reset failed"
        status_now = public_status()
        status_now["ok"] = False
        status_now["error"] = error
        return status_now
    return public_status()
