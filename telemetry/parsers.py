"""Normalisers and parsers for ONOS REST, ping, and iperf3 output."""

from __future__ import annotations

import json
import re
from typing import Any
import xml.etree.ElementTree as ET

from topologies.spec import INTER_SWITCH_LINKS, SWITCH_NAMES, peer_of, switch_name

_PING_COUNTS = re.compile(
    r"(\d+)\s+packets transmitted,\s+(\d+)\s+(?:packets\s+)?received",
    re.IGNORECASE,
)
_PING_LOSS = re.compile(r"(\d+(?:\.\d+)?)% packet loss", re.IGNORECASE)
_PING_RTT = re.compile(
    r"rtt min/avg/max(?:/mdev)? = "
    r"([\d.]+)/([\d.]+)/([\d.]+)",
    re.IGNORECASE,
)


def _int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def physical_links_from_onos(onos_links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse ONOS directed pairs into one physical inter-switch link."""
    grouped: dict[tuple[tuple[str, int], tuple[str, int]], dict[str, Any]] = {}
    for item in onos_links:
        src = item.get("src") or {}
        dst = item.get("dst") or {}
        src_dev = _str(src.get("device"))
        dst_dev = _str(dst.get("device"))
        src_port = _int(src.get("port"))
        dst_port = _int(dst.get("port"))
        if not src_dev or not dst_dev or src_port is None or dst_port is None:
            continue
        left = (src_dev, src_port)
        right = (dst_dev, dst_port)
        key = tuple(sorted((left, right)))
        entry = grouped.setdefault(
            key,
            {
                "a": {
                    "device": key[0][0],
                    "switch": switch_name(key[0][0]),
                    "port": key[0][1],
                },
                "b": {
                    "device": key[1][0],
                    "switch": switch_name(key[1][0]),
                    "port": key[1][1],
                },
                "state": _str(item.get("state")),
                "type": _str(item.get("type")),
                "source": "onos",
            },
        )
        state = _str(item.get("state"))
        if state == "ACTIVE":
            entry["state"] = "ACTIVE"
        elif entry.get("state") is None:
            entry["state"] = state
    rows = list(grouped.values())
    rows.sort(
        key=lambda row: (
            str(row["a"]["switch"] or row["a"]["device"]),
            int(row["a"]["port"]),
            str(row["b"]["switch"] or row["b"]["device"]),
            int(row["b"]["port"]),
        )
    )
    return rows


def configured_inter_switch_links() -> list[dict[str, Any]]:
    rows = []
    for link in INTER_SWITCH_LINKS:
        rows.append(
            {
                "a": {"switch": link.a, "port": link.a_port},
                "b": {"switch": link.b, "port": link.b_port},
                "source": "configured",
            }
        )
    return rows


def normalize_devices(devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for device in devices:
        device_id = _str(device.get("id"))
        annotations = device.get("annotations") or {}
        rows.append(
            {
                "id": device_id,
                "name": switch_name(device_id or "") or _str(annotations.get("datapathDescription")),
                "available": bool(device.get("available")),
                "role": _str(device.get("role")),
                "protocol": _str(annotations.get("protocol")),
                "hw": _str(device.get("hw")),
                "sw": _str(device.get("sw")),
                "source": "onos",
            }
        )
    rows.sort(key=lambda row: str(row.get("name") or row.get("id")))
    return rows


def _port_number(port: dict[str, Any]) -> int | str | None:
    element = port.get("element")
    if isinstance(element, dict) and element.get("port") is not None:
        parsed = _int(element.get("port"))
        return parsed if parsed is not None else _str(element.get("port"))
    if port.get("port") is not None:
        parsed = _int(port.get("port"))
        return parsed if parsed is not None else _str(port.get("port"))
    return None


def normalize_ports(switch: str, ports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for port in ports:
        number = _port_number(port)
        annotations = port.get("annotations") or {}
        numeric = number if isinstance(number, int) else _int(number)
        peer = peer_of(switch, numeric) if numeric is not None else None
        rows.append(
            {
                "switch": switch,
                "port": number,
                "name": _str(annotations.get("portName")) or _str(port.get("portName")),
                "enabled": port.get("isEnabled"),
                "type": _str(port.get("type")),
                "port_speed": _int(port.get("portSpeed")),
                "peer": peer,
                "source": "onos",
            }
        )

    def sort_key(row: dict[str, Any]) -> tuple[int, int | str]:
        port = row["port"]
        if isinstance(port, int):
            return (0, port)
        return (1, str(port))

    rows.sort(key=sort_key)
    return rows


def _stats_for_device(statistics: list[dict[str, Any]], device_id: str) -> list[dict[str, Any]]:
    ports: list[dict[str, Any]] = []
    for block in statistics:
        if _str(block.get("device")) != device_id:
            continue
        ports.extend(block.get("ports") or [])
    return ports


def _counter(port: dict[str, Any], *names: str) -> int | None:
    for name in names:
        if port.get(name) is not None:
            return _int(port.get(name))
    return None


def normalize_port_stats(
    switch: str,
    device_id: str,
    first: list[dict[str, Any]],
    second: list[dict[str, Any]],
    interval_sec: float,
    delta: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    first_ports = {_port_number(p): p for p in _stats_for_device(first, device_id)}
    second_ports = {_port_number(p): p for p in _stats_for_device(second, device_id)}
    delta_ports = {_port_number(p): p for p in _stats_for_device(delta or [], device_id)}
    numbers = sorted(
        (n for n in set(first_ports) | set(second_ports) if n is not None),
        key=lambda item: (0, item) if isinstance(item, int) else (1, str(item)),
    )
    rows: list[dict[str, Any]] = []
    for number in numbers:
        before = first_ports.get(number) or {}
        after = second_ports.get(number) or before
        rx_bytes_1 = _counter(before, "bytesReceived")
        tx_bytes_1 = _counter(before, "bytesSent")
        rx_bytes_2 = _counter(after, "bytesReceived")
        tx_bytes_2 = _counter(after, "bytesSent")
        rx_bps = None
        tx_bps = None
        if (
            rx_bytes_1 is not None
            and rx_bytes_2 is not None
            and interval_sec > 0
        ):
            rx_bps = max(0.0, (rx_bytes_2 - rx_bytes_1) * 8.0 / interval_sec)
        if (
            tx_bytes_1 is not None
            and tx_bytes_2 is not None
            and interval_sec > 0
        ):
            tx_bps = max(0.0, (tx_bytes_2 - tx_bytes_1) * 8.0 / interval_sec)
        delta_port = delta_ports.get(number) or {}
        rows.append(
            {
                "switch": switch,
                "port": number,
                "packets_rx": _counter(after, "packetsReceived"),
                "packets_tx": _counter(after, "packetsSent"),
                "bytes_rx": rx_bytes_2,
                "bytes_tx": tx_bytes_2,
                "drops_rx": _counter(after, "packetsRxDropped"),
                "drops_tx": _counter(after, "packetsTxDropped"),
                "errors_rx": _counter(after, "packetsRxErrors"),
                "errors_tx": _counter(after, "packetsTxErrors"),
                "duration_sec": _counter(after, "durationSec"),
                "rx_bits_per_sec": rx_bps,
                "tx_bits_per_sec": tx_bps,
                "delta_window_sec": _counter(delta_port, "durationSec"),
                "utilization_pct": None,
                "peer": peer_of(switch, number) if isinstance(number, int) else None,
            }
        )
    return {
        "switch": switch,
        "sample_interval_sec": interval_sec,
        "rate_method": "two_sample_byte_delta",
        "utilization_note": (
            "utilization_pct is null because no non-ground-truth link capacity is available"
        ),
        "ports": rows,
    }


def normalize_flows(switch: str, device_id: str, flows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for flow in flows:
        if _str(flow.get("deviceId")) != device_id:
            continue
        selector = flow.get("selector") or {}
        treatment = flow.get("treatment") or {}
        rows.append(
            {
                "id": _str(flow.get("id")),
                "table_id": flow.get("tableId"),
                "state": _str(flow.get("state")),
                "priority": _int(flow.get("priority")),
                "app_id": _str(flow.get("appId")),
                "selector": list(selector.get("criteria") or []),
                "treatment": list(treatment.get("instructions") or []),
                "packets": _int(flow.get("packets")),
                "bytes": _int(flow.get("bytes")),
                "life_sec": _int(flow.get("life")),
            }
        )
    rows.sort(
        key=lambda row: (
            -(row["priority"] or 0),
            str(row["id"] or ""),
        )
    )
    return rows


def parse_ping(text: str) -> dict[str, Any]:
    counts = _PING_COUNTS.search(text)
    loss = _PING_LOSS.search(text)
    rtt = _PING_RTT.search(text)
    if counts is None:
        raise ValueError("ping output did not contain transmit/receive counts")
    sent = int(counts.group(1))
    received = int(counts.group(2))
    if loss is not None:
        loss_pct = float(loss.group(1))
    elif sent > 0:
        loss_pct = 100.0 * (sent - received) / sent
    else:
        loss_pct = None
    return {
        "sent": sent,
        "received": received,
        "loss_pct": loss_pct,
        "rtt_min_ms": float(rtt.group(1)) if rtt else None,
        "rtt_avg_ms": float(rtt.group(2)) if rtt else None,
        "rtt_max_ms": float(rtt.group(3)) if rtt else None,
    }


def _iperf_field(summary: dict[str, Any], key: str) -> Any:
    if key not in summary:
        return None
    return summary.get(key)


def _prefer(primary: dict[str, Any], fallback: dict[str, Any], key: str) -> Any:
    """Use the receiver summary when it reports the key, including an explicit zero."""
    if key in primary:
        return primary.get(key)
    return _iperf_field(fallback, key)


def parse_iperf(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("iperf3 did not return JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("iperf3 JSON was not an object")
    if payload.get("error"):
        raise ValueError(str(payload["error"]))
    end = payload.get("end") or {}
    if not isinstance(end, dict):
        raise ValueError("iperf3 JSON end summary was not an object")
    sent = end.get("sum_sent") or {}
    received = end.get("sum_received") or {}
    if not isinstance(sent, dict) or not isinstance(received, dict):
        raise ValueError("iperf3 JSON side summary was not an object")

    sender_bytes = _iperf_field(sent, "bytes")
    sender_bps = _iperf_field(sent, "bits_per_second")
    sender_seconds = _iperf_field(sent, "seconds")
    receiver_bytes = _iperf_field(received, "bytes")
    receiver_bps = _iperf_field(received, "bits_per_second")
    receiver_seconds = _iperf_field(received, "seconds")
    bits = _prefer(received, sent, "bits_per_second")
    retransmits = _iperf_field(sent, "retransmits")
    return {
        "duration_sec": _prefer(received, sent, "seconds"),
        "bytes_transferred": _prefer(received, sent, "bytes"),
        "mbit_per_sec": (float(bits) / 1_000_000.0) if bits is not None else None,
        "retransmissions": retransmits,
        "retransmits": retransmits,
        "sender_bytes": sender_bytes,
        "sender_bits_per_sec": sender_bps,
        "sender_duration_sec": sender_seconds,
        "receiver_bytes": receiver_bytes,
        "receiver_bits_per_sec": receiver_bps,
        "receiver_duration_sec": receiver_seconds,
    }


def parse_nmapXML(text: str) -> dict[str, Any]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError("nmap did not return valid XML") from exc
    if root.tag != "nmaprun":
        raise ValueError("nmap XML root element is not nmaprun")
    host = root.find("host")
    if host is None:
        raise ValueError("nmap XML does not contain a host element")
    ports = host.find("ports")
    if ports is None:
        raise ValueError("nmap XML does not contain a ports element")
    for port in ports.findall("port"):
        protocol = port.get("protocol")
        number = _int(port.get("portid"))
        state_elem = port.find("state")
        state = _str(state_elem.get("state")) if state_elem is not None else None
        service_elem = port.find("service")
        service_name = _str(service_elem.get("name")) if service_elem is not None else None
        return {
                "protocol": protocol,
                "port": number,
                "state": state,
                "service": service_name,
        }
    raise ValueError("nmap XML does not contain any port elements")


# Imported by tests; keep SWITCH_NAMES referenced so mappings stay in sync.
assert SWITCH_NAMES["of:0000000000000001"] == "s1"
