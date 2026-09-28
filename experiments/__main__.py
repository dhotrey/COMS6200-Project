"""Dry-run commands for protocol v1. Formal collection is refused."""

from __future__ import annotations

import argparse
import json
import sys

from experiments.order import order_mismatch
from experiments.prompts import SCENARIOS
from experiments.runner import fetch_agent_config, formal_refused, run_dry_trial


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Protocol v1 dry-run runner")
    sub = parser.add_subparsers(dest="command", required=True)

    dry = sub.add_parser("dry-run", help="One non-formal trial")
    dry.add_argument("--method", choices=("baseline", "llm"), required=True)
    dry.add_argument("--scenario", required=True)
    dry.add_argument("--kind", default="manual")

    paired = sub.add_parser("paired-dry-run", help="One LLM dry run then one baseline dry run")
    paired.add_argument("--scenario", required=True)

    sub.add_parser("check-order", help="Verify shuffle output against protocol v1")
    sub.add_parser("formal", help="Refused until freeze metadata and an armed launcher exist")
    args = parser.parse_args(argv)

    mismatch = order_mismatch()
    if mismatch:
        print(mismatch, file=sys.stderr)
        return 2
    if args.command == "check-order":
        print("run order matches protocol v1")
        return 0
    if args.command == "formal":
        print(formal_refused(fetch_agent_config(), require_agent=True), file=sys.stderr)
        return 2
    scenario = args.scenario.upper()
    if scenario not in SCENARIOS:
        print("scenario must be F1-F5", file=sys.stderr)
        return 2
    if args.command == "dry-run":
        record = run_dry_trial(method=args.method, scenario=scenario, kind=args.kind)
        _print_summary(record)
        return 0 if record.get("outcome") == "scored" else 1
    records = [
        run_dry_trial(method="llm", scenario=scenario, kind="paired-pipeline"),
        run_dry_trial(method="baseline", scenario=scenario, kind="paired-pipeline"),
    ]
    for record in records:
        _print_summary(record)
    return 0 if all(item.get("outcome") == "scored" for item in records) else 1


def _print_summary(record: dict) -> None:
    summary = {
        "label": record.get("label"),
        "method": record.get("method"),
        "scenario": record.get("scenario"),
        "family": record.get("diagnosis_family"),
        "location": record.get("diagnosis_location"),
        "family_correct": record.get("family_correct"),
        "location_correct": record.get("location_correct"),
        "full_diagnosis_correct": record.get("full_diagnosis_correct"),
        "tool_call_count": record.get("tool_call_count"),
        "elapsed_sec": record.get("diagnosis_elapsed_sec"),
        "failure_class": record.get("failure_class"),
        "outcome": record.get("outcome"),
        "error": record.get("error"),
    }
    print(json.dumps(summary))


if __name__ == "__main__":
    raise SystemExit(main())
