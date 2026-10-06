"""Provider-neutral JSON schemas for the diagnostic tools."""

from __future__ import annotations

from typing import Any

from topologies.active import HOST_ATTACHMENTS, HOSTS, INTER_SWITCH_LINKS, SWITCHES

_HOST_ENUM = list(HOSTS)
_SWITCH_ENUM = list(SWITCHES)
_MAX_SWITCH_PORT = max(
    [link.a_port for link in INTER_SWITCH_LINKS]
    + [link.b_port for link in INTER_SWITCH_LINKS]
    + [item.switch_port for item in HOST_ATTACHMENTS]
)

TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "get_topology": {
        "name": "get_topology",
        "description": (
            "Return combined topology: ONOS device/link/port state plus the "
            "configured Mininet host-attachment map. Does not use ONOS host discovery."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    "ping": {
        "name": "ping",
        "description": (
            "Run a bounded ICMP ping between two project hosts using their "
            "configured primary IPv4 addresses."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "src": {"type": "string", "enum": _HOST_ENUM},
                "dst": {"type": "string", "enum": _HOST_ENUM},
                "count": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                    "default": 3,
                    "description": "ICMP echo count. Default 3, maximum 10.",
                },
            },
            "required": ["src", "dst"],
            "additionalProperties": False,
        },
    },
    "nmap": {
        "name": "nmap",
        "description": "Run a port scan between two project hosts using the specified protocol and port.",
        "parameters": {
            "type": "object",
            "properties": {
                "src": {"type": "string", "enum": _HOST_ENUM},
                "dst": {"type": "string", "enum": _HOST_ENUM},
                "proto": {"type": "string", "enum": ["tcp", "udp"]},
                "port": {"type": "integer", "minimum": 0, "maximum": 65535},
            },
            "required": ["src", "dst", "proto", "port"],
            "additionalProperties": False,
        },
    },
    "get_port_status": {
        "name": "get_port_status",
        "description": "Return ONOS port enabled/name/type state for one switch, with configured peers.",
        "parameters": {
            "type": "object",
            "properties": {
                "sw": {"type": "string", "enum": _SWITCH_ENUM},
            },
            "required": ["sw"],
            "additionalProperties": False,
        },
    },
    "get_port_stats": {
        "name": "get_port_stats",
        "description": (
            "Return ONOS port counters and a short derived bit-rate sample for one switch. "
            "Does not compute link utilisation from configured capacity."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sw": {"type": "string", "enum": _SWITCH_ENUM},
            },
            "required": ["sw"],
            "additionalProperties": False,
        },
    },
    "get_link_metrics": {
        "name": "get_link_metrics",
        "description": (
            "Return a fixed two-second measurement for one known switch port: "
            "its peer, whether the port is enabled, packet and byte deltas, "
            "bit and packet rates, drop and error deltas, instantaneous queue "
            "backlog, and overlimit and requeue deltas. Unavailable counters are null. "
            "The sample window cannot be changed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sw": {"type": "string", "enum": _SWITCH_ENUM},
                "port": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": _MAX_SWITCH_PORT,
                },
            },
            "required": ["sw", "port"],
            "additionalProperties": False,
        },
    },
    "get_flow_table": {
        "name": "get_flow_table",
        "description": "Return normalised ONOS flow entries for one switch.",
        "parameters": {
            "type": "object",
            "properties": {
                "sw": {"type": "string", "enum": _SWITCH_ENUM},
            },
            "required": ["sw"],
            "additionalProperties": False,
        },
    },
    "iperf": {
        "name": "iperf",
        "description": (
            "Run a bounded one-shot iperf3 TCP throughput test between two project hosts. "
            "The measurement reports sender_* (bytes, bits per second, and duration transmitted by the client) "
            "and receiver_* (bytes, bits per second, and duration received by the server) separately, plus retransmits. "
            "A completed test can have receiver_bytes 0 while sender_bytes is greater than 0; that is a measurement, not a command failure. "
            "Legacy bytes_transferred, mbit_per_sec, and duration_sec follow the receiver summary when that summary includes the field, otherwise the sender summary. "
            "Command failures return ok false."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "src": {"type": "string", "enum": _HOST_ENUM},
                "dst": {"type": "string", "enum": _HOST_ENUM},
                "duration": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 5,
                    "default": 2,
                    "description": "Test duration in seconds. Default 2, maximum 5.",
                },
            },
            "required": ["src", "dst"],
            "additionalProperties": False,
        },
    },
}


CANONICAL_TOOL_NAMES: tuple[str, ...] = (
    "get_topology",
    "ping",
    "nmap",
    "get_port_status",
    "get_port_stats",
    "get_link_metrics",
    "get_flow_table",
    "iperf",
)


def schema_list() -> list[dict[str, Any]]:
    """Return tool schemas in the model-facing order. Includes every TOOL_SCHEMAS entry."""
    missing = [name for name in CANONICAL_TOOL_NAMES if name not in TOOL_SCHEMAS]
    extra = [name for name in TOOL_SCHEMAS if name not in CANONICAL_TOOL_NAMES]
    if missing or extra:
        raise RuntimeError(f"tool schema list drifted: missing={missing} extra={extra}")
    return [TOOL_SCHEMAS[name] for name in CANONICAL_TOOL_NAMES]


def validate_arguments(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    """Reject unknown tools, extra properties, and values outside the allow-lists."""
    from telemetry.validate import ValidationError

    if name not in TOOL_SCHEMAS:
        raise ValidationError("INVALID_TOOL", "unknown telemetry tool")
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise ValidationError("INVALID_ARGUMENT", "tool arguments must be an object")
    schema = TOOL_SCHEMAS[name]["parameters"]
    properties = schema.get("properties") or {}
    required = schema.get("required") or []
    if schema.get("additionalProperties") is False:
        extra = sorted(set(arguments) - set(properties))
        if extra:
            raise ValidationError("INVALID_ARGUMENT", f"unsupported properties: {extra}")
    for key in required:
        if key not in arguments:
            raise ValidationError("INVALID_ARGUMENT", f"missing required property: {key}")
    for key, value in arguments.items():
        spec = properties.get(key)
        if spec is None:
            continue
        expected = spec.get("type")
        if expected == "string":
            if not isinstance(value, str):
                raise ValidationError("INVALID_ARGUMENT", f"{key} must be a string")
            allowed = spec.get("enum")
            if allowed is not None and value not in allowed:
                raise ValidationError("INVALID_ARGUMENT", f"{key} is not an allowed value")
        elif expected == "integer":
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValidationError("INVALID_ARGUMENT", f"{key} must be an integer")
            minimum = spec.get("minimum")
            maximum = spec.get("maximum")
            if minimum is not None and value < minimum:
                raise ValidationError("INVALID_ARGUMENT", f"{key} is below the minimum")
            if maximum is not None and value > maximum:
                raise ValidationError("INVALID_ARGUMENT", f"{key} is above the maximum")
    return arguments

