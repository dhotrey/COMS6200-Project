"""Operator catalogue inject/reset for the harness UI.

Not an LLM tool. Do not add these functions to telemetry schemas or chat
history. The assistant must not receive scenario ids or ground truth.
"""

from __future__ import annotations

import os
from typing import Any

from faults.injector import inject, reset, status
from faults.scenarios import RUNNABLE


def public_status() -> dict[str, Any]:
    result = status()
    error = result.get("error") or {}
    data = result.get("data") or {}
    state = data.get("state") if isinstance(data.get("state"), dict) else {}
    active = bool(data.get("active"))
    scenario_id = state.get("scenario_id") if active else None
    if scenario_id is not None and scenario_id not in RUNNABLE:
        scenario_id = None
    return {
        "ok": bool(result.get("ok")),
        "active": active,
        "scenario_id": scenario_id,
        "runnable": sorted(RUNNABLE),
        "error": error.get("message"),
    }


def load_scenario(scenario_id: str) -> dict[str, Any]:
    if os.geteuid() != 0:
        return {
            "ok": False,
            "active": False,
            "scenario_id": None,
            "runnable": sorted(RUNNABLE),
            "error": "Fault injection needs root. Restart with python -m agent so it can re-exec sudo.",
        }
    reset()
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
