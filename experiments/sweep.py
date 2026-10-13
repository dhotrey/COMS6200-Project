"""Exploratory multi-topology diagnosis sweep (not protocol v1).

A sweep is one directory, evidence/experiments/sweep/<run-id>/. Each ``run``
call runs one round on one topology: every method (the scripted baseline and
each model) on every fault once, in a freshly seeded random order. Calling
``run`` again adds the next round to the same sweep, and ``summary`` pools all
rounds. Every trial is independent (fresh network, new conversation), so N
single-round calls give the same data as one N-round run. Topologies are run
in separate sessions, so alternate them (the runner suggests which is next) to
keep day-to-day differences such as gateway latency from lining up with one
topology.

Trial isolation:

- the network is restarted before every trial (scripts/testbed.sh stop/start),
  so port counters, ARP caches and flow state from earlier trials cannot carry
  over;
- every LLM trial is a new conversation, the gateway response cache is
  bypassed (cf-aig-skip-cache) and nothing is stored provider-side;
- provider prompt caching stays on. It reuses computation for identical
  prompt text and does not change answers; cached tokens are recorded.

Before a round, a preflight sends one tiny request per model with the agent's
real request shape, so a model the gateway rejects fails in seconds.

Each trial runs in its own worker process because the topology is selected at
import time (COMS6200_TOPOLOGY). Scoring uses experiments/sweep_scoring.py
(protocol v1 rubric, locations from each topology's fault catalogue).

Records: plan.json, trials.jsonl, trials/*.json, logs/, summary.md, labelled
EXPLORATORY SWEEP / NOT PROTOCOL V1.

Operator only: it restarts the testbed and injects faults. Run as root with a
Python that has the agent dependencies (see docs/user-guide.md):

  python3 -m experiments.sweep plan
  sudo <agent-venv>/bin/python -m experiments.sweep run --run-id NAME --topology ring5s5h
  python3 -m experiments.sweep summary --run-id NAME
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import random
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from experiments.prompts import PROMPTS, SCENARIOS

ROOT = Path(__file__).resolve().parents[1]
SWEEP_ROOT = ROOT / "evidence" / "experiments" / "sweep"
LABEL = "EXPLORATORY SWEEP / NOT PROTOCOL V1"
TOPOLOGIES = ("main6s8h", "ring5s5h", "tree5s8h")
BASELINE = "baseline"
DEFAULT_TARGET_ROUNDS = 5  # rounds per topology the operator plans to run
DEFAULT_SEED = 6202  # protocol v1 uses 6200 and 6201
DEFAULT_EFFORT = "medium"
# The study's model set: the original evaluation's four plus GPT-4.1 mini and nano.
DEFAULT_MODELS = (
    "gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol", "gpt-6-astra", "gpt-4.1-mini", "gpt-4.1-nano",
)
# Judge binary success, as the rubrics define it (judge/grading.md).
JUDGE_SUCCESS = {"correct", "mostly_correct"}
# Protocol v1 agent limits: 14 tool calls, 300 s per turn, no artificial delay.
LIMITS = {
    "MAX_TOOL_CALLS": "14",
    "MAX_TURN_SECONDS": "300",
    "TOOL_DELAY_MIN_SECONDS": "0",
    "TOOL_DELAY_MAX_SECONDS": "0",
}
FINAL_STATUSES = {"completed", "excluded"}
TRIAL_TIMEOUT_S = 900
TESTBED_TIMEOUT_S = 600
MAX_CONSECUTIVE_EXCLUDED = 3
# Time: measured in the first live round (ring5s5h, 2026-10-12, WSL2), which took 34 min.
# Restart includes the worker start; overhead is gate, inject, reset and judge. Other
# topologies may differ. Tokens: the WSL2 pilots (docs/results/llm-diagnosis.md).
EST_RESTART_S = 18
EST_OVERHEAD_S = 6
EST_DIAGNOSIS_S = {"llm": 40, "baseline": 5}
EST_INPUT_TOKENS = 50_000
EST_CACHED_SHARE = 0.85
EST_OUTPUT_TOKENS = 1_500


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _display(path: Path) -> str:
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


# --------------------------------------------------------------------- plan


def build_config(
    *,
    run_id: str,
    models: list[str],
    efforts: dict[str, str] | None = None,
    seed: int = DEFAULT_SEED,
    scenarios: tuple[str, ...] = SCENARIOS,
    include_baseline: bool = True,
    effort: str = DEFAULT_EFFORT,
    target_rounds: int = DEFAULT_TARGET_ROUNDS,
) -> dict[str, Any]:
    """Sweep settings. Rounds are added later, one topology at a time."""
    unknown = [s for s in scenarios if s not in PROMPTS]
    if unknown:
        raise ValueError(f"unknown scenarios {unknown}")
    methods = ([BASELINE] if include_baseline else []) + list(models)
    if not methods:
        raise ValueError("no methods: give at least one model or keep the baseline")
    efforts = efforts or {}
    return {
        "run_id": run_id,
        "label": LABEL,
        "created_at": _now(),
        "seed": seed,
        "target_rounds": target_rounds,
        "topologies": list(TOPOLOGIES),
        "scenarios": list(scenarios),
        "methods": methods,
        "effort": effort,
        # Effort actually sent per model; models without reasoning use "none".
        "efforts": {model: efforts.get(model, effort) for model in models},
        "limits": dict(LIMITS),
        "prompts": {s: PROMPTS[s] for s in scenarios},
        "isolation": "network restarted before every trial (testbed.sh stop/start)",
        "caching": {
            "gateway_response_cache": "bypassed (cf-aig-skip-cache)",
            "provider_storage": "off (store=false)",
            "provider_prompt_cache": "on (does not change answers; cached tokens recorded)",
            "conversation": "new per trial",
        },
        "rounds": [],
    }


def config_identity(plan: dict[str, Any]) -> dict[str, Any]:
    return {key: plan[key] for key in ("seed", "scenarios", "methods", "efforts")}


def round_trials(plan: dict[str, Any], topology: str, round_number: int) -> list[dict[str, Any]]:
    """One repetition of every method x scenario on one topology, in a seeded random order."""
    cells = [(method, scenario) for method in plan["methods"] for scenario in plan["scenarios"]]
    random.Random(f"{plan['seed']}:{topology}:{round_number}").shuffle(cells)
    trials = []
    for index, (method, scenario) in enumerate(cells, start=1):
        llm = method != BASELINE
        trials.append(
            {
                "trial_id": f"{topology}-r{round_number:02d}-{method}-{scenario}",
                "round": round_number,
                "index": index,
                "topology": topology,
                "scenario": scenario,
                "method": "llm" if llm else "baseline",
                "model": method if llm else None,
                "effort": plan["efforts"][method] if llm else None,
            }
        )
    return trials


def all_trials(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [trial for entry in plan["rounds"] for trial in entry["trials"]]


def topology_rounds(plan: dict[str, Any], topology: str) -> list[dict[str, Any]]:
    return [entry for entry in plan["rounds"] if entry["topology"] == topology]


def completed_rounds(plan: dict[str, Any], finals: dict[str, Any]) -> dict[str, int]:
    counts = {topology: 0 for topology in plan["topologies"]}
    for entry in plan["rounds"]:
        if all(trial["trial_id"] in finals for trial in entry["trials"]):
            counts[entry["topology"]] += 1
    return counts


def suggest_next(plan: dict[str, Any], finals: dict[str, Any], just_ran: str | None) -> str:
    """Topology with the fewest complete rounds; on a tie, the next one after just_ran."""
    counts = completed_rounds(plan, finals)
    order = list(plan["topologies"])
    start = order.index(just_ran) + 1 if just_ran in order else 0
    return min(order[start:] + order[:start], key=lambda topology: counts[topology])


def describe(plan: dict[str, Any], prices: dict[str, tuple[float, float, float]] | None) -> str:
    template = round_trials(plan, plan["topologies"][0], 1)
    round_seconds = sum(EST_RESTART_S + EST_OVERHEAD_S + EST_DIAGNOSIS_S[t["method"]] for t in template)
    total_rounds = plan["target_rounds"] * len(plan["topologies"])
    lines = [
        plan["label"],
        f"Methods:    {', '.join(plan['methods'])}",
        f"Scenarios:  {', '.join(plan['scenarios'])}; seed {plan['seed']}",
        f"One round:  {len(template)} trials on one topology (each method x fault once), "
        f"~{round_seconds / 60:.0f} min including a network restart per trial",
        f"Target:     {plan['target_rounds']} rounds x {len(plan['topologies'])} topologies = "
        f"{len(template) * total_rounds} trials, ~{round_seconds * total_rounds / 3600:.0f} h "
        f"over {total_rounds} sessions",
    ]
    round_cost = 0.0
    for method in plan["methods"]:
        if method == BASELINE:
            continue
        per_trial = estimate_trial_cost((prices or {}).get(method))
        cost = "" if per_trial is None else f", ~${per_trial:.3f}/trial"
        lines.append(f"            {method}: effort {plan['efforts'][method]}{cost}")
        round_cost += (per_trial or 0) * len(plan["scenarios"])
    if prices:
        lines.append(
            f"Model cost: ~${round_cost:.2f} per round, ~${round_cost * total_rounds:.0f} for the target "
            "(pilot-based; real usage is recorded)"
        )
    return "\n".join(lines)


def estimate_trial_cost(price: tuple[float, float, float] | None) -> float | None:
    if price is None:
        return None
    inp, cached, out = price
    fresh = EST_INPUT_TOKENS * (1 - EST_CACHED_SHARE)
    reused = EST_INPUT_TOKENS * EST_CACHED_SHARE
    return (fresh * inp + reused * cached + EST_OUTPUT_TOKENS * out) / 1e6


def model_efforts(effort: str) -> tuple[list[str], dict[str, str], dict[str, tuple[float, float, float]]]:
    """Agent models usable at this effort, the effort each gets, and prices (needs agent deps)."""
    from agent import config

    models: list[str] = []
    efforts: dict[str, str] = {}
    for option in config.MODELS:
        if not option.get("reasoning", True):
            models.append(option["id"])
            efforts[option["id"]] = "none"
        elif effort in option["efforts"]:
            models.append(option["id"])
            efforts[option["id"]] = effort
    return models, efforts, dict(config.PRICES)


def check_models(efforts: dict[str, str]) -> list[str]:
    from agent import config

    problems = []
    for model, effort in efforts.items():
        option = config.model_option(model)
        if not option:
            problems.append(f"{model} is not in agent/config.py MODELS")
        elif effort not in option["efforts"]:
            problems.append(f"{model} does not support effort {effort}")
        if model not in config.PRICES:
            problems.append(f"{model} has no PRICES entry in agent/config.py")
    return problems


def preflight(efforts: dict[str, str]) -> dict[str, str | None]:
    """One tiny turn per model through the agent loop's real request shape.

    Catches a model the gateway or provider rejects (unsupported parameter, no
    access) in seconds instead of mid-sweep. A zero tool budget makes the loop
    send tool_choice "none", so no diagnostic tool runs. A fraction of a cent
    per model.
    """
    from agent import config
    from agent.loop import run

    results: dict[str, str | None] = {}

    async def no_tools(name: str, arguments: str) -> dict[str, Any]:
        raise RuntimeError("the preflight runs no tools")

    async def one(model: str) -> None:
        client = config.make_client()
        state: dict[str, Any] = {"content": "", "tools": [], "stats": {}}
        try:
            history = [{"role": "user", "content": "Reply with the single word OK."}]
            limits = {"max_tool_calls": 0, "max_turn_seconds": 60}
            async for _event in run(client, history, model, efforts[model], state,
                                    tool_executor=no_tools, limits=limits):
                pass
        finally:
            await client.close()

    for model in efforts:
        try:
            asyncio.run(one(model))
            results[model] = None
        except Exception as exc:  # noqa: BLE001 — reported per model
            results[model] = f"{type(exc).__name__}: {str(exc)[:200]}"
    return results


# ------------------------------------------------------------------ records


def run_dir_for(run_id: str) -> Path:
    if not run_id or any(ch in run_id for ch in "/\\") or run_id.startswith("."):
        raise ValueError("run id must be a plain directory name")
    return SWEEP_ROOT / run_id


def load_plan(run_dir: Path) -> dict[str, Any]:
    return json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))


def read_records(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "trials.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def append_record(run_dir: Path, record: dict[str, Any]) -> None:
    with (run_dir / "trials.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def final_records(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Last final record per trial id (earlier attempts stay in the file for audit)."""
    final: dict[str, dict[str, Any]] = {}
    for record in records:
        if record.get("status") in FINAL_STATUSES:
            final[record["trial_id"]] = record
    return final


def summary_record(detail: dict[str, Any]) -> dict[str, Any]:
    """One trials.jsonl line: everything except answers and tool observations."""
    stats = detail.get("stats") or {}
    score = detail.get("score") or {}
    keep = (
        "trial_id", "round", "index", "topology", "scenario", "method", "model", "effort",
        "attempt", "status", "turn_status", "outcome", "reason", "error", "started_at",
        "finished_at", "trial_seconds", "network_restart_s", "catalogue_version", "asks_user",
    )
    record = {key: detail.get(key) for key in keep}
    record.update(
        family_correct=score.get("family_correct"),
        location_correct=score.get("location_correct"),
        gate_ok=(detail.get("gate_before") or {}).get("ok"),
        inject_ok=(detail.get("inject") or {}).get("ok"),
        reset_ok=(detail.get("reset") or {}).get("ok"),
        tool_calls=stats.get("tool_calls"),
        model_calls=stats.get("model_calls"),
        input_tokens=stats.get("input_tokens"),
        cached_tokens=stats.get("cached_tokens"),
        output_tokens=stats.get("output_tokens"),
        reasoning_tokens=stats.get("reasoning_tokens"),
        cost_usd=stats.get("cost_usd"),
        diagnosis_seconds=stats.get("duration_seconds"),
        judge_status=(detail.get("evaluation") or {}).get("status"),
        judge_verdict=(detail.get("evaluation") or {}).get("verdict"),
        judge_cost_usd=(detail.get("evaluation") or {}).get("cost_usd"),
        detail_file=detail.get("detail_file"),
    )
    return record


def spend(record: dict[str, Any]) -> float:
    """Diagnosis plus judge cost of one record (missing usage counts as 0 here)."""
    return float(record.get("cost_usd") or 0) + float(record.get("judge_cost_usd") or 0)


def infrastructure_record(trial: dict[str, Any], attempt: int, reason: str, **extra: Any) -> dict[str, Any]:
    return {
        **trial,
        "attempt": attempt,
        "label": LABEL,
        "status": "infrastructure",
        "reason": reason,
        "started_at": _now(),
        "finished_at": _now(),
        **extra,
    }


# ------------------------------------------------------------- one trial


class TrialHooks(Protocol):
    def topology(self) -> str: ...
    def catalogue_version(self) -> str | None: ...
    def gate(self) -> dict[str, Any]: ...
    def inject(self, scenario: str) -> dict[str, Any]: ...
    def reset(self) -> dict[str, Any]: ...
    def diagnose(self, trial: dict[str, Any], prompt: str) -> dict[str, Any]: ...
    def judge(self, trial: dict[str, Any], prompt: str, answer: str) -> dict[str, Any]: ...


def _envelope_summary(result: dict[str, Any]) -> dict[str, Any]:
    error = result.get("error") or {}
    return {
        "ok": bool(result.get("ok")),
        "status": (result.get("data") or {}).get("status"),
        "code": error.get("code") if isinstance(error, dict) else None,
        "message": error.get("message") if isinstance(error, dict) else error,
    }


def run_trial(
    trial: dict[str, Any],
    prompt: str,
    hooks: TrialHooks,
    *,
    attempt: int = 1,
) -> dict[str, Any]:
    """Gate, inject, one diagnosis, reset, score and judge. The method only sees the prompt."""
    from experiments.sweep_scoring import asks_user, outcome, score

    started = time.perf_counter()
    record: dict[str, Any] = {
        **trial,
        "attempt": attempt,
        "label": LABEL,
        "prompt": prompt,
        "started_at": _now(),
        "catalogue_version": hooks.catalogue_version(),
    }

    def finish(status: str, **fields: Any) -> dict[str, Any]:
        record.update(fields, status=status, finished_at=_now())
        record["trial_seconds"] = round(time.perf_counter() - started, 3)
        return record

    running = hooks.topology()
    if running != trial["topology"]:
        return finish("infrastructure", reason=f"worker topology {running} != {trial['topology']}")
    record["gate_before"] = hooks.gate()
    if not record["gate_before"].get("ok"):
        return finish("infrastructure", reason="healthy gate failed before inject")
    record["inject"] = _envelope_summary(hooks.inject(trial["scenario"]))
    if not record["inject"]["ok"]:
        record["reset"] = _envelope_summary(hooks.reset())
        return finish("infrastructure", reason=f"inject failed: {record['inject']['code']}")
    try:
        result = hooks.diagnose(trial, prompt)
    finally:
        record["reset"] = _envelope_summary(hooks.reset())
    record.update({key: value for key, value in result.items() if key != "status"})
    if result["status"] == "infrastructure":
        return finish("infrastructure", reason=result.get("error") or "diagnosis infrastructure error")
    scored = score(trial["topology"], trial["scenario"], result, method=trial["method"])
    answer = str(result.get("diagnosis_text") or "")
    # The judge grades after the reset: it reads only the answer, never the network.
    evaluation = hooks.judge(trial, prompt, answer)
    return finish(
        "completed", turn_status=result["status"], score=scored, outcome=outcome(scored), evaluation=evaluation,
        asks_user=asks_user(answer) if trial["method"] == "llm" else None,
    )


class LiveHooks:
    """Real testbed, fault injector, agent loop and scripted baseline."""

    def topology(self) -> str:
        from topologies.active import TOPOLOGY

        return TOPOLOGY

    def catalogue_version(self) -> str | None:
        from faults.registry import ACTIVE

        return ACTIVE.version if ACTIVE else None

    def gate(self) -> dict[str, Any]:
        return live_gate()

    def inject(self, scenario: str) -> dict[str, Any]:
        from faults.injector import inject

        return inject(scenario)

    def reset(self) -> dict[str, Any]:
        from faults.injector import reset

        return reset()

    def diagnose(self, trial: dict[str, Any], prompt: str) -> dict[str, Any]:
        if trial["method"] == "baseline":
            return baseline_diagnosis(prompt)
        return llm_diagnosis(prompt, trial["model"], trial["effort"])

    def judge(self, trial: dict[str, Any], prompt: str, answer: str) -> dict[str, Any]:
        return judge_diagnosis(trial["topology"], trial["scenario"], prompt, answer)


def judge_diagnosis(topology: str, scenario: str, prompt: str, answer: str) -> dict[str, Any]:
    """Grade one answer with the agent's LLM judge and the topology/fault rubric.

    The same judge and rubrics as the results page's own benchmarks. An empty
    answer (for example a timeout before any text) is recorded as Incorrect
    without a judge call, and labelled as such.
    """
    from agent import config, judge

    evaluation = judge.prepare({"topology": topology, "scenario": scenario}, prompt, [])
    if evaluation["status"] != "pending":
        return evaluation
    evaluation["answer"] = answer
    if not answer.strip():
        evaluation.update(status="completed", verdict="incorrect", label="Incorrect (no answer)",
                          criteria_text=evaluation["criteria"]["incorrect"], cost_usd=0.0,
                          graded_by="sweep: no diagnosis text")
        return evaluation
    if not config.configured():
        evaluation.update(status="error", error="Cloudflare gateway is not configured in .env")
        return evaluation

    async def grade() -> None:
        client = config.make_judge_client()

        async def keep(_evaluation: dict[str, Any]) -> None:
            return None  # the sweep stores the result itself

        try:
            await judge.evaluate(client, None, None, evaluation, persist=keep)
        finally:
            if client is not None:
                await client.close()

    asyncio.run(grade())
    return evaluation


def live_gate() -> dict[str, Any]:
    """Topology-aware healthy gate (protocol v1 checks, counts from the selected spec)."""
    from faults.injector import status
    from faults.onos_experiment import list_experiment_flows, onos_client
    from forwarding.baseline_forwarding import expected_flow_count, list_baseline_flows, list_devices
    from telemetry.gateway import TelemetryGateway
    from topologies.active import DEVICE_IDS, INTER_SWITCH_LINKS

    detail: dict[str, Any] = {}
    try:
        client = onos_client()
        devices = {item.get("id"): item for item in list_devices(client)}
        detail["of13_devices"] = sum(
            1
            for device_id in DEVICE_IDS.values()
            if (devices.get(device_id) or {}).get("available")
            and ((devices.get(device_id) or {}).get("annotations") or {}).get("protocol") == "OF_13"
        )
        detail["directed_links"] = len(client.get("links").get("links") or [])
        detail["baseline_added"] = sum(
            1 for flow in list_baseline_flows(client) if flow.get("state") == "ADDED"
        )
        detail["experiment_flows"] = len(list_experiment_flows(client))
        fault = status()
        detail["fault_active"] = bool((fault.get("data") or {}).get("active")) or not fault.get("ok")
        ping = TelemetryGateway().ping("h1", "h5", count=2)
        detail["h1_h5_received"] = int((ping.get("data") or {}).get("received", 0)) if ping.get("ok") else 0
    # credentials_from_env() exits instead of raising when ONOS_* are unset.
    except (Exception, SystemExit) as exc:  # noqa: BLE001 — report the class, not credentials
        detail["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        detail["ok"] = False
        return detail
    detail["ok"] = (
        detail["of13_devices"] == len(DEVICE_IDS)
        and detail["directed_links"] == 2 * len(INTER_SWITCH_LINKS)
        and detail["baseline_added"] == expected_flow_count()
        and detail["experiment_flows"] == 0
        and not detail["fault_active"]
        and detail["h1_h5_received"] > 0
    )
    return detail


def baseline_diagnosis(prompt: str) -> dict[str, Any]:
    from baseline.diagnose import diagnose
    from telemetry.gateway import TelemetryGateway

    result = diagnose(prompt, TelemetryGateway())
    trace = result.get("tool_calls") or []
    return {
        "status": "timeout" if result.get("error") == "diagnosis timeout" else "completed",
        "error": result.get("error"),
        "diagnosis_text": result.get("diagnosis_text") or "",
        "diagnosis_family": result.get("diagnosis_family"),
        "diagnosis_location": result.get("diagnosis_location"),
        "evidence": result.get("evidence"),
        "tool_trace": trace,
        # Chat-UI shape (name/arguments/ok), so a published trial's chat shows its calls.
        "tools": [
            {"call_id": f"baseline-{row.get('sequence')}", "name": row.get("tool"),
             "arguments": row.get("arguments"), "ok": row.get("ok"), "duration_seconds": row.get("elapsed_sec")}
            for row in trace
        ],
        "stats": {
            "tool_calls": result.get("tool_call_count"),
            "duration_seconds": result.get("elapsed_sec"),
            "model_calls": 0,
            "cost_usd": 0.0,
            "usage_complete": True,
        },
    }


def _infrastructure_error(exc: BaseException) -> bool:
    """Gateway/network failures are infrastructure; model behaviour is not.

    A 400 after the preflight passed means the provider rejected this
    conversation, for example gpt-3.5-turbo's 16k context overflowing. That is
    the model's own limit and is scored as a failed diagnosis.
    """
    status = re.search(r"status (\d{3})", str(exc))
    if status and int(status.group(1)) in (400, 413):
        return False
    if isinstance(exc, OSError):
        return True
    try:
        import httpx

        if isinstance(exc, httpx.HTTPError):
            return True
    except ImportError:
        pass
    return str(exc).startswith(("Gateway", "Request failed"))


def llm_diagnosis(prompt: str, model: str, effort: str) -> dict[str, Any]:
    """One new conversation, one turn, through the same loop the harness uses."""
    import logfire

    from agent import config
    from agent.loop import run

    if not config.configured():
        return {"status": "infrastructure", "error": "Cloudflare gateway is not configured in .env"}
    logfire.configure(service_name="network-agent-sweep", send_to_logfire="if-token-present", console=False)
    state: dict[str, Any] = {"content": "", "tools": [], "stats": {}}

    async def turn() -> None:
        client = config.make_client()
        try:
            async for _event in run(client, [{"role": "user", "content": prompt}], model, effort, state):
                pass
        finally:
            await client.close()

    status, error = "completed", None
    try:
        asyncio.run(turn())
    except TimeoutError:
        status, error = "timeout", "turn time limit reached"
    except Exception as exc:  # noqa: BLE001 — classified and recorded
        error = f"{type(exc).__name__}: {str(exc)[:300]}"
        status = "infrastructure" if _infrastructure_error(exc) else "model_error"
    tools = state["tools"]
    return {
        "status": status,
        "error": error,
        "diagnosis_text": state["content"].strip(),
        "tool_trace": [
            {
                "sequence": index,
                "tool": tool.get("name"),
                "arguments": tool.get("arguments"),
                "ok": tool.get("ok"),
                "invalid": tool.get("invalid"),
                "seconds": tool.get("duration_seconds"),
            }
            for index, tool in enumerate(tools, start=1)
        ],
        # Full agent tool records (arguments, observations, timings), as the chat UI saves them.
        "tools": tools,
        "stats": state["stats"],
    }


def trial_main(run_dir: Path, trial_id: str, attempt: int, out: Path) -> int:
    plan = load_plan(run_dir)
    trial = next((t for t in all_trials(plan) if t["trial_id"] == trial_id), None)
    if trial is None:
        raise SystemExit(f"unknown trial {trial_id}")
    try:
        detail = run_trial(trial, plan["prompts"][trial["scenario"]], LiveHooks(), attempt=attempt)
    except (Exception, SystemExit) as exc:  # noqa: BLE001 — never lose the attempt
        detail = infrastructure_record(trial, attempt, f"worker error {type(exc).__name__}: {str(exc)[:300]}")
    detail["detail_file"] = _display(out)
    out.write_text(json.dumps(detail, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return 0


# ---------------------------------------------------------- orchestrator


def child_env(topology: str) -> dict[str, str]:
    env = dict(os.environ)
    env.update(LIMITS)
    env["COMS6200_TOPOLOGY"] = topology
    env.setdefault("ONOS_USER", "onos")
    env.setdefault("ONOS_PASSWORD", "rocks")
    env["PYTHONPATH"] = str(ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env


def testbed(command: str, topology: str, log: Path) -> int:
    with log.open("a", encoding="utf-8") as handle:
        handle.write(f"\n===== {_now()} testbed.sh {command} ({topology}) =====\n")
        handle.flush()
        try:
            return subprocess.run(
                [str(ROOT / "scripts" / "testbed.sh"), command],
                cwd=ROOT,
                env=child_env(topology),
                stdout=handle,
                stderr=subprocess.STDOUT,
                timeout=TESTBED_TIMEOUT_S,
                check=False,
            ).returncode
        except subprocess.TimeoutExpired:
            handle.write("testbed.sh timed out\n")
            return 124


def restart_network(run_dir: Path, previous: str | None, topology: str) -> dict[str, Any]:
    """Stop whatever runs (with its own topology so its flows are removed), then start fresh."""
    started = time.perf_counter()
    log = run_dir / "testbed.log"
    stop_rc = testbed("stop", previous or topology, log)
    start_rc = testbed("start", topology, log)
    return {"ok": start_rc == 0, "stop_rc": stop_rc, "start_rc": start_rc, "seconds": round(time.perf_counter() - started, 1)}


def run_worker(python: str, run_dir: Path, trial: dict[str, Any], attempt: int) -> dict[str, Any]:
    out = run_dir / "trials" / f"{trial['trial_id']}.a{attempt}.json"
    log = run_dir / "logs" / f"{trial['trial_id']}.a{attempt}.log"
    command = [
        python, "-m", "experiments.sweep", "trial",
        "--run-dir", str(run_dir), "--trial-id", trial["trial_id"],
        "--attempt", str(attempt), "--out", str(out),
    ]
    with log.open("w", encoding="utf-8") as handle:
        try:
            rc = subprocess.run(
                command, cwd=ROOT, env=child_env(trial["topology"]), stdout=handle,
                stderr=subprocess.STDOUT, timeout=TRIAL_TIMEOUT_S, check=False,
            ).returncode
        except subprocess.TimeoutExpired:
            rc = 124
    if out.is_file():
        return summary_record(json.loads(out.read_text(encoding="utf-8")))
    return infrastructure_record(trial, attempt, f"worker exited {rc} without a record (see {log.name})")


def save_plan(run_dir: Path, plan: dict[str, Any]) -> None:
    (run_dir / "plan.json").write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_trials(
    run_dir: Path,
    pending: list[dict[str, Any]],
    *,
    python: str,
    max_cost_usd: float | None,
    publisher: Any = None,
) -> int:
    """Run trials in order, each on a freshly restarted network. 0, or a stop code."""
    spent = sum(spend(r) for r in read_records(run_dir))
    up: str | None = None
    excluded_in_a_row = 0
    try:
        for number, trial in enumerate(pending, start=1):
            if max_cost_usd is not None and spent >= max_cost_usd:
                print(f"Stopping: spend ${spent:.2f} reached --max-cost-usd {max_cost_usd}. Re-run to continue.")
                return 2
            record: dict[str, Any] = {}
            for attempt in (1, 2):
                restart = restart_network(run_dir, up, trial["topology"])
                up = trial["topology"] if restart["ok"] else None
                if restart["ok"]:
                    record = run_worker(python, run_dir, trial, attempt)
                else:
                    record = infrastructure_record(
                        trial, attempt, "network restart failed (see testbed.log)", network=restart
                    )
                record["network_restart_s"] = restart["seconds"]
                if record["status"] != "infrastructure":
                    break
                if attempt == 1:
                    append_record(run_dir, record)  # keep the failed attempt for audit
            if record["status"] == "infrastructure":
                record["status"] = "excluded"  # one infrastructure rerun, then excluded
            append_record(run_dir, record)
            spent += spend(record)
            if publisher is not None:
                publisher.trial(record)
            if record["status"] == "completed":
                label = f"judge {record.get('judge_verdict') or record.get('judge_status')}, rule {record.get('outcome')}"
                if record.get("asks_user"):
                    label += ", asked user"
            else:
                label = record["status"]
            print(
                f"[{number}/{len(pending)}] {trial['topology']} r{trial['round']} {trial['scenario']} "
                f"{trial['model'] or BASELINE:14} {label} ${spent:.2f}",
                flush=True,
            )
            if record.get("reset_ok") is False:
                print("Stopping: fault reset failed. Inspect the testbed, then re-run to continue.")
                return 3
            excluded_in_a_row = excluded_in_a_row + 1 if record["status"] == "excluded" else 0
            if excluded_in_a_row >= MAX_CONSECUTIVE_EXCLUDED:
                print(f"Stopping: {excluded_in_a_row} trials in a row excluded. Check testbed.log and logs/.")
                return 4
    finally:
        if up is not None:
            testbed("stop", up, run_dir / "testbed.log")
    return 0


def run_topology(
    run_dir: Path,
    plan: dict[str, Any],
    topology: str,
    *,
    rounds: int = 1,
    python: str,
    max_cost_usd: float | None,
    retry_excluded: bool = False,
    round_info: dict[str, Any] | None = None,
    publisher: Any = None,
) -> int:
    """Finish this topology's unfinished trials, or start its next round. Repeat ``rounds`` times."""
    for sub in ("trials", "logs"):
        (run_dir / sub).mkdir(exist_ok=True)
    for _ in range(rounds):
        finals = final_records(read_records(run_dir))
        if retry_excluded:
            finals = {key: value for key, value in finals.items() if value["status"] != "excluded"}
            retry_excluded = False
        pending = [
            trial
            for entry in topology_rounds(plan, topology)
            for trial in entry["trials"]
            if trial["trial_id"] not in finals
        ]
        if pending:
            print(f"Resuming {topology}: {len(pending)} unfinished trial(s)")
        else:
            number = len(topology_rounds(plan, topology)) + 1
            trials = round_trials(plan, topology, number)
            plan["rounds"].append(
                {"topology": topology, "round": number, "created_at": _now(), **(round_info or {}), "trials": trials}
            )
            save_plan(run_dir, plan)
            pending = trials
            print(f"Starting {topology} round {number}: {len(trials)} trials")
        code = run_trials(run_dir, pending, python=python, max_cost_usd=max_cost_usd, publisher=publisher)
        if code:
            return code
    return 0


# ---------------------------------------------------------------- summary


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, centre - half), min(1.0, centre + half))


def _judged(record: dict[str, Any]) -> bool:
    return record.get("status") == "completed" and record.get("judge_status") == "completed"


def _rate(rows: list[dict[str, Any]], *, judge: bool) -> str:
    """`success/scored (rate, 95% Wilson interval) pN`, from the judge or the rule-based score."""
    if judge:
        scored = [r for r in rows if _judged(r)]
        wins = sum(1 for r in scored if r.get("judge_verdict") in JUDGE_SUCCESS)
        partial = sum(1 for r in scored if r.get("judge_verdict") == "partially_correct")
    else:
        scored = [r for r in rows if r.get("status") == "completed"]
        wins = sum(1 for r in scored if r.get("outcome") == "success")
        partial = sum(1 for r in scored if r.get("outcome") == "partial")
    if not scored:
        return "—"
    low, high = wilson(wins, len(scored))
    return f"{wins}/{len(scored)} ({wins / len(scored):.0%}, {low:.0%}–{high:.0%}) p{partial}"


def _agreement(rows: list[dict[str, Any]]) -> str:
    """How often the judge's binary success matches the rule-based success."""
    both = [r for r in rows if _judged(r)]
    if not both:
        return "—"
    same = sum(1 for r in both if (r.get("judge_verdict") in JUDGE_SUCCESS) == (r.get("outcome") == "success"))
    return f"{same}/{len(both)} ({same / len(both):.0%})"


def _asked(rows: list[dict[str, Any]]) -> str:
    """How many completed model answers ended with a question for the user."""
    known = [r for r in rows if r.get("status") == "completed" and r.get("asks_user") is not None]
    if not known:
        return "—"
    asked = sum(1 for r in known if r["asks_user"])
    return f"{asked}/{len(known)} ({asked / len(known):.0%})"


def _mean(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [float(r[key]) for r in rows if r.get(key) is not None]
    return sum(values) / len(values) if values else None


def _fmt(value: float | None, spec: str) -> str:
    return "—" if value is None else format(value, spec)


def _rounds_section(plan: dict[str, Any], finals: dict[str, Any]) -> list[str]:
    counts = completed_rounds(plan, finals)
    lines = ["| Topology | Complete rounds | Started rounds |", "| --- | --- | --- |"]
    for topology in plan["topologies"]:
        started = len(topology_rounds(plan, topology))
        lines.append(f"| {topology} | {counts[topology]} / {plan['target_rounds']} | {started} |")
    commits = {entry.get("git_commit") for entry in plan["rounds"]}
    if len(commits) > 1 or any(entry.get("git_dirty") for entry in plan["rounds"]):
        lines += [
            "",
            "**Warning:** rounds ran on different or uncommitted code "
            f"({', '.join(sorted(str(c)[:8] for c in commits))}); check before pooling.",
        ]
    return lines + [""]


def build_summary(plan: dict[str, Any], records: list[dict[str, Any]]) -> str:
    finals = list(final_records(records).values())
    methods = plan["methods"]

    def by(**want: str) -> list[dict[str, Any]]:
        def method_of(record: dict[str, Any]) -> str:
            return record.get("model") or BASELINE

        return [
            r for r in finals
            if all((method_of(r) if key == "method" else r.get(key)) == value for key, value in want.items())
        ]

    def table(title: str, columns: list[str], cell: Any) -> list[str]:
        out = ["", f"## {title}", "", "| Method | " + " | ".join(columns) + " |",
               "| --- |" + " --- |" * len(columns)]
        for method in methods:
            out.append(f"| {method} | " + " | ".join(cell(method, column) for column in columns) + " |")
        return out

    diagnosis_usd = sum(float(r.get("cost_usd") or 0) for r in records)
    judge_usd = sum(float(r.get("judge_cost_usd") or 0) for r in records)
    lines = [
        f"# Sweep {plan['run_id']}",
        "",
        f"**{plan['label']}.** Not comparable to protocol v1 formal data.",
        "",
        f"Created {plan['created_at']}; seed {plan['seed']}; target {plan['target_rounds']} rounds "
        f"per topology; model efforts {plan['efforts']}; limits {plan['limits']}.",
        f"Isolation: {plan['isolation']}. Caching: {plan['caching']}.",
        "",
        *_rounds_section(plan, final_records(records)),
        f"Trials: {len(finals)} of {len(all_trials(plan))} started so far are final "
        f"({sum(1 for r in finals if r['status'] == 'excluded')} excluded as infrastructure). "
        f"Spend ${diagnosis_usd + judge_usd:.2f} (diagnosis ${diagnosis_usd:.2f}, judge ${judge_usd:.2f}).",
        "",
        "Cells read `success/scored (rate, 95% Wilson interval) pN`. **Judge (primary):** the agent's LLM "
        "judge with the topology/fault rubric (`judge/`); success = Correct or Mostly correct, pN = Partially "
        "correct. **Rule-based (cross-check):** the protocol v1 keyword rubric; pN = type or location only.",
    ]
    all_column = "All"
    lines += table("Judge: success by method and topology", [*plan["topologies"], all_column],
                   lambda m, c: _rate(by(method=m) if c == all_column else by(method=m, topology=c), judge=True))
    lines += table("Judge: success by method and scenario (all topologies)", plan["scenarios"],
                   lambda m, s: _rate(by(method=m, scenario=s), judge=True))
    for topology in plan["topologies"]:
        lines += table(f"Judge: {topology}", plan["scenarios"],
                       lambda m, s, t=topology: _rate(by(method=m, topology=t, scenario=s), judge=True))
    lines += table("Ended by asking the user", [*plan["topologies"], all_column],
                   lambda m, c: _asked(by(method=m) if c == all_column else by(method=m, topology=c)))
    lines += ["", "Model answers whose last paragraph asks the user a question (for example \"Would you like "
              "me to proceed?\"). A trial is one turn, so the question is never answered; these answers usually "
              "stop before a diagnosis and are judged Incorrect."]
    lines += table("Rule-based cross-check by method and topology", [*plan["topologies"], all_column],
                   lambda m, c: _rate(by(method=m) if c == all_column else by(method=m, topology=c), judge=False))
    lines += ["", "The rule-based score reads one paragraph, picked by the protocol v1 heuristic: the last one "
              "with a conclusion cue (such as \"therefore\") or a fault keyword. In free-form answers that is "
              "often a side or next-step paragraph, so it can fail answers the judge rightly passes. Treat it "
              "as a coarse check."]
    lines += table("Judge vs rule-based agreement (binary success)", [*plan["topologies"], all_column],
                   lambda m, c: _agreement(by(method=m) if c == all_column else by(method=m, topology=c)))
    lines += ["", "## Usage per completed trial (mean)", "",
              "| Method | Trials | Tool calls | Input tokens | Cached share | Output tokens | Diagnosis USD | "
              "Judge USD | Diagnosis s |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for method in methods:
        rows = [r for r in by(method=method) if r.get("status") == "completed"]
        if not rows:
            continue
        inputs, cached = _mean(rows, "input_tokens"), _mean(rows, "cached_tokens")
        share = cached / inputs if inputs and cached is not None else None
        lines.append(
            f"| {method} | {len(rows)} | {_fmt(_mean(rows, 'tool_calls'), '.1f')} | {_fmt(inputs, '.0f')} | "
            f"{_fmt(share, '.0%')} | {_fmt(_mean(rows, 'output_tokens'), '.0f')} | "
            f"{_fmt(_mean(rows, 'cost_usd'), '.4f')} | {_fmt(_mean(rows, 'judge_cost_usd'), '.4f')} | "
            f"{_fmt(_mean(rows, 'diagnosis_seconds'), '.1f')} |"
        )
    return "\n".join(lines) + "\n"


def _with_asks_user(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Records written before the asks_user field: work it out from the saved answer."""
    from experiments.sweep_scoring import asks_user

    for record in records:
        if "asks_user" in record or record.get("method") != "llm" or record.get("status") != "completed":
            continue
        if not record.get("detail_file"):
            continue
        try:
            detail = json.loads((ROOT / record["detail_file"]).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        record["asks_user"] = asks_user(str(detail.get("diagnosis_text") or ""))
    return records


def write_summary(run_dir: Path) -> Path:
    path = run_dir / "summary.md"
    path.write_text(build_summary(load_plan(run_dir), _with_asks_user(read_records(run_dir))), encoding="utf-8")
    return path


# -------------------------------------------------------------------- CLI


def _config_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--models", nargs="+", help="model ids (default: the study set, DEFAULT_MODELS)")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--scenarios", nargs="+", default=list(SCENARIOS), choices=SCENARIOS)
    parser.add_argument("--no-baseline", action="store_true", help="models only")
    parser.add_argument("--effort", default=DEFAULT_EFFORT, help="reasoning effort for models that reason")
    parser.add_argument(
        "--target-rounds", type=int, default=DEFAULT_TARGET_ROUNDS,
        help="rounds per topology you plan to run (progress and estimate only)",
    )


def _make_config(args: argparse.Namespace, run_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        _, efforts, prices = model_efforts(args.effort)
    except ImportError:
        print("Note: without the agent dependencies, per-model efforts and prices are not shown.")
        efforts, prices = {}, {}
    models = list(args.models or DEFAULT_MODELS)
    plan = build_config(
        run_id=run_id, models=models, efforts=efforts, seed=args.seed,
        scenarios=tuple(args.scenarios), include_baseline=not args.no_baseline,
        effort=args.effort, target_rounds=args.target_rounds,
    )
    return plan, prices


def ui_benchmark_active(url: str = "http://127.0.0.1:8000/api/benchmarks/config") -> str | None:
    """Id of a benchmark the agent UI is running on the same testbed, if any."""
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return json.load(response).get("active_id")
    except Exception:  # noqa: BLE001 — server not running or unreachable
        return None


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False).stdout.strip()
    except OSError:
        return ""


def _round_info(topology: str, checks: dict[str, str | None]) -> dict[str, Any]:
    from faults.registry import CATALOGUES

    return {
        "git_commit": _git("rev-parse", "HEAD"),
        "git_dirty": bool(_git("status", "--porcelain")),
        "system_prompt_sha256": hashlib.sha256((ROOT / "agent" / "prompt.md").read_bytes()).hexdigest(),
        "catalogue_version": CATALOGUES[topology].version,
        "preflight": checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m experiments.sweep", description=LABEL)
    sub = parser.add_subparsers(dest="command", required=True)
    plan_p = sub.add_parser("plan", help="print one round's size and a time/cost estimate")
    _config_args(plan_p)
    run_p = sub.add_parser("run", help="run the next round on one topology (or resume it); needs root")
    run_p.add_argument("--run-id", required=True)
    run_p.add_argument("--topology", required=True, choices=TOPOLOGIES)
    run_p.add_argument("--rounds", type=int, default=1, help="rounds to run now on this topology")
    _config_args(run_p)
    run_p.add_argument("--max-cost-usd", type=float, default=100.0, help="stop once total sweep spend reaches this")
    run_p.add_argument("--retry-excluded", action="store_true", help="rerun this topology's excluded trials first")
    run_p.add_argument("--skip-preflight", action="store_true")
    run_p.add_argument("--python", default=sys.executable, help="worker interpreter (needs agent deps)")
    run_p.add_argument("--no-publish", action="store_true", help="do not upload to the results page (D1)")
    summary_p = sub.add_parser("summary", help="rewrite and print summary.md")
    summary_p.add_argument("--run-id", required=True)
    publish_p = sub.add_parser("publish", help="upload (again) every final trial to the results page")
    publish_p.add_argument("--run-id", required=True)
    trial_p = sub.add_parser("trial", help=argparse.SUPPRESS)
    trial_p.add_argument("--run-dir", type=Path, required=True)
    trial_p.add_argument("--trial-id", required=True)
    trial_p.add_argument("--attempt", type=int, default=1)
    trial_p.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.command == "trial":
        return trial_main(args.run_dir, args.trial_id, args.attempt, args.out)
    if args.command == "summary":
        print(write_summary(run_dir_for(args.run_id)).read_text(encoding="utf-8"))
        return 0
    if args.command == "plan":
        plan, prices = _make_config(args, "preview")
        print(describe(plan, prices))
        return 0
    if args.command == "publish":
        from experiments.sweep_publish import publish_all

        count, errors = publish_all(run_dir_for(args.run_id))
        print(f"Published {count} trial(s) to the results page" + (f"; {len(errors)} failed:" if errors else "."))
        for error in errors:
            print(f"  {error}")
        return 1 if errors else 0

    if os.geteuid() != 0:
        print("ERROR: run needs root (testbed restarts, fault injection, Mininet namespaces).")
        return 1
    if args.rounds < 1:
        print("ERROR: --rounds must be at least 1")
        return 1
    busy = ui_benchmark_active()
    if busy:
        print(f"ERROR: the agent UI is running benchmark {busy} on the testbed. Wait for it or stop it first.")
        return 1
    plan, prices = _make_config(args, args.run_id)
    problems = check_models(plan["efforts"])
    if problems:
        print("ERROR: " + "; ".join(problems))
        return 1
    run_dir = run_dir_for(args.run_id)
    if (run_dir / "plan.json").is_file():
        existing = load_plan(run_dir)
        if config_identity(existing) != config_identity(plan):
            print(
                f"ERROR: {args.run_id} was created with different models, efforts, scenarios or seed; "
                "use the same options or a new --run-id."
            )
            return 1
        plan = existing
    else:
        run_dir.mkdir(parents=True, exist_ok=True)
        plan["prices"] = {m: prices.get(m) for m in plan["efforts"]}
        save_plan(run_dir, plan)
    print(describe(plan, prices))

    checks: dict[str, str | None] = {}
    if plan["efforts"] and not args.skip_preflight:
        print("Preflight: one tiny request per model (no tools run)")
        checks = preflight(plan["efforts"])
        for model, error in checks.items():
            print(f"  {model:14} {'ok' if error is None else error}")
        failed = sorted(model for model, error in checks.items() if error)
        if failed:
            print(
                f"ERROR: preflight failed for {', '.join(failed)}. Fix agent/config.py, or start a new "
                "--run-id with --models leaving them out."
            )
            return 1

    publisher = None
    if not args.no_publish:
        from experiments.sweep_publish import Publisher

        publisher = Publisher(run_dir, plan)
        publisher.start()
    try:
        code = run_topology(
            run_dir, plan, args.topology, rounds=args.rounds, python=args.python,
            max_cost_usd=args.max_cost_usd, retry_excluded=args.retry_excluded,
            round_info=_round_info(args.topology, checks), publisher=publisher,
        )
    finally:
        if publisher is not None:
            publisher.finish()
    write_summary(run_dir)
    finals = final_records(read_records(run_dir))
    counts = completed_rounds(plan, finals)
    print("Complete rounds: " + ", ".join(f"{t} {counts[t]}/{plan['target_rounds']}" for t in plan["topologies"]))
    if code == 0:
        print(f"Next suggested topology: {suggest_next(plan, finals, args.topology)}")
    print(f"Summary: {_display(run_dir / 'summary.md')}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
