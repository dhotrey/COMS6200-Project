"""Short-window switch-port measurements.

Rates and drop/error deltas come from kernel interface counters. Queue backlog
is the instantaneous sample at the end of the window. Overlimit and requeue
values are deltas across that same window. Configuration text is discarded.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from topologies.spec import peer_of

from telemetry.validate import ValidationError, require_switch

LINK_SAMPLE_SEC = 2.0

_IFACE = re.compile(r"^s[1-6]-eth[1-5]$")
_OVERLIMITS = re.compile(r"overlimits\s+(\d+)\s+requeues\s+(\d+)")
_BACKLOG = re.compile(r"backlog\s+(\d+)b\s+(\d+)p\b")
_STAT_NAMES = (
    "rx_bytes",
    "tx_bytes",
    "rx_packets",
    "tx_packets",
    "rx_dropped",
    "tx_dropped",
    "rx_errors",
    "tx_errors",
)


def require_switch_port(sw: object, port: object) -> tuple[str, int]:
    switch = require_switch(sw)
    if not isinstance(port, int) or isinstance(port, bool):
        raise ValidationError("INVALID_PORT", "port must be an integer")
    if peer_of(switch, port) is None:
        raise ValidationError("INVALID_PORT", "port is not a known port on that switch")
    interface_name(switch, port)
    return switch, port


def interface_name(switch: str, port: int) -> str:
    name = f"{switch}-eth{port}"
    if _IFACE.fullmatch(name) is None:
        raise ValidationError("INVALID_PORT", "port is not a known port on that switch")
    return name


def public_peer(switch: str, port: int) -> dict[str, str | int]:
    peer = peer_of(switch, port)
    if peer is None:
        raise ValidationError("INVALID_PORT", "port is not a known port on that switch")
    if peer.get("kind") == "switch":
        return {"switch": str(peer["id"]), "port": int(peer["port"])}
    return {"host": str(peer["id"])}


def parse_qdisc_counters(text: str) -> dict[str, int | None]:
    """Extract runtime queue counters. The rest of the text is ignored."""
    overlimits = None
    requeues = None
    backlog_bytes = None
    backlog_packets = None
    over_match = _OVERLIMITS.search(text or "")
    if over_match:
        overlimits = int(over_match.group(1))
        requeues = int(over_match.group(2))
    backlog_match = _BACKLOG.search(text or "")
    if backlog_match:
        backlog_bytes = int(backlog_match.group(1))
        backlog_packets = int(backlog_match.group(2))
    return {
        "overlimits": overlimits,
        "requeues": requeues,
        "backlog_bytes": backlog_bytes,
        "backlog_packets": backlog_packets,
    }


def read_iface_counters(iface: str) -> dict[str, int | None] | None:
    checked = interface_name(*_split_iface(iface))
    directory = Path("/sys/class/net") / checked / "statistics"
    if not directory.is_dir():
        return None
    values: dict[str, int | None] = {}
    for name in _STAT_NAMES:
        try:
            values[name] = int((directory / name).read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            values[name] = None
    return values


def read_qdisc_text(iface: str) -> str | None:
    checked = interface_name(*_split_iface(iface))
    try:
        completed = subprocess.run(
            ["tc", "-s", "qdisc", "show", "dev", checked],
            shell=False,
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout or ""


def build_link_metrics(
    switch: str,
    port: int,
    enabled: bool | None,
    interval_sec: float,
    before_iface: dict[str, int | None] | None,
    after_iface: dict[str, int | None] | None,
    before_queue: dict[str, int | None],
    after_queue: dict[str, int | None],
) -> dict[str, Any]:
    rx_bytes = _delta(before_iface, after_iface, "rx_bytes")
    tx_bytes = _delta(before_iface, after_iface, "tx_bytes")
    rx_packets = _delta(before_iface, after_iface, "rx_packets")
    tx_packets = _delta(before_iface, after_iface, "tx_packets")
    return {
        "switch": switch,
        "port": port,
        "peer": public_peer(switch, port),
        "enabled": enabled,
        "sample_interval_sec": interval_sec,
        "rx_packets_delta": rx_packets,
        "tx_packets_delta": tx_packets,
        "rx_bytes_delta": rx_bytes,
        "tx_bytes_delta": tx_bytes,
        "rx_bits_per_sec": _rate_bits(rx_bytes, interval_sec),
        "tx_bits_per_sec": _rate_bits(tx_bytes, interval_sec),
        "rx_packets_per_sec": _rate_packets(rx_packets, interval_sec),
        "tx_packets_per_sec": _rate_packets(tx_packets, interval_sec),
        "rx_drops_delta": _delta(before_iface, after_iface, "rx_dropped"),
        "tx_drops_delta": _delta(before_iface, after_iface, "tx_dropped"),
        "rx_errors_delta": _delta(before_iface, after_iface, "rx_errors"),
        "tx_errors_delta": _delta(before_iface, after_iface, "tx_errors"),
        "queue_backlog_bytes": after_queue.get("backlog_bytes"),
        "queue_backlog_packets": after_queue.get("backlog_packets"),
        "queue_overlimits_delta": _delta(before_queue, after_queue, "overlimits"),
        "queue_requeues_delta": _delta(before_queue, after_queue, "requeues"),
    }


def _split_iface(iface: str) -> tuple[str, int]:
    if _IFACE.fullmatch(iface) is None:
        raise ValidationError("INVALID_PORT", "port is not a known port on that switch")
    switch, _, raw_port = iface.partition("-eth")
    return switch, int(raw_port)


def _delta(
    before: dict[str, int | None] | None,
    after: dict[str, int | None] | None,
    key: str,
) -> int | None:
    if before is None or after is None:
        return None
    left = before.get(key)
    right = after.get(key)
    if left is None or right is None:
        return None
    return max(0, right - left)


def _rate_bits(byte_delta: int | None, interval_sec: float) -> float | None:
    if byte_delta is None or interval_sec <= 0:
        return None
    return byte_delta * 8.0 / interval_sec


def _rate_packets(packet_delta: int | None, interval_sec: float) -> float | None:
    if packet_delta is None or interval_sec <= 0:
        return None
    return packet_delta / interval_sec
