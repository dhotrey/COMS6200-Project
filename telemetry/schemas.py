"""Provider-neutral JSON schemas for the six M4 diagnostic tools."""

from __future__ import annotations

from typing import Any

from topologies.spec import HOSTS, SWITCHES

_HOST_ENUM = list(HOSTS)
_SWITCH_ENUM = list(SWITCHES)

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
            "Run a bounded one-shot iperf3 TCP throughput test between two project hosts."
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


def schema_list() -> list[dict[str, Any]]:
    return [TOOL_SCHEMAS[name] for name in (
        "get_topology",
        "ping",
        "get_port_status",
        "get_port_stats",
        "get_flow_table",
        "iperf",
    )]


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

