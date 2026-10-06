"""Thin CLI over TelemetryGateway. JSON on stdout; diagnostics on stderr."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from topologies.active import HOSTS, SWITCHES, TOPOLOGY

from telemetry.gateway import TelemetryGateway
from telemetry.schemas import schema_list

_HOST_RANGE = f"{HOSTS[0]}-{HOSTS[-1]}"
_SWITCH_RANGE = f"{SWITCHES[0]}-{SWITCHES[-1]}"


def _emit(result: dict[str, Any]) -> int:
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if result.get("ok") else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m telemetry.cli",
        description=(
            f"Bounded structured telemetry for {TOPOLOGY}. "
            f"Hosts: {_HOST_RANGE}. Switches: {_SWITCH_RANGE}. "
            "Does not accept IPs, shell strings, or REST paths."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("get-topology", help="ONOS devices/links plus configured host attachments")

    port_status = sub.add_parser("get-port-status", help="ONOS port status for one switch")
    port_status.add_argument("--switch", required=True, help=_SWITCH_RANGE)

    port_stats = sub.add_parser("get-port-stats", help="ONOS port counters and short bit-rate sample")
    port_stats.add_argument("--switch", required=True, help=_SWITCH_RANGE)

    link = sub.add_parser(
        "get-link-metrics",
        help="Fixed two-second port and queue measurement for one known switch port",
    )
    link.add_argument("--switch", required=True, help=_SWITCH_RANGE)
    link.add_argument("--port", required=True, type=int, help="known port on that switch")

    flows = sub.add_parser("get-flow-table", help="Normalised ONOS flows for one switch")
    flows.add_argument("--switch", required=True, help=_SWITCH_RANGE)

    ping = sub.add_parser("ping", help="Bounded ICMP ping between two project hosts")
    ping.add_argument("--src", required=True, help=_HOST_RANGE)
    ping.add_argument("--dst", required=True, help=_HOST_RANGE)
    ping.add_argument("--count", type=int, default=None, help="1-10, default 3")

    iperf = sub.add_parser("iperf", help="Bounded one-shot iperf3 TCP test")
    iperf.add_argument("--src", required=True, help=_HOST_RANGE)
    iperf.add_argument("--dst", required=True, help=_HOST_RANGE)
    iperf.add_argument("--duration", type=int, default=None, help="1-5 seconds, default 2")

    nmap = sub.add_parser("nmap", help="Bounded one-shot nmap TCP test")
    nmap.add_argument("--src", required=True, help=_HOST_RANGE)
    nmap.add_argument("--dst", required=True, help=_HOST_RANGE)
    nmap.add_argument("--proto", required=True, help="tcp or udp")
    nmap.add_argument("--port", type=int, required=True, help="0-65535")

    sub.add_parser("schemas", help="Print provider-neutral tool schemas as JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "schemas":
        json.dump(schema_list(), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    gateway = TelemetryGateway()
    if args.command == "get-topology":
        return _emit(gateway.get_topology())
    if args.command == "get-port-status":
        return _emit(gateway.get_port_status(args.switch))
    if args.command == "get-port-stats":
        return _emit(gateway.get_port_stats(args.switch))
    if args.command == "get-link-metrics":
        return _emit(gateway.get_link_metrics(args.switch, args.port))
    if args.command == "get-flow-table":
        return _emit(gateway.get_flow_table(args.switch))
    if args.command == "ping":
        return _emit(gateway.ping(args.src, args.dst, count=args.count))
    if args.command == "iperf":
        return _emit(gateway.iperf(args.src, args.dst, duration=args.duration))
    if args.command == "nmap":
        return _emit(gateway.nmap(args.src, args.dst, proto=args.proto, port=args.port))
    parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
