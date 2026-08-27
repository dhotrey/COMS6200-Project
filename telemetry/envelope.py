"""Common JSON envelope for telemetry tools."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ok(tool: str, data: Any) -> dict[str, Any]:
    return {"tool": tool, "ok": True, "timestamp": utc_now(), "data": data, "error": None}


def error(
    tool: str,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "tool": tool,
        "ok": False,
        "timestamp": utc_now(),
        "data": None,
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
        },
    }
