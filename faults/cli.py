"""Operator CLI for M5 fault injection.

This is NOT an LLM/agent tool. Do not expose it through telemetry schemas.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from faults.injector import inject, reset, status


def _emit(result: dict[str, Any]) -> int:
    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if result.get("ok") else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m faults.cli",
        description=(
            "Operator-only fault injector for COMS6200. "
            "Currently only F1 (s3–s1 primary link failure) is runnable. "
            "Does not accept interfaces, commands, PIDs, or REST paths. "
            "Not an LLM tool."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    inject_p = sub.add_parser("inject", help="Inject an allow-listed fault scenario")
    inject_p.add_argument(
        "--scenario",
        required=True,
        choices=["F1"],
        help="Only F1 is implemented",
    )

    sub.add_parser("status", help="Show active fault state / observed F1 interfaces")

    reset_p = sub.add_parser("reset", help="Restore F1 link endpoints and clear state")
    reset_p.add_argument(
        "--force-f1",
        action="store_true",
        help="Restore canonical F1 interfaces even when state is missing",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "inject":
        return _emit(inject(args.scenario))
    if args.command == "status":
        return _emit(status())
    if args.command == "reset":
        return _emit(reset(force_f1=bool(args.force_f1)))
    parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
