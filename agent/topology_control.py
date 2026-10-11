"""Operator-only live topology switching. Never a model tool."""

from __future__ import annotations

import os
import logging
import json
from pathlib import Path
import re
import subprocess
import sys

from topologies import active

ROOT = Path(__file__).resolve().parents[1]
TOPOLOGIES = (
    {"id": "main6s8h", "label": "Main", "description": "6 switches · 8 hosts"},
    {"id": "ring5s5h", "label": "Ring", "description": "5 switches · 5 hosts"},
    {"id": "tree5s8h", "label": "Tree", "description": "7 switches · 8 hosts"},
)
error: str | None = None


def running_topology() -> str | None:
    """Match switch-side ports, including older helpers with no identity marker."""
    try:
        actual = {p.name for p in Path("/sys/class/net").iterdir()
                  if re.fullmatch(r"s\d+-eth\d+", p.name)}
    except OSError:
        return None
    for name, spec in active.SPECS.items():
        ends = [(link.a, link.a_port) for link in spec.INTER_SWITCH_LINKS]
        ends += [(link.b, link.b_port) for link in spec.INTER_SWITCH_LINKS]
        ends += [(a.switch, a.switch_port) for a in spec.HOST_ATTACHMENTS]
        if actual == {f"{sw}-eth{port}" for sw, port in ends}:
            return name
    return None


def ready_file() -> Path:
    return Path(os.getenv("COMS6200_FAULT_STATE_DIR", "/run/coms6200")) / "mininet.ready"


def restore_selection() -> None:
    """Recognise a helper-managed testbed after an agent/dev-server restart."""
    try:
        name = ready_file().read_text().strip()
    except OSError:
        name = None
    running = running_topology()
    if running:
        active.select(running)
    elif name in active.SPECS:
        active.select(name)


def environment(topology: str | None = None) -> dict[str, str]:
    return {**os.environ, "COMS6200_TOPOLOGY": topology or active.TOPOLOGY}


def redact(text: str) -> str:
    for key, value in os.environ.items():
        if value and any(word in key.upper() for word in ("PASSWORD", "TOKEN", "SECRET", "API_KEY")):
            text = text.replace(value, "[redacted]")
    return text


def run_command(argv: list[str], topology: str, timeout: int = 240) -> None:
    """Fixed operator commands; expose only a bounded, redacted failure reason."""
    if "faults.cli" in argv:
        step = "fault reset"
    elif "forwarding/baseline_forwarding.py" in argv:
        step = "baseline removal"
    else:
        step = "testbed " + argv[-1]
    try:
        result = subprocess.run(
            argv, cwd=ROOT, env=environment(topology), capture_output=True,
            text=True, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{topology} {step} timed out; check the testbed before retrying.") from exc
    except OSError as exc:
        raise RuntimeError("Cannot run the testbed helper; check the server installation.") from exc
    if result.returncode:
        # These helpers run locally, but their errors can still include secrets
        # from the environment. Redact before truncation and expose only the
        # named error, rather than a traceback or full helper output, to the UI.
        output = redact((result.stdout or "") + "\n" + (result.stderr or ""))[-4000:]
        logging.getLogger(__name__).error("%s %s failed (exit %s):\n%s",
                                        topology, step, result.returncode, output)
        detail = "check the agent terminal for the failed command's output"
        reasons = [line.strip() for line in output.splitlines()
                   if line.startswith(("ERROR:", "RuntimeError:", "ModuleNotFoundError:", "ImportError:"))]
        if reasons:
            detail = reasons[-1][:400]
        # Fault CLI envelopes expose a controlled error message, not ground truth.
        if "faults.cli" in argv:
            try:
                payload = json.loads(result.stdout)
                fault_error = payload.get("error") or {}
                detail = str(fault_error.get("code") or "fault reset failed")
                if fault_error.get("message"):
                    detail += ": " + redact(str(fault_error["message"]))[:400]
            except (ValueError, AttributeError):
                pass
        raise RuntimeError(f"{topology} {step} failed (exit {result.returncode}); {detail}.")


def load_topology(name: str) -> None:
    """Stop the previous network and provision matching baseline rules and tools."""
    global error
    if name not in active.SPECS:
        raise ValueError("topology must be main6s8h, ring5s5h or tree5s8h")
    if os.geteuid() != 0:
        raise RuntimeError("Topology loading needs root. Restart with python -m agent.")
    running = running_topology()
    previous = running or active.TOPOLOGY
    # Keep a same-topology selection/fault load from restarting a running testbed.
    if name == previous and error is None and running == name:
        active.select(name)
        return
    try:
        # Remove even main's baseline flows before disconnecting its DPIDs.
        # The normal main stop intentionally retains them for frozen protocol v1.
        if running:
            run_command([sys.executable, "-m", "faults.cli", "reset"], previous)
            run_command(
                [sys.executable, "forwarding/baseline_forwarding.py", "remove"], previous,
            )
        run_command(["bash", "scripts/testbed.sh", "stop"], previous)
        run_command(["bash", "scripts/testbed.sh", "start"], name)
    except RuntimeError as exc:
        restore_selection()
        error = str(exc)
        raise
    active.select(name)
    error = None


restore_selection()
