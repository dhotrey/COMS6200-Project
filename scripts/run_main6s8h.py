#!/usr/bin/env python3
"""Keep the selected topology running without an interactive Mininet CLI.

Runs COMS6200_TOPOLOGY (topologies/active.py; default main6s8h). The file
keeps its historical name because testbed.sh and the docs refer to it.

Operator helper for scripts/testbed.sh. Host shells still use the standard
Mininet marker mininet:<host> so telemetry ping/iperf keep working.

Not an LLM tool. Does not install forwarding or inject faults.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from topologies.active import TOPOLOGY  # noqa: E402
from topologies.main_topology import MainProjectTopology  # noqa: E402
from topologies.ring_topology import RingTopology  # noqa: E402
from topologies.tree_topology import TreeTopology  # noqa: E402

TOPOLOGIES = {
    "main6s8h": MainProjectTopology,
    "ring5s5h": RingTopology,
    "tree5s8h": TreeTopology,
}

RUN_DIR = Path(os.environ.get("COMS6200_FAULT_STATE_DIR", "/run/coms6200"))
DEFAULT_PID = RUN_DIR / "mininet.pid"
DEFAULT_READY = RUN_DIR / "mininet.ready"
DEFAULT_LOG = RUN_DIR / "mininet.log"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _read_pid(path: Path) -> int | None:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text.isdigit():
        return None
    return int(text)


def _ensure_run_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)


def _clear_stale(pid_path: Path, ready_path: Path) -> None:
    pid = _read_pid(pid_path)
    if pid is not None and _pid_alive(pid):
        raise SystemExit(f"topology already running as pid {pid}")
    for stale in (pid_path, ready_path):
        try:
            stale.unlink()
        except OSError:
            pass


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    os.chmod(path, 0o600)


def _daemonize(log_path: Path) -> None:
    if os.fork() > 0:
        os._exit(0)
    os.setsid()
    if os.fork() > 0:
        os._exit(0)
    os.chdir("/")
    os.umask(0o22)
    log_fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    os.dup2(log_fd, 1)
    os.dup2(log_fd, 2)
    if log_fd > 2:
        os.close(log_fd)
    null_fd = os.open("/dev/null", os.O_RDONLY)
    os.dup2(null_fd, 0)
    if null_fd > 2:
        os.close(null_fd)


def _build_net(controller_ip: str, controller_port: int):
    from mininet.log import setLogLevel
    from mininet.net import Mininet
    from mininet.node import OVSKernelSwitch, RemoteController

    setLogLevel("info")
    return Mininet(
        topo=TOPOLOGIES[TOPOLOGY](),
        switch=OVSKernelSwitch,
        controller=lambda name: RemoteController(
            name, ip=controller_ip, port=controller_port
        ),
        autoSetMacs=False,
        autoStaticArp=False,
        waitConnected=False,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=f"Run {TOPOLOGY} in the background for session start/stop."
    )
    parser.add_argument("--pid-file", type=Path, default=DEFAULT_PID)
    parser.add_argument("--ready-file", type=Path, default=DEFAULT_READY)
    parser.add_argument("--log-file", type=Path, default=DEFAULT_LOG)
    parser.add_argument(
        "--foreground",
        action="store_true",
        help="Do not daemonize (debugging only)",
    )
    parser.add_argument("--controller-ip", default=os.environ.get("ONOS_HOST", "127.0.0.1"))
    parser.add_argument(
        "--controller-port",
        type=int,
        default=int(os.environ.get("ONOS_OF_PORT", "6653")),
    )
    args = parser.parse_args(argv)

    if os.geteuid() != 0:
        raise SystemExit("run_main6s8h.py must run as root (Mininet/OVS)")

    _ensure_run_dir(args.pid_file.parent)
    _clear_stale(args.pid_file, args.ready_file)
    _ensure_run_dir(args.log_file.parent)

    if not args.foreground:
        _daemonize(args.log_file)

    _write_text(args.pid_file, f"{os.getpid()}\n")
    net = None
    stop = False

    def _request_stop(signum: int, _frame: object) -> None:
        nonlocal stop
        stop = True
        print(f"received signal {signum}; stopping {TOPOLOGY}")

    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)

    try:
        net = _build_net(args.controller_ip, args.controller_port)
        net.start()
        # The agent uses this identity after a restart to select matching tools.
        _write_text(args.ready_file, f"{TOPOLOGY}\n")
        print(f"{TOPOLOGY} started; waiting for stop signal")
        while not stop:
            time.sleep(0.5)
    finally:
        if net is not None:
            try:
                net.stop()
            except Exception as exc:  # noqa: BLE001
                print(f"net.stop() failed: {exc}")
        for path in (args.ready_file, args.pid_file):
            try:
                path.unlink()
            except OSError:
                pass
        print(f"{TOPOLOGY} stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
