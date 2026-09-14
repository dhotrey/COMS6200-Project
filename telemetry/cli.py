"""Thin CLI over TelemetryGateway. JSON on stdout; diagnostics on stderr."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from telemetry.gateway import TelemetryGateway
from telemetry.schemas import schema_list


def _emit(result: dict[str, Any]) -> int:
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if result.get("ok") else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m telemetry.cli",
        description=(
            "Bounded structured telemetry for main6s8h. "
            "Hosts: h1-h8. Switches: s1-s6. "
            "Does not accept IPs, shell strings, or REST paths."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("get-topology", help="ONOS devices/links plus configured host attachments")

    port_status = sub.add_parser("get-port-status", help="ONOS port status for one switch")
    port_status.add_argument("--switch", required=True, help="s1-s6")

    port_stats = sub.add_parser("get-port-stats", help="ONOS port counters and short bit-rate sample")
    port_stats.add_argument("--switch", required=True, help="s1-s6")

    flows = sub.add_parser("get-flow-table", help="Normalised ONOS flows for one switch")
    flows.add_argument("--switch", required=True, help="s1-s6")

    ping = sub.add_parser("ping", help="Bounded ICMP ping between two project hosts")
    ping.add_argument("--src", required=True, help="h1-h8")
    ping.add_argument("--dst", required=True, help="h1-h8")
    ping.add_argument("--count", type=int, default=None, help="1-10, default 3")

    iperf = sub.add_parser("iperf", help="Bounded one-shot iperf3 TCP test")
    iperf.add_argument("--src", required=True, help="h1-h8")
    iperf.add_argument("--dst", required=True, help="h1-h8")
    iperf.add_argument("--duration", type=int, default=None, help="1-5 seconds, default 2")

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
    if args.command == "get-flow-table":
        return _emit(gateway.get_flow_table(args.switch))
    if args.command == "ping":
        return _emit(gateway.ping(args.src, args.dst, count=args.count))
    if args.command == "iperf":
        return _emit(gateway.iperf(args.src, args.dst, duration=args.duration))
    parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
