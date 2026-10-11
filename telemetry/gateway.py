"""TelemetryGateway: the only agent-facing diagnostic implementation."""

from __future__ import annotations

import time
from typing import Any

from topologies import active

from telemetry import envelope
from telemetry.host_exec import HostExecError, run_in_host, start_in_host, terminate
from telemetry.onos_client import OnosClient, OnosError
from telemetry.link_metrics import (
    LINK_SAMPLE_SEC,
    build_link_metrics,
    interface_name,
    parse_qdisc_counters,
    read_iface_counters,
    read_qdisc_text,
    require_switch_port,
)
from telemetry.parsers import (
    configured_inter_switch_links,
    normalize_devices,
    normalize_flows,
    normalize_port_stats,
    normalize_ports,
    parse_iperf,
    parse_nmapXML,
    parse_ping,
    physical_links_from_onos,
)
from telemetry.validate import (
    ValidationError,
    host_attachments,
    primary_ip,
    require_count,
    require_duration,
    require_host,
    require_switch,
    require_match,
    require_range,
)

IPERF_PORT = 5201
STATS_INTERVAL_SEC = 1.0


class TelemetryGateway:
    """Bounded structured diagnostics over ONOS REST and Mininet host namespaces."""

    def __init__(
        self,
        client: OnosClient | None = None,
        stats_interval_sec: float = STATS_INTERVAL_SEC,
        link_sample_sec: float = LINK_SAMPLE_SEC,
    ) -> None:
        self._client = client
        self.stats_interval_sec = stats_interval_sec
        self.link_sample_sec = link_sample_sec

    def _onos(self) -> OnosClient:
        if self._client is None:
            self._client = OnosClient.from_env()
        return self._client

    def _fail(self, tool: str, exc: Exception) -> dict[str, Any]:
        if isinstance(exc, ValidationError):
            return envelope.error(tool, exc.code, exc.message)
        if isinstance(exc, (OnosError, HostExecError)):
            return envelope.error(tool, exc.code, exc.message)
        return envelope.error(tool, "INTERNAL_ERROR", "tool failed")

    def get_topology(self) -> dict[str, Any]:
        tool = "get_topology"
        try:
            devices = normalize_devices(self._onos().devices())
            observed_links = physical_links_from_onos(self._onos().links())
            configured_links = configured_inter_switch_links()
            attachments = host_attachments()
            data = {
                "switches": devices,
                "links": observed_links,
                "configured_inter_switch_links": configured_links,
                "host_attachments": attachments,
                "summary": {
                    "switches": len(active.SWITCHES),
                    "observed_switches": len(devices),
                    "physical_inter_switch_links": len(observed_links),
                    "configured_inter_switch_links": len(configured_links),
                    "configured_host_attachments": len(attachments),
                    "logical_hosts": len(active.HOSTS),
                    "total_physical_links": len(configured_links) + len(attachments),
                    "onos_host_discovery": "not_used",
                },
            }
            return envelope.ok(tool, data)
        except Exception as exc:  # noqa: BLE001 — envelope must never raise
            return self._fail(tool, exc)

    def get_port_status(self, sw: object) -> dict[str, Any]:
        tool = "get_port_status"
        try:
            switch = require_switch(sw)
            ports = self._onos().device_ports(active.DEVICE_IDS[switch])
            return envelope.ok(
                tool,
                {"switch": switch, "ports": normalize_ports(switch, ports)},
            )
        except Exception as exc:  # noqa: BLE001
            return self._fail(tool, exc)

    def get_port_stats(self, sw: object) -> dict[str, Any]:
        tool = "get_port_stats"
        try:
            switch = require_switch(sw)
            client = self._onos()
            first = client.port_statistics()
            time.sleep(self.stats_interval_sec)
            second = client.port_statistics()
            try:
                delta = client.delta_port_statistics()
            except OnosError:
                delta = []
            data = normalize_port_stats(
                switch,
                active.DEVICE_IDS[switch],
                first,
                second,
                self.stats_interval_sec,
                delta=delta,
            )
            return envelope.ok(tool, data)
        except Exception as exc:  # noqa: BLE001
            return self._fail(tool, exc)


    def get_link_metrics(self, sw: object, port: object) -> dict[str, Any]:
        tool = "get_link_metrics"
        try:
            switch, number = require_switch_port(sw, port)
            iface = interface_name(switch, number)
            enabled = self._port_enabled(switch, number)
            before_iface = read_iface_counters(iface)
            before_queue = parse_qdisc_counters(read_qdisc_text(iface) or "")
            started = time.perf_counter()
            time.sleep(self.link_sample_sec)
            interval = round(time.perf_counter() - started, 3)
            after_iface = read_iface_counters(iface)
            after_queue = parse_qdisc_counters(read_qdisc_text(iface) or "")
            data = build_link_metrics(
                switch,
                number,
                enabled,
                interval,
                before_iface,
                after_iface,
                before_queue,
                after_queue,
            )
            return envelope.ok(tool, data)
        except Exception as exc:  # noqa: BLE001
            return self._fail(tool, exc)

    def _port_enabled(self, switch: str, port: int) -> bool | None:
        try:
            rows = normalize_ports(switch, self._onos().device_ports(active.DEVICE_IDS[switch]))
        except OnosError:
            return None
        for row in rows:
            if row.get("port") != port:
                continue
            enabled = row.get("enabled")
            return enabled if isinstance(enabled, bool) else None
        return None

    def get_flow_table(self, sw: object) -> dict[str, Any]:
        tool = "get_flow_table"
        try:
            switch = require_switch(sw)
            flows = normalize_flows(switch, active.DEVICE_IDS[switch], self._onos().flows())
            return envelope.ok(tool, {"switch": switch, "count": len(flows), "flows": flows})
        except Exception as exc:  # noqa: BLE001
            return self._fail(tool, exc)

    def ping(self, src: object, dst: object, count: object = None) -> dict[str, Any]:
        tool = "ping"
        try:
            left = require_host(src)
            right = require_host(dst)
            packets = require_count(count)
            ip = primary_ip(right)
            completed = run_in_host(
                left,
                ["ping", "-n", "-c", str(packets), "-W", "1", ip],
                timeout_s=max(8.0, packets * 2.0 + 3.0),
            )
            output = (completed.stdout or "") + "\n" + (completed.stderr or "")
            try:
                parsed = parse_ping(output)
            except ValueError:
                return envelope.error(
                    tool,
                    "PARSE_ERROR",
                    "could not parse ping output",
                    {"returncode": completed.returncode},
                )
            parsed.update({"src": left, "dst": right, "dst_ip": ip})
            return envelope.ok(tool, parsed)
        except Exception as exc:  # noqa: BLE001
            return self._fail(tool, exc)

    def iperf(self, src: object, dst: object, duration: object = None) -> dict[str, Any]:
        tool = "iperf"
        server = None
        right: str | None = None
        try:
            left = require_host(src)
            right = require_host(dst)
            seconds = require_duration(duration)
            ip = primary_ip(right)
            server = start_in_host(
                right,
                ["iperf3", "-s", "-1", "-J", "-p", str(IPERF_PORT)],
            )
            time.sleep(0.4)
            if server.poll() is not None:
                stderr = (server.stderr.read() if server.stderr else "") or ""
                return envelope.error(
                    tool,
                    "IPERF_SERVER_FAILED",
                    "iperf3 server exited before the client started",
                    {"stderr": stderr[-300:]},
                )
            completed = run_in_host(
                left,
                ["iperf3", "-c", ip, "-t", str(seconds), "-J", "-p", str(IPERF_PORT)],
                timeout_s=float(seconds) + 8.0,
            )
            terminate(server)
            server = None
            output = completed.stdout or ""
            try:
                parsed = parse_iperf(output)
            except ValueError as exc:
                return envelope.error(tool, "PARSE_ERROR", str(exc)[:200])
            parsed.update({"src": left, "dst": right, "dst_ip": ip})
            return envelope.ok(tool, parsed)
        except Exception as exc:  # noqa: BLE001
            return self._fail(tool, exc)
        finally:
            if server is not None:
                terminate(server)
            if right is not None:
                _stop_host_iperf(right)

    def nmap(self, src: object, dst: object, proto: object, port: object) -> dict[str, Any]:
        tool = "nmap"
        protos = {
            "tcp": "-sT",
            "udp": "-sU",
        }
        try:
            left = require_host(src)
            right = require_host(dst)
            proto = require_match(proto, "proto", protos.keys())
            port = require_range(port, "port", 0, 65535)
            ip = primary_ip(right)
            # nmap with xml output to stdout, no ping, host timeout 5s (3 retries default), total timeout 20s
            completed = run_in_host(
                left,
                ["nmap", "-oX", "-", "-Pn", "-p", str(port), protos[proto], ip, "--host-timeout", "5s"],
                timeout_s=20.0,
            )
            output = (completed.stdout or "") + "\n" + (completed.stderr or "")
            try:
                parsed = parse_nmapXML(output)
            except ValueError:
                return envelope.error(
                    tool,
                    "PARSE_ERROR",
                    "could not parse nmap output",
                    {"returncode": completed.returncode},
                )
            parsed.update({"src": left, "dst": right, "dst_ip": ip})
            return envelope.ok(tool, parsed)
        except Exception as exc:  # noqa: BLE001
            return self._fail(tool, exc)

def _stop_host_iperf(host: str) -> None:
    """Best-effort: stop leftover gateway iperf3 (port IPERF_PORT only).

    Mininet hosts share the root PID namespace, so an unscoped ``pkill -x iperf3``
    would also stop unrelated iperf3 processes on other ports, such as operator
    cross-traffic that the diagnostic is meant to observe.
    """
    try:
        run_in_host(
            host,
            ["pkill", "-f", f"^(.*/)?iperf3 .*-p {IPERF_PORT}$"],
            timeout_s=2.0,
        )
    except HostExecError:
        return


def tool_names() -> tuple[str, ...]:
    from telemetry.schemas import CANONICAL_TOOL_NAMES

    return CANONICAL_TOOL_NAMES
