"""Input allow-lists and topology helpers for telemetry."""

from __future__ import annotations

from topologies.spec import HOSTS, HOST_ATTACHMENTS, PRIMARY_IPV4, SWITCHES


class ValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def require_host(name: object) -> str:
    if not isinstance(name, str) or name not in HOSTS:
        raise ValidationError("INVALID_HOST", f"host must be one of {list(HOSTS)}")
    return name


def require_switch(name: object) -> str:
    if not isinstance(name, str) or name not in SWITCHES:
        raise ValidationError("INVALID_SWITCH", f"switch must be one of {list(SWITCHES)}")
    return name


def require_count(value: object, default: int = 3) -> int:
    if value is None:
        return default
    if not isinstance(value, int) or isinstance(value, bool) or value < 1 or value > 10:
        raise ValidationError("INVALID_ARGUMENT", "count must be an integer from 1 to 10")
    return value


def require_duration(value: object, default: int = 2) -> int:
    if value is None:
        return default
    if not isinstance(value, int) or isinstance(value, bool) or value < 1 or value > 5:
        raise ValidationError("INVALID_ARGUMENT", "duration must be an integer from 1 to 5")
    return value


def primary_ip(host: str) -> str:
    require_host(host)
    return PRIMARY_IPV4[host]


def host_attachments() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in HOST_ATTACHMENTS:
        rows.append(
            {
                "host": item.host,
                "switch": item.switch,
                "switch_port": item.switch_port,
                "host_intf": item.host_intf,
                "mac": item.mac,
                "ipv4": item.ipv4,
                "role": item.role,
                "source": "configured",
            }
        )
    return rows
