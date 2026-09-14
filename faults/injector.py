"""Operator fault injector dispatcher for Fault Catalogue v1 (F1–F5).

Evaluator/operator only. Uses fixed argv subprocesses with the shell disabled.
Does not invoke sudo internally. Not an LLM tool.
"""

from __future__ import annotations

from typing import Any, Callable

from faults import envelope
from faults.catalogue import FAULT_CATALOGUE_VERSION
from faults.common import FaultError
from faults import f1_link, f2_congestion, f3_acl, f4_loop, f5_missing
from faults.scenarios import RUNNABLE, require_scenario
from faults.state import StateError, active_state, clear_state, read_state


_INJECTORS: dict[str, Callable[[], dict[str, Any]]] = {
    "F1": f1_link.inject_f1,
    "F2": f2_congestion.inject_f2,
    "F3": f3_acl.inject_f3,
    "F4": f4_loop.inject_f4,
    "F5": f5_missing.inject_f5,
}

_RESETTERS: dict[str, Callable[..., dict[str, Any]]] = {
    "F1": f1_link.reset_f1,
    "F2": f2_congestion.reset_f2,
    "F3": f3_acl.reset_f3,
    "F4": f4_loop.reset_f4,
    "F5": f5_missing.reset_f5,
}


def inject(scenario_id: object = "F1") -> dict[str, Any]:
    action = "inject"
    try:
        scenario = require_scenario(scenario_id)
        existing = active_state()
        if existing is not None:
            raise FaultError(
                "FAULT_ALREADY_ACTIVE",
                f"active fault {existing.get('scenario_id')} already recorded; reset first",
            )
        handler = _INJECTORS[scenario.scenario_id]
        data = handler()
        data["catalogue_version"] = FAULT_CATALOGUE_VERSION
        return envelope.ok(action, data)
    except FaultError as exc:
        return envelope.error(action, exc.code, exc.message, exc.details)
    except StateError as exc:
        return envelope.error(action, exc.code, exc.message)
    except ValueError as exc:
        return envelope.error(action, "INVALID_SCENARIO", str(exc))
    except Exception as exc:  # noqa: BLE001
        return envelope.error(action, "INTERNAL_ERROR", str(exc)[:300])


def status() -> dict[str, Any]:
    action = "status"
    try:
        payload = read_state()
        if payload is None:
            observed = f1_link.observe_f1_ifaces()
            return envelope.ok(
                action,
                {
                    "active": False,
                    "catalogue_version": FAULT_CATALOGUE_VERSION,
                    "runnable": sorted(RUNNABLE),
                    "state_file": None,
                    "observed_f1_interfaces": observed,
                },
            )
        return envelope.ok(
            action,
            {
                "active": payload.get("status") == "ACTIVE",
                "catalogue_version": FAULT_CATALOGUE_VERSION,
                "state": payload,
            },
        )
    except FaultError as exc:
        return envelope.error(action, exc.code, exc.message, exc.details)
    except StateError as exc:
        return envelope.error(action, exc.code, exc.message)


def reset(
    force_f1: bool = False,
    force_scenario: str | None = None,
) -> dict[str, Any]:
    """Reset active fault, or recover a named scenario when state is missing."""
    action = "reset"
    try:
        payload = read_state()
        if payload is not None:
            scenario_id = str(payload.get("scenario_id") or "")
            if scenario_id not in _RESETTERS:
                raise FaultError(
                    "STATE_CORRUPT",
                    f"unknown scenario_id in state: {scenario_id}",
                )
            data = _RESETTERS[scenario_id](force=False, payload=payload)
            data["catalogue_version"] = FAULT_CATALOGUE_VERSION
            return envelope.ok(action, data)

        # No state file: optional forced recovery for a known scenario.
        if force_f1:
            force_scenario = "F1"
        if force_scenario:
            if force_scenario not in _RESETTERS:
                raise FaultError("INVALID_SCENARIO", f"unknown recovery scenario {force_scenario}")
            data = _RESETTERS[force_scenario](force=True, payload=None)
            data["catalogue_version"] = FAULT_CATALOGUE_VERSION
            return envelope.ok(action, data)

        return envelope.ok(
            action,
            {
                "status": "IDLE",
                "catalogue_version": FAULT_CATALOGUE_VERSION,
                "message": "no active fault state",
            },
        )
    except FaultError as exc:
        return envelope.error(action, exc.code, exc.message, exc.details)
    except StateError as exc:
        return envelope.error(action, exc.code, exc.message)
    except ValueError as exc:
        return envelope.error(action, "INVALID_SCENARIO", str(exc))
    except Exception as exc:  # noqa: BLE001
        # Best-effort: do not leave callers without an envelope.
        try:
            clear_state()
        except Exception:
            pass
        return envelope.error(action, "INTERNAL_ERROR", str(exc)[:300])
