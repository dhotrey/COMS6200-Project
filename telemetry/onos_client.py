"""Read-only ONOS REST client with an allow-listed path set.

Credentials come from ONOS_USER / ONOS_PASSWORD. Paths are never taken from
callers. This client has no generic get(user_path) entry point.
"""

from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import quote

DEFAULT_ONOS_URL = "http://127.0.0.1:8181/onos/v1"
_DEVICE_ID_RE = re.compile(r"^of:[0-9a-fA-F]+$")


class OnosError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def credentials_from_env() -> tuple[str, str, str]:
    user = os.environ.get("ONOS_USER", "").strip()
    password = os.environ.get("ONOS_PASSWORD", "")
    url = os.environ.get("ONOS_URL", DEFAULT_ONOS_URL).strip() or DEFAULT_ONOS_URL
    if not user or password == "":
        raise OnosError(
            "ONOS_AUTH_FAILED",
            "ONOS_USER and ONOS_PASSWORD must be set in the environment",
        )
    return user, password, url.rstrip("/")


class OnosClient:
    def __init__(self, url: str, user: str, password: str, timeout_s: float = 10.0) -> None:
        self.url = url.rstrip("/")
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        self._auth = f"Basic {token}"
        self.timeout_s = timeout_s

    @classmethod
    def from_env(cls, timeout_s: float = 10.0) -> "OnosClient":
        user, password, url = credentials_from_env()
        return cls(url, user, password, timeout_s=timeout_s)

    def _get(self, path: str) -> Any:
        url = f"{self.url}/{path.lstrip('/')}"
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "Authorization": self._auth},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                raw = response.read()
                if not raw:
                    return {}
                return json.loads(raw.decode())
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise OnosError("ONOS_AUTH_FAILED", "ONOS REST authentication failed") from exc
            raise OnosError("ONOS_UNAVAILABLE", f"ONOS REST HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise OnosError("ONOS_UNAVAILABLE", "ONOS REST is unreachable") from exc
        except TimeoutError as exc:
            raise OnosError("ONOS_UNAVAILABLE", "ONOS REST timed out") from exc
        except json.JSONDecodeError as exc:
            raise OnosError("PARSE_ERROR", "ONOS REST returned invalid JSON") from exc

    def devices(self) -> list[dict[str, Any]]:
        payload = self._get("devices")
        return list(payload.get("devices") or [])

    def links(self) -> list[dict[str, Any]]:
        payload = self._get("links")
        return list(payload.get("links") or [])

    def device_ports(self, device_id: str) -> list[dict[str, Any]]:
        if not _DEVICE_ID_RE.fullmatch(device_id):
            raise OnosError("INVALID_SWITCH", "internal device id is not an ONOS DPID")
        encoded = quote(device_id, safe=":")
        payload = self._get(f"devices/{encoded}/ports")
        ports = payload.get("ports")
        if ports is None and isinstance(payload.get("device"), dict):
            ports = payload["device"].get("ports")
        return list(ports or [])

    def flows(self) -> list[dict[str, Any]]:
        payload = self._get("flows")
        return list(payload.get("flows") or [])

    def port_statistics(self) -> list[dict[str, Any]]:
        payload = self._get("statistics/ports")
        return list(payload.get("statistics") or [])

    def delta_port_statistics(self) -> list[dict[str, Any]]:
        payload = self._get("statistics/delta/ports")
        return list(payload.get("statistics") or [])
