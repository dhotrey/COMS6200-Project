"""Operator fault injector dispatcher for the selected catalogue (F1–F5).

main6s8h runs the frozen Fault Catalogue v1; ring5s5h runs its own catalogue
(faults/registry.py). Handlers are shared and receive the selected scenario.

Evaluator/operator only. Uses fixed argv subprocesses with the shell disabled.
Does not invoke sudo internally. Not an LLM tool.
"""

from __future__ import annotations

import os
import re
from typing import Any, Callable

from faults import envelope
from faults.common import FaultError, require_root
from faults import f1_link, f2_congestion, f3_acl, f4_loop, f5_missing
from faults.registry import ACTIVE, Catalogue
from faults.state import StateError, active_state, clear_state, read_state
from topologies.active import HOST_ATTACHMENTS, INTER_SWITCH_LINKS, TOPOLOGY

SYS_CLASS_NET = "/sys/class/net"
_SWITCH_IFACE = re.compile(r"s\d+-eth\d+")

_INJECTORS: dict[str, Callable[..., dict[str, Any]]] = {
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


def _catalogue() -> Catalogue:
    if ACTIVE is None:
        raise FaultError(
            "TOPOLOGY_UNSUPPORTED",
            f"no fault catalogue for COMS6200_TOPOLOGY={TOPOLOGY}",
        )
    return ACTIVE


def _switch_interfaces() -> set[str]:
    """Switch-side Mininet ports (sN-ethP) in the root network namespace."""
    try:
        names = os.listdir(SYS_CLASS_NET)
    except OSError:
        return set()
    return {name for name in names if _SWITCH_IFACE.fullmatch(name)}


def expected_switch_interfaces() -> set[str]:
    ends = [(link.a, link.a_port) for link in INTER_SWITCH_LINKS]
    ends += [(link.b, link.b_port) for link in INTER_SWITCH_LINKS]
    ends += [(item.switch, item.switch_port) for item in HOST_ATTACHMENTS]
    return {f"{switch}-eth{port}" for switch, port in ends}


def _require_selected_datapath() -> None:
    """Refuse to mutate unless the running switch ports are exactly the selected topology's.

    Interface names overlap between topologies (every ring5s5h port name also
    exists in main6s8h), and sudo drops COMS6200_TOPOLOGY by default, so the
    setting alone cannot prove which network is running.
    """
    actual = _switch_interfaces()
    expected = expected_switch_interfaces()
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    if missing or unexpected:
        raise FaultError(
            "TOPOLOGY_MISMATCH",
            f"running switch ports do not match {TOPOLOGY} "
            f"(missing {len(missing)}, unexpected {len(unexpected)}); "
            "check COMS6200_TOPOLOGY and sudo --preserve-env",
            {"missing": missing, "unexpected": unexpected},
        )


def _require_state_catalogue(payload: dict[str, Any], catalogue: Catalogue) -> None:
    """A fault must be reset with the catalogue that injected it."""
    recorded = (payload.get("ground_truth") or {}).get("catalogue_version")
    if recorded is not None and recorded != catalogue.version:
        raise FaultError(
            "STATE_CATALOGUE_MISMATCH",
            f"active fault was injected from catalogue {recorded}; "
            f"COMS6200_TOPOLOGY={TOPOLOGY} selects {catalogue.version}",
        )


def inject(scenario_id: object = "F1") -> dict[str, Any]:
    action = "inject"
    try:
        catalogue = _catalogue()
        scenario = catalogue.require_scenario(scenario_id)
        existing = active_state()
        if existing is not None:
            raise FaultError(
                "FAULT_ALREADY_ACTIVE",
                f"active fault {existing.get('scenario_id')} already recorded; reset first",
            )
        require_root()
        _require_selected_datapath()
        data = _INJECTORS[scenario.scenario_id](scenario)
        data["catalogue_version"] = catalogue.version
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
        catalogue = _catalogue()
        payload = read_state()
        if payload is None:
            observed = f1_link.observe_f1_ifaces(catalogue.scenarios["F1"])
            return envelope.ok(
                action,
                {
                    "active": False,
                    "topology": catalogue.topology,
                    "catalogue_version": catalogue.version,
                    "runnable": sorted(catalogue.runnable),
                    "state_file": None,
                    "observed_f1_interfaces": observed,
                },
            )
        return envelope.ok(
            action,
            {
                "active": payload.get("status") == "ACTIVE",
                "topology": catalogue.topology,
                "catalogue_version": catalogue.version,
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
        catalogue = _catalogue()
        payload = read_state()
        if payload is not None:
            _require_state_catalogue(payload, catalogue)
            scenario_id = str(payload.get("scenario_id") or "")
            if scenario_id not in _RESETTERS or scenario_id not in catalogue.scenarios:
                raise FaultError(
                    "STATE_CORRUPT",
                    f"unknown scenario_id in state: {scenario_id}",
                )
            data = _RESETTERS[scenario_id](
                catalogue.scenarios[scenario_id], force=False, payload=payload
            )
            data["catalogue_version"] = catalogue.version
            return envelope.ok(action, data)

        # No state file: optional forced recovery for a known scenario.
        if force_f1:
            force_scenario = "F1"
        if force_scenario:
            if force_scenario not in _RESETTERS or force_scenario not in catalogue.scenarios:
                raise FaultError("INVALID_SCENARIO", f"unknown recovery scenario {force_scenario}")
            data = _RESETTERS[force_scenario](
                catalogue.scenarios[force_scenario], force=True, payload=None
            )
            data["catalogue_version"] = catalogue.version
            return envelope.ok(action, data)

        return envelope.ok(
            action,
            {
                "status": "IDLE",
                "catalogue_version": catalogue.version,
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
