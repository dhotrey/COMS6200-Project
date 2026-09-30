"""Dry-run runner, run order, and the formal-mode lock."""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from experiments.health import RECOVERY_COMMANDS, ensure_healthy  # noqa: E402
from experiments.order import LLM_ORDER, BASELINE_ORDER, order_mismatch  # noqa: E402
from experiments.prompts import PROMPTS  # noqa: E402
from experiments.runner import (  # noqa: E402
    FORMAL_LAUNCHER_ARMED,
    FORMAL_RUN_PATH,
    PROTOCOL_TOOLS,
    agent_runtime_blockers,
    formal_blockers,
    formal_refused,
    infrastructure_may_retry,
    run_dry_trial,
    toolset_error,
)
from telemetry.schemas import CANONICAL_TOOL_NAMES  # noqa: E402


def test_order_matches_protocol() -> None:
    assert order_mismatch() is None
    assert len(LLM_ORDER) == 40 and len(BASELINE_ORDER) == 40
    assert LLM_ORDER[0] == ("F1", 5)
    assert LLM_ORDER[-1] == ("F2", 8)
    assert BASELINE_ORDER[0] == ("F1", 1)
    assert BASELINE_ORDER[-1] == ("F4", 3)


def test_formal_mode_is_blocked() -> None:
    assert FORMAL_LAUNCHER_ARMED is False
    assert toolset_error() is None
    assert tuple(CANONICAL_TOOL_NAMES) == PROTOCOL_TOOLS
    refused = formal_refused()
    assert "formal collection refused" in refused
    assert "formal launcher is not armed" in refused
    assert "metadata.json is absent" in refused
    blockers = formal_blockers({})
    assert any("approved_model_id" in item for item in blockers)
    assert any("team_approval_recorded" in item for item in blockers)
    assert infrastructure_may_retry(1) is True
    assert infrastructure_may_retry(2) is False
    text = (ROOT / "experiments" / "runner.py").read_text()
    assert "--with-onos" not in text
    assert "runs.jsonl" in text
    assert not FORMAL_RUN_PATH.exists()


def test_live_agent_limit_must_be_protocol() -> None:
    bad = agent_runtime_blockers(
        {
            "max_tool_calls": 10,
            "max_turn_seconds": 300,
            "tool_delay_min_seconds": 0,
            "tool_delay_max_seconds": 0,
        }
    )
    assert any("max_tool_calls" in item for item in bad)
    missing = agent_runtime_blockers(None)
    assert missing == ["live agent config is unavailable"]
    good = agent_runtime_blockers(
        {
            "max_tool_calls": 14,
            "max_turn_seconds": 300,
            "tool_delay_min_seconds": 0,
            "tool_delay_max_seconds": 0,
            "default_model": "gpt-5.6-sol",
            "default_effort": "medium",
        }
    )
    assert good == []
    wrong_model = agent_runtime_blockers(
        {
            "max_tool_calls": 14,
            "max_turn_seconds": 300,
            "tool_delay_min_seconds": 0,
            "tool_delay_max_seconds": 0,
            "default_model": "gpt-5.6-luna",
            "default_effort": "medium",
        }
    )
    assert any("default_model" in item for item in wrong_model)
    refused = formal_refused(
        {"max_tool_calls": 10, "max_turn_seconds": 300,
         "tool_delay_min_seconds": 0, "tool_delay_max_seconds": 0},
        require_agent=True,
    )
    assert "live agent max_tool_calls is not 14" in refused


def test_dry_run_classifies_and_hides_scenario_from_diagnosis() -> None:
    calls = {"diagnose": [], "inject": [], "health": 0}

    def health():
        calls["health"] += 1
        return True, "healthy"

    def inject(scenario):
        calls["inject"].append(scenario)
        return {"ok": True, "data": {"status": "ACTIVE"}}

    def diagnose(prompt):
        calls["diagnose"].append(prompt)
        return {
            "diagnosis_family": "congestion",
            "diagnosis_location": "s1",
            "diagnosis_text": "Congestion somewhere on s1.",
            "tool_calls": [{"sequence": 1, "tool": "ping", "arguments": {}, "ok": True, "elapsed_sec": 0.1}],
            "tool_call_count": 1,
            "elapsed_sec": 1.0,
            "error": None,
        }

    record = run_dry_trial(
        method="baseline",
        scenario="F2",
        kind="unit",
        diagnose_fn=diagnose,
        health_fn=health,
        inject_fn=inject,
        reset_fn=lambda: {"ok": True},
        append=False,
    )
    assert calls["inject"] == ["F2"]
    assert calls["diagnose"] == [PROMPTS["F2"]]
    assert "F2" not in calls["diagnose"][0]
    assert record["formal"] is False
    assert record["label"] == "DRY RUN / NOT FORMAL DATA"
    assert record["outcome"] == "scored"
    assert record["failure_class"] == "diagnostic"
    assert record["family_correct"] == 1
    assert record["location_correct"] == 0
    assert record["include_in_accuracy"] is True
    assert record["attempt"] == 1
    assert record["model"] is None
    assert not FORMAL_RUN_PATH.exists()

    def fail_health():
        return False, "links:0"

    blocked = run_dry_trial(
        method="baseline",
        scenario="F1",
        diagnose_fn=lambda prompt: (_ for _ in ()).throw(AssertionError("diagnosed")),
        health_fn=fail_health,
        inject_fn=lambda scenario: (_ for _ in ()).throw(AssertionError("injected")),
        append=False,
    )
    assert blocked["failure_class"] == "infrastructure"
    assert blocked["include_in_accuracy"] is False
    assert blocked["family_correct"] is None


def test_recovery_commands_leave_onos_up() -> None:
    assert RECOVERY_COMMANDS == (
        ["./scripts/testbed.sh", "stop"],
        ["./scripts/testbed.sh", "start"],
    )
    probes = iter([(False, "down"), (True, "healthy")])
    seen = []

    def recover():
        seen.append("recover")

    ok, detail = ensure_healthy(probe=lambda: next(probes), recover=recover)
    assert seen == ["recover"]
    assert ok and detail == "healthy"


def main() -> int:
    failed = 0
    for check in (
        test_order_matches_protocol,
        test_formal_mode_is_blocked,
        test_live_agent_limit_must_be_protocol,
        test_dry_run_classifies_and_hides_scenario_from_diagnosis,
        test_recovery_commands_leave_onos_up,
    ):
        try:
            check()
            print(f"PASS {check.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {check.__name__}: {type(exc).__name__}: {exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
