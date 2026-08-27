"""Ephemeral evaluator/operator fault state outside the repository."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_DIR = Path(os.environ.get("COMS6200_FAULT_STATE_DIR", "/run/coms6200"))
STATE_PATH = STATE_DIR / "fault-state.json"


class StateError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ensure_state_dir() -> Path:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        os.chmod(STATE_DIR, 0o700)
    except OSError as exc:
        raise StateError("STATE_UNAVAILABLE", f"cannot create {STATE_DIR}: {exc}") from exc
    return STATE_DIR


def read_state() -> dict[str, Any] | None:
    if not STATE_PATH.is_file():
        return None
    try:
        payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateError("STATE_CORRUPT", "fault state file is unreadable") from exc
    if not isinstance(payload, dict):
        raise StateError("STATE_CORRUPT", "fault state file has invalid shape")
    return payload


def write_state(payload: dict[str, Any]) -> Path:
    ensure_state_dir()
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix="fault-state.", dir=str(STATE_DIR), text=True)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, STATE_PATH)
        os.chmod(STATE_PATH, 0o600)
    except OSError as exc:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise StateError("STATE_UNAVAILABLE", f"cannot write fault state: {exc}") from exc
    return STATE_PATH


def clear_state() -> None:
    try:
        STATE_PATH.unlink(missing_ok=True)
    except OSError as exc:
        raise StateError("STATE_UNAVAILABLE", f"cannot clear fault state: {exc}") from exc


def active_state() -> dict[str, Any] | None:
    payload = read_state()
    if payload is None:
        return None
    if payload.get("status") != "ACTIVE":
        return None
    return payload
