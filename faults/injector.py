"""Bounded F1 link-failure injector / reset.

Operator/evaluator only. Uses fixed argv subprocesses with the shell disabled.
Does not invoke sudo internally.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from faults import envelope
from faults.scenarios import LinkFailureScenario, require_scenario
from faults.state import StateError, active_state, clear_state, read_state, utc_now, write_state


class FaultError(RuntimeError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def require_root() -> None:
    if os.geteuid() != 0:
        raise FaultError(
            "ROOT_REQUIRED",
            "link-state mutation requires root; re-run as root or with sudo "
            "(this tool does not invoke sudo itself)",
        )


def _which(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise FaultError("COMMAND_UNAVAILABLE", f"{name} is not available on PATH")
    return path


def _run(argv: list[str], timeout_s: float = 5.0) -> subprocess.CompletedProcess[str]:
    if not argv or not all(isinstance(item, str) and item and "\x00" not in item for item in argv):
        raise FaultError("INTERNAL_ERROR", "invalid fixed argv")
    try:
        return subprocess.run(
            argv,
            check=False,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        raise FaultError("COMMAND_TIMEOUT", f"{argv[0]} timed out") from exc
    except FileNotFoundError as exc:
        raise FaultError("COMMAND_UNAVAILABLE", f"{argv[0]} is not available") from exc


def _iface_exists(name: str) -> bool:
    completed = _run([_which("ip"), "-o", "link", "show", "dev", name])
    return completed.returncode == 0


def _iface_operstate(name: str) -> str:
    path = Path("/sys/class/net") / name / "operstate"
    try:
        return path.read_text(encoding="utf-8").strip().lower()
    except FileNotFoundError:
        completed = _run([_which("ip"), "-o", "link", "show", "dev", name])
        if completed.returncode != 0:
            raise FaultError("INTERFACE_MISSING", f"interface {name} is missing")
        text = completed.stdout
        if "state UP" in text or ",UP," in text or " UP " in text:
            return "up"
        if "state DOWN" in text or " DOWN " in text:
            return "down"
        return "unknown"
    except OSError as exc:
        raise FaultError("INTERFACE_UNREADABLE", f"cannot read {path}") from exc


def _port_to_br(iface: str) -> str:
    completed = _run([_which("ovs-vsctl"), "port-to-br", iface])
    if completed.returncode != 0:
        raise FaultError(
            "INTERFACE_NOT_OVS",
            f"{iface} is not an OVS port on this host",
            {"stderr": (completed.stderr or "")[-200:]},
        )
    bridge = (completed.stdout or "").strip()
    if not bridge:
        raise FaultError("INTERFACE_NOT_OVS", f"ovs-vsctl returned empty bridge for {iface}")
    return bridge


def _set_link(iface: str, up: bool) -> None:
    action = "up" if up else "down"
    completed = _run([_which("ip"), "link", "set", "dev", iface, action])
    if completed.returncode != 0:
        raise FaultError(
            "LINK_MUTATION_FAILED",
            f"failed to bring {iface} {action}",
            {"stderr": (completed.stderr or "")[-300:]},
        )


def validate_endpoints(scenario: LinkFailureScenario) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for endpoint in scenario.endpoints:
        iface = endpoint.interface
        if not _iface_exists(iface):
            raise FaultError(
                "TOPOLOGY_NOT_RUNNING",
                f"expected interface {iface} is missing; is main6s8h running?",
            )
        bridge = _port_to_br(iface)
        if bridge != endpoint.switch:
            raise FaultError(
                "TOPOLOGY_MISMATCH",
                f"{iface} belongs to bridge {bridge}, expected {endpoint.switch}",
            )
        oper = _iface_operstate(iface)
        rows.append(
            {
                "switch": endpoint.switch,
                "port": endpoint.port,
                "interface": iface,
                "bridge": bridge,
                "operstate": oper,
            }
        )
    return rows


def _ensure_all_up(rows: list[dict[str, Any]]) -> None:
    down = [row["interface"] for row in rows if row["operstate"] != "up"]
    if down:
        raise FaultError(
            "LINK_NOT_UP",
            "F1 endpoints must be UP before injection",
            {"down": down},
        )


def _ensure_all_down(rows: list[dict[str, Any]]) -> None:
    up = [row["interface"] for row in rows if row["operstate"] == "up"]
    if up:
        raise FaultError(
            "LINK_STILL_UP",
            "F1 endpoints did not go down",
            {"still_up": up},
        )


def inject(scenario_id: object = "F1") -> dict[str, Any]:
    action = "inject"
    try:
        require_root()
        scenario = require_scenario(scenario_id)
        existing = active_state()
        if existing is not None:
            raise FaultError(
                "FAULT_ALREADY_ACTIVE",
                f"active fault {existing.get('scenario_id')} already recorded; reset first",
            )
        rows = validate_endpoints(scenario)
        _ensure_all_up(rows)

        # Persist intent before mutation so crash recovery can find resources.
        pending = {
            "status": "PENDING",
            "scenario_id": scenario.scenario_id,
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
                _set_link(iface, up=False)
                mutated.append(iface)
            after = validate_endpoints(scenario)
            _ensure_all_down(after)
        except FaultError:
            for iface in reversed(mutated):
                try:
                    _set_link(iface, up=True)
                except FaultError:
                    pass
            clear_state()
            raise

        active = dict(pending)
        active["status"] = "ACTIVE"
        active["verified_at"] = utc_now()
        active["endpoint_state"] = after
        write_state(active)
        return envelope.ok(
            action,
            {
                "scenario_id": scenario.scenario_id,
                "status": "ACTIVE",
                "interfaces": list(scenario.interfaces),
                "endpoint_state": after,
                "ground_truth": scenario.ground_truth(),
            },
        )
    except FaultError as exc:
        return envelope.error(action, exc.code, exc.message, exc.details)
    except StateError as exc:
        return envelope.error(action, exc.code, exc.message)
    except ValueError as exc:
        return envelope.error(action, "INVALID_SCENARIO", str(exc))


def status() -> dict[str, Any]:
    action = "status"
    try:
        payload = read_state()
        if payload is None:
            # Recoverable observation: report known F1 interface state if present.
            try:
                scenario = require_scenario("F1")
                rows = validate_endpoints(scenario)
                observed = {row["interface"]: row["operstate"] for row in rows}
            except FaultError:
                observed = {}
            return envelope.ok(
                action,
                {
                    "active": False,
                    "state_file": None,
                    "observed_f1_interfaces": observed,
                },
            )
        return envelope.ok(
            action,
            {
                "active": payload.get("status") == "ACTIVE",
                "state": payload,
            },
        )
    except FaultError as exc:
        return envelope.error(action, exc.code, exc.message, exc.details)
    except StateError as exc:
        return envelope.error(action, exc.code, exc.message)


def reset(force_f1: bool = False) -> dict[str, Any]:
    """Restore F1 endpoints.

    If an ACTIVE/PENDING state exists, restore those recorded interfaces.
    If state is missing and force_f1 is True (or interfaces are down), restore
    the canonical F1 interfaces after bridge validation.
    """
    action = "reset"
    try:
        require_root()
        scenario = require_scenario("F1")
        payload = read_state()
        if payload is None:
            rows = validate_endpoints(scenario)
            down = [row for row in rows if row["operstate"] != "up"]
            if not down and not force_f1:
                return envelope.ok(
                    action,
                    {
                        "status": "IDLE",
                        "message": "no active fault state; F1 endpoints already UP",
                        "endpoint_state": rows,
                    },
                )
            # Crash recovery for known F1 resources only.
            for iface in scenario.interfaces:
                _set_link(iface, up=True)
            after = validate_endpoints(scenario)
            return envelope.ok(
                action,
                {
                    "status": "RECOVERED",
                    "message": "restored canonical F1 endpoints without state file",
                    "interfaces": list(scenario.interfaces),
                    "endpoint_state": after,
                },
            )

        recorded = payload.get("interfaces") or list(scenario.interfaces)
        if list(recorded) != list(scenario.interfaces):
            raise FaultError(
                "STATE_MISMATCH",
                "recorded interfaces do not match canonical F1 resources",
                {"recorded": recorded, "expected": list(scenario.interfaces)},
            )
        # Validate bridges before mutation.
        validate_endpoints(scenario)
        for iface in scenario.interfaces:
            _set_link(iface, up=True)
        after = validate_endpoints(scenario)
        still_down = [row["interface"] for row in after if row["operstate"] != "up"]
        if still_down:
            raise FaultError(
                "RESET_INCOMPLETE",
                "one or more F1 endpoints remain down after reset",
                {"still_down": still_down},
            )
        clear_state()
        return envelope.ok(
            action,
            {
                "status": "IDLE",
                "scenario_id": "F1",
                "interfaces": list(scenario.interfaces),
                "endpoint_state": after,
            },
        )
    except FaultError as exc:
        return envelope.error(action, exc.code, exc.message, exc.details)
    except StateError as exc:
        return envelope.error(action, exc.code, exc.message)
    except ValueError as exc:
        return envelope.error(action, "INVALID_SCENARIO", str(exc))
