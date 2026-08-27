"""Allow-listed Mininet host-namespace execution.

Host names are validated against h1-h8. The gateway never accepts a PID,
executable, or command string from the caller.

Discovery uses the Mininet host-shell marker `mininet:<host>` in
/proc/<pid>/cmdline. That is the standard Mininet 2.x host process identity
when the topology is launched with `mn --custom`. The PID is re-checked
immediately before mnexec.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

from telemetry.validate import ValidationError, require_host

_PROC = Path("/proc")


class HostExecError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _cmdline_tokens(pid: int) -> list[str] | None:
    path = _PROC / str(pid) / "cmdline"
    try:
        raw = path.read_bytes()
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return None
    return [token.decode("utf-8", "replace") for token in raw.split(b"\x00") if token]


def _is_host_shell(pid: int, host: str) -> bool:
    tokens = _cmdline_tokens(pid)
    if tokens is None:
        return False
    marker = f"mininet:{host}"
    return marker in tokens


def find_host_pid(host: str) -> int:
    require_host(host)
    marker = f"mininet:{host}"
    matches: list[int] = []
    if not _PROC.is_dir():
        raise HostExecError("TOPOLOGY_NOT_RUNNING", "host namespaces require Linux /proc")
    try:
        entries = list(_PROC.iterdir())
    except OSError as exc:
        raise HostExecError("TOPOLOGY_NOT_RUNNING", "cannot scan /proc") from exc
    for entry in entries:
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        tokens = _cmdline_tokens(pid)
        if tokens is None:
            continue
        if marker in tokens:
            matches.append(pid)
    if not matches:
        raise HostExecError(
            "HOST_NAMESPACE_NOT_FOUND",
            f"Mininet host {host} is not running",
        )
    return min(matches)


def _mnexec() -> str:
    path = shutil.which("mnexec")
    if path:
        return path
    for candidate in ("/usr/bin/mnexec", "/usr/local/bin/mnexec"):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    raise HostExecError("TOPOLOGY_NOT_RUNNING", "mnexec is not available")


def run_in_host(
    host: str,
    argv: list[str],
    timeout_s: float,
) -> subprocess.CompletedProcess[str]:
    """Run a fixed argv list inside a validated Mininet host namespace."""
    if not argv or not all(isinstance(item, str) for item in argv):
        raise HostExecError("INVALID_ARGUMENT", "internal command argv is invalid")
    if any(item == "" or "\x00" in item for item in argv):
        raise HostExecError("INVALID_ARGUMENT", "internal command argv is invalid")
    pid = find_host_pid(host)
    if not _is_host_shell(pid, host):
        raise HostExecError("HOST_NAMESPACE_NOT_FOUND", f"stale namespace pid for {host}")
    command = [_mnexec(), "-a", str(pid), "--", *argv]
    try:
        return subprocess.run(
            command,
            check=False,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        raise HostExecError("COMMAND_TIMEOUT", f"{argv[0]} timed out in {host}") from exc
    except FileNotFoundError as exc:
        raise HostExecError("TOPOLOGY_NOT_RUNNING", "mnexec is not available") from exc
    except ValidationError:
        raise


def start_in_host(host: str, argv: list[str]) -> subprocess.Popen[str]:
    if not argv or not all(isinstance(item, str) for item in argv):
        raise HostExecError("INVALID_ARGUMENT", "internal command argv is invalid")
    if any(item == "" or "\x00" in item for item in argv):
        raise HostExecError("INVALID_ARGUMENT", "internal command argv is invalid")
    pid = find_host_pid(host)
    if not _is_host_shell(pid, host):
        raise HostExecError("HOST_NAMESPACE_NOT_FOUND", f"stale namespace pid for {host}")
    command = [_mnexec(), "-a", str(pid), "--", *argv]
    try:
        return subprocess.Popen(
            command,
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    except FileNotFoundError as exc:
        raise HostExecError("TOPOLOGY_NOT_RUNNING", "mnexec is not available") from exc


def terminate(proc: subprocess.Popen[str], grace_s: float = 1.0) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.terminate()
        except (ProcessLookupError, PermissionError, OSError):
            return
    deadline = time.time() + grace_s
    while proc.poll() is None and time.time() < deadline:
        time.sleep(0.05)
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
            except (ProcessLookupError, PermissionError, OSError):
                return
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            return
