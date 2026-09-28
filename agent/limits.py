"""Process limits for protocol v1. No network or provider imports."""
from __future__ import annotations

import os


def runtime_limits() -> dict[str, int | float]:
    """Effective process limits. Defaults are the protocol-v1 values."""
    return {
        "max_tool_calls": int(os.environ.get("MAX_TOOL_CALLS", "14")),
        "max_turn_seconds": int(float(os.environ.get("MAX_TURN_SECONDS", "300"))),
        "tool_delay_min_seconds": float(os.environ.get("TOOL_DELAY_MIN_SECONDS", "0")),
        "tool_delay_max_seconds": float(os.environ.get("TOOL_DELAY_MAX_SECONDS", "0")),
    }
