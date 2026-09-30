"""Protocol v1 experiment runner.

Dry-run mode records non-formal attempts. Formal mode refuses to start until
the freeze metadata is complete, including team approval of the model id.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from baseline import BASELINE_VERSION
from baseline.diagnose import TIMEOUT_SEC, diagnose
from experiments import SCORING_VERSION
from experiments.evaluator import evaluate
from experiments.health import ensure_healthy
from experiments.order import BASELINE_SEED, LLM_SEED, order_mismatch
from experiments.prompts import FAMILIES, PROMPTS
from telemetry.schemas import CANONICAL_TOOL_NAMES

ROOT = Path(__file__).resolve().parents[1]
DRY_RUN_PATH = ROOT / "evidence" / "experiments" / "protocol-v1" / "dry-runs.jsonl"
FORMAL_RUN_PATH = ROOT / "evidence" / "experiments" / "protocol-v1" / "runs.jsonl"
METADATA_PATH = ROOT / "evidence" / "experiments" / "protocol-v1" / "metadata.json"
PROMPT_PATH = ROOT / "agent" / "prompt.md"

PROTOCOL_TOOLS = (
    "get_topology",
    "ping",
    "nmap",
    "get_port_status",
    "get_port_stats",
    "get_link_metrics",
    "get_flow_table",
    "iperf",
)
DRY_MODEL = "gpt-5.6-sol"
DRY_EFFORT = "medium"
DATASET_LABEL = "DRY RUN / NOT FORMAL DATA"
FORMAL_LAUNCHER_ARMED = False


def toolset_error() -> str | None:
    from agent.tools import TOOLS
    from telemetry.gateway import tool_names
    from telemetry.schemas import schema_list

    names = tuple(CANONICAL_TOOL_NAMES)
    schema_names = tuple(item["name"] for item in schema_list())
    agent_names = tuple(item["name"] for item in TOOLS)
    if names != PROTOCOL_TOOLS or tuple(tool_names()) != PROTOCOL_TOOLS:
        return "canonical tool set does not match the protocol eight"
    if schema_names != PROTOCOL_TOOLS:
        return "schema_list does not match the protocol eight"
    if agent_names != PROTOCOL_TOOLS:
        return "agent tool registry does not match the protocol eight"
    return None


def agent_runtime_blockers(config: dict[str, Any] | None) -> list[str]:
    """Formal preflight against the running agent's reported limits."""
    if not isinstance(config, dict):
        return ["live agent config is unavailable"]
    expected = {
        "max_tool_calls": 14,
        "max_turn_seconds": 300,
        "tool_delay_min_seconds": 0,
        "tool_delay_max_seconds": 0,
    }
    blockers = []
    for key, value in expected.items():
        observed = config.get(key)
        if observed is None or float(observed) != float(value):
            blockers.append(f"live agent {key} is not {value}")
    if config.get("default_model") != "gpt-5.6-sol":
        blockers.append("live agent default_model is not gpt-5.6-sol")
    if config.get("default_effort") != "medium":
        blockers.append("live agent default_effort is not medium")
    return blockers


def fetch_agent_config(base_url: str = "http://127.0.0.1:8000") -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(base_url + "/api/config", timeout=5) as response:
            payload = json.loads(response.read().decode())
    except (OSError, ValueError, TimeoutError):
        return None
    return payload if isinstance(payload, dict) else None


def formal_blockers(metadata: dict[str, Any] | None = None) -> list[str]:
    """Reasons formal collection must not start. Empty only when every gate is met."""
    blockers = []
    mismatch = order_mismatch()
    if mismatch:
        blockers.append(mismatch)
    if toolset_error():
        blockers.append(toolset_error())
    payload = metadata if metadata is not None else _read_metadata()
    if payload is None:
        blockers.append("metadata.json is absent")
        return blockers
    expected = {
        "protocol_version": "v1",
        "reasoning_effort": "medium",
        "max_tool_calls": 14,
        "max_turn_seconds": 300,
        "tool_delay_min": 0,
        "tool_delay_max": 0,
        "baseline_version": BASELINE_VERSION,
        "scoring_version": SCORING_VERSION,
        "llm_seed": LLM_SEED,
        "baseline_seed": BASELINE_SEED,
        "team_approval_recorded": True,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            blockers.append(f"{key} is not {value}")
    if payload.get("approved_model_id") != "gpt-5.6-sol":
        blockers.append("approved_model_id is not gpt-5.6-sol")
    if not payload.get("frozen_git_commit"):
        blockers.append("frozen_git_commit is unset")
    if payload.get("formal_collection") is not False and "formal_collection" in payload:
        # A true flag is still not enough unless the fields above match.
        pass
    head = _git_head()
    if payload.get("frozen_git_commit") and payload.get("frozen_git_commit") != head:
        blockers.append("frozen_git_commit does not match HEAD")
    if _git_dirty():
        blockers.append("working tree is dirty")
    return blockers


def formal_refused(agent_config: dict[str, Any] | None = None, *, require_agent: bool = False) -> str:
    """Formal collection cannot start from this tree.

    Missing freeze metadata blocks it. The launcher also stays disarmed so this
    phase cannot execute the 80-trial matrix even if metadata is later filled in
    by hand. When require_agent is set, the live /api/config limits must be 14,
    300 seconds, and zero tool delay.
    """
    reasons = formal_blockers()
    if require_agent:
        reasons.extend(agent_runtime_blockers(agent_config))
    if not FORMAL_LAUNCHER_ARMED:
        reasons.append("formal launcher is not armed")
    if not reasons:
        return ""
    return "formal collection refused: " + "; ".join(reasons)


def infrastructure_may_retry(attempt: int) -> bool:
    """Protocol allows one infrastructure rerun. Dry-run does not invoke it."""
    return attempt == 1


def run_dry_trial(
    *,
    method: str,
    scenario: str,
    repetition: int | None = None,
    interleave_index: int | None = None,
    kind: str = "baseline-catalogue",
    llm_runner: Any = None,
    diagnose_fn: Any = None,
    health_fn: Any = None,
    inject_fn: Any = None,
    reset_fn: Any = None,
    append: bool = True,
) -> dict[str, Any]:
    """One non-formal trial. The diagnostic method receives the symptom only."""
    if method not in {"baseline", "llm"}:
        raise ValueError("method must be baseline or llm")
    if scenario not in PROMPTS:
        raise ValueError("scenario must be F1-F5")
    mismatch = order_mismatch()
    if mismatch:
        raise RuntimeError(mismatch)
    if toolset_error():
        raise RuntimeError(toolset_error())
    _ensure_lab_credentials()
    prompt = PROMPTS[scenario]
    health = health_fn or ensure_healthy
    started = _now()
    t0 = time.perf_counter()
    before_ok, before_detail = health()
    if not before_ok:
        record = _record(
            method=method,
            scenario=scenario,
            repetition=repetition,
            interleave_index=interleave_index,
            prompt=prompt,
            kind=kind,
            started=started,
            elapsed=round(time.perf_counter() - t0, 3),
            outcome="infrastructure_failure",
            failure_class="infrastructure",
            include=False,
            error=f"healthy gate failed before diagnosis: {before_detail}",
            reset_before=False,
            reset_after=None,
        )
        if append:
            _append(record)
        return record
    injector = inject_fn or _inject
    try:
        injected = injector(scenario)
    except SystemExit:
        injected = {"ok": False}
    if not injected.get("ok"):
        record = _record(
            method=method,
            scenario=scenario,
            repetition=repetition,
            interleave_index=interleave_index,
            prompt=prompt,
            kind=kind,
            started=started,
            elapsed=round(time.perf_counter() - t0, 3),
            outcome="infrastructure_failure",
            failure_class="infrastructure",
            include=False,
            error="scenario inject failed",
            reset_before=True,
            reset_after=None,
        )
        if append:
            _append(record)
        return record
    try:
        if method == "baseline":
            diagnosis = (diagnose_fn or _diagnose_live)(prompt)
        else:
            diagnosis = (llm_runner or _llm_once)(prompt)
    except Exception as exc:  # noqa: BLE001 — infrastructure, not a scored answer
        diagnosis = {"error": type(exc).__name__, "infrastructure": True}
    resetter = reset_fn or _reset
    reset_payload = resetter()
    after_ok, after_detail = health()
    elapsed = round(time.perf_counter() - t0, 3)
    if diagnosis.get("infrastructure"):
        record = _record(
            method=method,
            scenario=scenario,
            repetition=repetition,
            interleave_index=interleave_index,
            prompt=prompt,
            kind=kind,
            started=started,
            elapsed=elapsed,
            outcome="infrastructure_failure",
            failure_class="infrastructure",
            include=False,
            error=str(diagnosis.get("error") or "diagnostic method failed"),
            reset_before=True,
            reset_after=bool(after_ok and reset_payload.get("ok")),
            diagnosis=diagnosis,
        )
        if append:
            _append(record)
        return record
    scored = evaluate(diagnosis, scenario, method=method)
    full = scored.get("full_diagnosis_correct") == 1
    record = _record(
        method=method,
        scenario=scenario,
        repetition=repetition,
        interleave_index=interleave_index,
        prompt=prompt,
        kind=kind,
        started=started,
        elapsed=diagnosis.get("elapsed_sec", elapsed),
        outcome="scored",
        failure_class=None if full else "diagnostic",
        include=True,
        error=diagnosis.get("error"),
        reset_before=True,
        reset_after=bool(after_ok and reset_payload.get("ok")),
        diagnosis=diagnosis,
        scored=scored,
    )
    if not after_ok:
        record["error"] = record.get("error") or f"healthy gate failed after reset: {after_detail}"
    if append:
        _append(record)
    return record


def _record(
    *,
    method: str,
    scenario: str,
    repetition: int | None,
    interleave_index: int | None,
    prompt: str,
    kind: str,
    started: str,
    elapsed: float,
    outcome: str,
    failure_class: str | None,
    include: bool,
    error: str | None,
    reset_before: bool,
    reset_after: bool | None,
    diagnosis: dict[str, Any] | None = None,
    scored: dict[str, Any] | None = None,
) -> dict[str, Any]:
    diagnosis = diagnosis or {}
    scored = scored or {}
    stats = diagnosis.get("stats") or {}
    seed = LLM_SEED if method == "llm" else BASELINE_SEED
    return {
        "experiment_version": "protocol-v1",
        "dataset": "dry-run",
        "label": DATASET_LABEL,
        "dry_run_kind": kind,
        "formal": False,
        "git_commit": _git_head(),
        "git_dirty": _git_dirty(),
        "run_id": uuid.uuid4().hex,
        "attempt": 1,
        "interleave_index": interleave_index,
        "method": method,
        "model": diagnosis.get("model") if method == "llm" else None,
        "reasoning_effort": diagnosis.get("effort") if method == "llm" else None,
        "scenario": scenario,
        "ground_truth_family": FAMILIES[scenario],
        "repetition": repetition,
        "run_order": interleave_index,
        "random_seed": seed,
        "prompt": prompt,
        "prompt_sha256": _prompt_sha(),
        "started_at": started,
        "completed_at": _now(),
        "elapsed_sec": elapsed,
        "diagnosis_elapsed_sec": diagnosis.get("elapsed_sec", elapsed),
        "diagnosis_text": diagnosis.get("diagnosis_text"),
        "diagnosis_family": diagnosis.get("diagnosis_family"),
        "diagnosis_location": diagnosis.get("diagnosis_location"),
        "primary_conclusion_span": scored.get("primary_conclusion_span"),
        "family_correct": scored.get("family_correct"),
        "location_correct": scored.get("location_correct"),
        "full_diagnosis_correct": scored.get("full_diagnosis_correct"),
        "tool_calls": diagnosis.get("tool_calls") or [],
        "tool_call_count": diagnosis.get("tool_call_count"),
        "invalid_tool_calls": stats.get("invalid_tool_calls"),
        "model_calls": stats.get("model_calls"),
        "input_tokens": stats.get("input_tokens"),
        "output_tokens": stats.get("output_tokens"),
        "reasoning_tokens": stats.get("reasoning_tokens"),
        "cached_tokens": stats.get("cached_tokens"),
        "total_tokens": stats.get("total_tokens"),
        "cost_usd": stats.get("cost_usd"),
        "first_token_seconds": stats.get("first_token_seconds"),
        "conversation_id": diagnosis.get("conversation_id"),
        "usage_complete": stats.get("usage_complete"),
        "reset_verified_before": reset_before,
        "reset_verified_after": reset_after,
        "reset_verified": bool(reset_before and reset_after),
        "outcome": outcome,
        "include_in_accuracy": include,
        "failure_class": failure_class,
        "evaluation_error": scored.get("evaluation_error"),
        "error": error,
        "baseline_version": BASELINE_VERSION if method == "baseline" else None,
        "scoring_version": SCORING_VERSION,
    }



def _ensure_lab_credentials() -> None:
    """Use the same lab REST defaults as the healthy gate when the shell has none.

    Values are not printed. A shell that already exported credentials is left as-is.
    """
    os.environ.setdefault("ONOS_USER", "onos")
    os.environ.setdefault("ONOS_PASSWORD", "rocks")


def _diagnose_live(prompt: str) -> dict[str, Any]:
    from telemetry.gateway import TelemetryGateway

    return diagnose(prompt, TelemetryGateway())


def _inject(scenario: str) -> dict[str, Any]:
    from faults.injector import inject

    return inject(scenario)


def _reset() -> dict[str, Any]:
    from faults.injector import reset

    return reset()


def _llm_once(prompt: str, base_url: str = "http://127.0.0.1:8000") -> dict[str, Any]:
    """One new conversation and one turn. Dry-run model only. Not team approval."""
    started = time.perf_counter()
    create = urllib.request.Request(
        base_url + "/api/conversations",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(create, timeout=30) as response:
        created = json.load(response)
    conversation_id = created["id"]
    body = json.dumps(
        {
            "conversation_id": conversation_id,
            "message": prompt,
            "model": DRY_MODEL,
            "effort": DRY_EFFORT,
        }
    ).encode()
    request = urllib.request.Request(
        base_url + "/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    text: list[str] = []
    tools: list[dict[str, Any]] = []
    stats: dict[str, Any] = {}
    error = None
    with urllib.request.urlopen(request, timeout=TIMEOUT_SEC + 30) as response:
        for raw in response:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            event = json.loads(line[5:].strip())
            kind = event.get("type")
            if kind == "text":
                text.append(event.get("text") or "")
            elif kind == "tool_end":
                arguments = event.get("arguments")
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        pass
                tools.append(
                    {
                        "sequence": len(tools) + 1,
                        "tool": event.get("name"),
                        "arguments": arguments,
                        "ok": event.get("ok"),
                        "elapsed_sec": event.get("duration_seconds"),
                        "invalid": event.get("invalid"),
                    }
                )
            elif kind == "stats":
                stats = event.get("stats") or stats
            elif kind == "error":
                error = event.get("message") or "llm error"
            elif kind == "done":
                break
    if error and not text and not stats:
        return {"infrastructure": True, "error": error, "conversation_id": conversation_id}
    return {
        "diagnosis_text": "".join(text).strip(),
        "diagnosis_family": None,
        "diagnosis_location": None,
        "tool_calls": tools,
        "tool_call_count": stats.get("tool_calls", len(tools)),
        "elapsed_sec": stats.get("duration_seconds", round(time.perf_counter() - started, 3)),
        "stats": stats,
        "conversation_id": conversation_id,
        "model": DRY_MODEL,
        "effort": DRY_EFFORT,
        "error": error,
    }


def _append(record: dict[str, Any]) -> None:
    if record.get("formal"):
        raise RuntimeError("dry-run writer refused a formal record")
    DRY_RUN_PATH.parent.mkdir(parents=True, exist_ok=True)
    with DRY_RUN_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    if FORMAL_RUN_PATH.exists():
        raise RuntimeError("formal runs.jsonl must not exist during dry-run")


def _read_metadata() -> dict[str, Any] | None:
    if not METADATA_PATH.exists():
        return None
    payload = json.loads(METADATA_PATH.read_text())
    return payload if isinstance(payload, dict) else None


def _git_head() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return (completed.stdout or "").strip()


def _git_dirty() -> bool:
    completed = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return bool((completed.stdout or "").strip())


def _prompt_sha() -> str | None:
    if not PROMPT_PATH.exists():
        return None
    return hashlib.sha256(PROMPT_PATH.read_bytes()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
