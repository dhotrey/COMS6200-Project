"""Operator CLI for the selected fault catalogue (F1–F5).

main6s8h: Fault Catalogue v1. ring5s5h and tree5s8h: topology-specific
catalogues (faults/registry.py).

This is NOT an LLM/agent tool. Do not expose it through telemetry schemas.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from faults.injector import inject, reset, status
from faults.registry import ACTIVE

_VERSION = ACTIVE.version if ACTIVE else "none"
_RUNNABLE = sorted(ACTIVE.runnable) if ACTIVE else []


def _emit(result: dict[str, Any]) -> int:
    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if result.get("ok") else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m faults.cli",
        description=(
            f"Operator-only fault injector for COMS6200 fault catalogue "
            f"{_VERSION}. Runnable: {', '.join(_RUNNABLE)}. "
            "Does not accept interfaces, commands, PIDs, rates, or REST paths. "
            "Not an LLM tool."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    inject_p = sub.add_parser("inject", help="Inject an allow-listed fault scenario")
    inject_p.add_argument(
        "--scenario",
        required=True,
        choices=_RUNNABLE,
        help="Allow-listed scenario ID only",
    )

    sub.add_parser("status", help="Show active fault state")

    reset_p = sub.add_parser("reset", help="Reset active fault / recover canonical resources")
    reset_p.add_argument(
        "--force-f1",
        action="store_true",
        help="Restore canonical F1 interfaces even when state is missing",
    )
    reset_p.add_argument(
        "--force-scenario",
        choices=_RUNNABLE,
        default=None,
        help="Recover a named scenario's canonical resources when state is missing",
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
        return _emit(
            reset(
                force_f1=bool(args.force_f1),
                force_scenario=args.force_scenario,
            )
        )
    parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
