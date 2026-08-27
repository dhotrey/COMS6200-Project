"""Common JSON envelope for the operator-facing fault CLI."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ok(action: str, data: Any) -> dict[str, Any]:
    return {
        "component": "faults",
        "action": action,
        "ok": True,
        "timestamp": utc_now(),
        "data": data,
        "error": None,
    }


def error(
    action: str,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "component": "faults",
        "action": action,
        "ok": False,
        "timestamp": utc_now(),
        "data": None,
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
        },
    }
