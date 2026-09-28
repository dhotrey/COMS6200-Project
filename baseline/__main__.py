"""Run one baseline diagnosis from a symptom string. No scenario argument."""

from __future__ import annotations

import argparse
import json

from baseline.diagnose import diagnose
from telemetry.gateway import TelemetryGateway


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deterministic troubleshooting baseline")
    parser.add_argument("--prompt", required=True, help="Symptom text only")
    args = parser.parse_args(argv)
    result = diagnose(args.prompt, TelemetryGateway())
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
