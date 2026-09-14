"""F2 congestion: TBF bottleneck + background iperf cross traffic."""

from __future__ import annotations

import os
import signal
import time
from pathlib import Path
from typing import Any

from faults.common import (
    FaultError,
    require_root,
    tc_del_root,
    tc_replace_tbf,
    tc_show,
    validate_iface_bridge,
)
from faults.scenarios import F2, host_ip
from faults.state import clear_state, utc_now, write_state
from telemetry.host_exec import HostExecError, find_host_pid, run_in_host, start_in_host, terminate

_PROC = Path("/proc")


def _cmdline(pid: int) -> list[str] | None:
    try:
        raw = (_PROC / str(pid) / "cmdline").read_bytes()
    except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
        return None
    return [t.decode("utf-8", "replace") for t in raw.split(b"\x00") if t]


def _is_iperf3(pid: int) -> bool:
    tokens = _cmdline(pid)
    if not tokens:
        return False
    return any(tok == "iperf3" or tok.endswith("/iperf3") for tok in tokens)


def _stop_host_iperf(host: str) -> None:
    try:
        run_in_host(host, ["pkill", "-x", "iperf3"], timeout_s=2.0)
    except HostExecError:
        pass


def _kill_tracked(pids: list[int]) -> None:
    for pid in pids:
        if not _is_iperf3(pid) and not _cmdline(pid):
            continue
        # Only kill if cmdline still looks like iperf3 or mnexec→iperf child tree root.
        tokens = _cmdline(pid)
        if tokens is None:
            continue
        if not (
            _is_iperf3(pid)
            or any("iperf3" in t for t in tokens)
            or (tokens and tokens[0].endswith("mnexec"))
        ):
            continue
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            continue
    time.sleep(0.3)
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass


def inject_f2() -> dict[str, Any]:
    require_root()
    scenario = F2
    iface = scenario.shape_iface
    row = validate_iface_bridge(iface, scenario.shape_switch)
    if row["operstate"] != "up":
        raise FaultError("LINK_NOT_UP", f"{iface} must be UP before F2", {"operstate": row["operstate"]})

    # Ensure hosts exist before mutating.
    find_host_pid(scenario.background_src)
    find_host_pid(scenario.background_dst)

    pending = {
        "status": "PENDING",
        "scenario_id": "F2",
        "injected_at": utc_now(),
        "shape_interface": iface,
        "background": {
            "src": scenario.background_src,
            "dst": scenario.background_dst,
            "port": scenario.iperf_port,
            "duration_s": scenario.background_duration_s,
        },
        "pids": [],
        "ground_truth": scenario.ground_truth(),
        "note": "evaluator/operator only; never expose to telemetry or LLM tools",
    }
    write_state(pending)

    server = None
    client = None
    try:
        tc_replace_tbf(iface, scenario.rate, scenario.burst, scenario.latency)
        server = start_in_host(
            scenario.background_dst,
            ["iperf3", "-s", "-1", "-p", str(scenario.iperf_port)],
        )
        time.sleep(0.5)
        if server.poll() is not None:
            raise FaultError("IPERF_SERVER_FAILED", "background iperf3 server exited early")
        dst_ip = host_ip(scenario.background_dst)
        client = start_in_host(
            scenario.background_src,
            [
                "iperf3",
                "-c",
                dst_ip,
                "-t",
                str(scenario.background_duration_s),
                "-p",
                str(scenario.iperf_port),
            ],
        )
        time.sleep(0.8)
        if client.poll() is not None:
            raise FaultError("IPERF_CLIENT_FAILED", "background iperf3 client exited early")
        pids = [p for p in (server.pid, client.pid) if p]
        active = dict(pending)
        active["status"] = "ACTIVE"
        active["verified_at"] = utc_now()
        active["pids"] = pids
        active["tc_show"] = tc_show(iface).strip()
        write_state(active)
        return {
            "scenario_id": "F2",
            "status": "ACTIVE",
            "shape_interface": iface,
            "tc_show": active["tc_show"],
            "background_pids": pids,
            "ground_truth": scenario.ground_truth(),
        }
    except Exception:
        if client is not None:
            terminate(client)
        if server is not None:
            terminate(server)
        _stop_host_iperf(scenario.background_src)
        _stop_host_iperf(scenario.background_dst)
        tc_del_root(iface)
        clear_state()
        raise


def reset_f2(*, force: bool = False, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    require_root()
    scenario = F2
    iface = scenario.shape_iface
    validate_iface_bridge(iface, scenario.shape_switch)
    pids = list((payload or {}).get("pids") or [])
    _kill_tracked(pids)
    _stop_host_iperf(scenario.background_src)
    _stop_host_iperf(scenario.background_dst)
    tc_del_root(iface)
    clear_state()
    show = tc_show(iface).strip()
    return {
        "status": "IDLE" if payload or force else "RECOVERED",
        "scenario_id": "F2",
        "shape_interface": iface,
        "tc_show": show,
        "message": "removed F2 TBF and background iperf",
    }
