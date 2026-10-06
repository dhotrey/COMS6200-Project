"""Shared low-level helpers for operator fault injection.

Never imported by telemetry. Fixed argv only; shell disabled.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from topologies.active import TOPOLOGY


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
            "this fault mutation requires root; re-run as root or with sudo "
            "(this tool does not invoke sudo itself)",
        )


def which(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise FaultError("COMMAND_UNAVAILABLE", f"{name} is not available on PATH")
    return path


def run(argv: list[str], timeout_s: float = 5.0) -> subprocess.CompletedProcess[str]:
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


def iface_exists(name: str) -> bool:
    return run([which("ip"), "-o", "link", "show", "dev", name]).returncode == 0


def iface_operstate(name: str) -> str:
    path = Path("/sys/class/net") / name / "operstate"
    try:
        return path.read_text(encoding="utf-8").strip().lower()
    except FileNotFoundError:
        completed = run([which("ip"), "-o", "link", "show", "dev", name])
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


def port_to_br(iface: str) -> str:
    completed = run([which("ovs-vsctl"), "port-to-br", iface])
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


def set_link(iface: str, up: bool) -> None:
    action = "up" if up else "down"
    completed = run([which("ip"), "link", "set", "dev", iface, action])
    if completed.returncode != 0:
        raise FaultError(
            "LINK_MUTATION_FAILED",
            f"failed to bring {iface} {action}",
            {"stderr": (completed.stderr or "")[-300:]},
        )


def validate_iface_bridge(iface: str, expected_bridge: str) -> dict[str, str]:
    if not iface_exists(iface):
        raise FaultError(
            "TOPOLOGY_NOT_RUNNING",
            f"expected interface {iface} is missing; is {TOPOLOGY} running?",
        )
    bridge = port_to_br(iface)
    if bridge != expected_bridge:
        raise FaultError(
            "TOPOLOGY_MISMATCH",
            f"{iface} belongs to bridge {bridge}, expected {expected_bridge}",
        )
    return {
        "interface": iface,
        "bridge": bridge,
        "operstate": iface_operstate(iface),
    }


# Fixed tc helpers — rates/interfaces come only from scenario constants.
def tc_replace_tbf(iface: str, rate: str, burst: str, latency: str) -> None:
    completed = run(
        [
            which("tc"),
            "qdisc",
            "replace",
            "dev",
            iface,
            "root",
            "tbf",
            "rate",
            rate,
            "burst",
            burst,
            "latency",
            latency,
        ]
    )
    if completed.returncode != 0:
        raise FaultError(
            "TC_FAILED",
            f"failed to install tbf on {iface}",
            {"stderr": (completed.stderr or "")[-300:]},
        )


def tc_del_root(iface: str) -> None:
    # Idempotent: missing qdisc is OK.
    run([which("tc"), "qdisc", "del", "dev", iface, "root"], timeout_s=5.0)


def tc_has_root(iface: str) -> bool:
    completed = run([which("tc"), "qdisc", "show", "dev", iface])
    if completed.returncode != 0:
        return False
    text = completed.stdout or ""
    return "qdisc" in text and "noqueue" not in text.splitlines()[0] if text.strip() else False


def tc_show(iface: str) -> str:
    return run([which("tc"), "qdisc", "show", "dev", iface]).stdout or ""
