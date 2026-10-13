"""Publish a command-line sweep to the agent's D1 benchmark tables.

The results page (agent/results.html) then shows the sweep beside the UI's
own benchmarks: one run with mode "sweep", the scripted baseline as a
"Scripted baseline" section, each round as a trial, and each attempted trial
as a chat (Open chat). The local evidence files stay the source of truth;
``python3 -m experiments.sweep publish`` repeats the upload after a D1 failure.

Needs the agent dependencies and the D1 credentials in .env.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from experiments import sweep

BASELINE_VARIANT = {"model": "scripted-baseline", "label": "Scripted baseline", "effort": "none",
                    "deprecated": False}
_NAMESPACE = uuid.UUID("5d9f6b2e-7c1a-4f0e-9a51-3b6c2d8e4f10")


def d1_run_id(plan: dict[str, Any]) -> str:
    return f"sweep-{plan['run_id']}"


def variants(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Results-page sections, in plan order."""
    from agent import config

    rows = []
    for method in plan["methods"]:
        if method == sweep.BASELINE:
            rows.append(dict(BASELINE_VARIANT))
            continue
        option = config.model_option(method)
        rows.append({"model": method, "label": option.get("label", method), "effort": plan["efforts"][method],
                     "deprecated": option.get("deprecated", False)})
    return rows


def variant_key(trial: dict[str, Any]) -> tuple[str, str]:
    if trial.get("method") == "baseline" or not trial.get("model"):
        return BASELINE_VARIANT["model"], BASELINE_VARIANT["effort"]
    return trial["model"], trial["effort"]


def matrix_id(topology: str, scenario: str, model: str, effort: str) -> str:
    """The results page's matrix cell id."""
    return f"{topology}:{scenario}:{model}:{effort}"


def trial_cell_id(topology: str, scenario: str, model: str, effort: str, trial: int) -> str:
    return f"{matrix_id(topology, scenario, model, effort)}:trial:{trial}"


def _rounds(plan: dict[str, Any]) -> dict[str, int]:
    return {t: max(plan["target_rounds"], len(sweep.topology_rounds(plan, t))) for t in plan["topologies"]}


def planned_cells(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Pending rows for the target rounds, plus any extra rounds already started."""
    rows = variants(plan)
    cells = []
    for topology, rounds in _rounds(plan).items():
        for scenario in plan["scenarios"]:
            for variant in rows:
                model, effort = variant["model"], variant["effort"]
                for trial in range(1, rounds + 1):
                    cells.append({
                        "id": trial_cell_id(topology, scenario, model, effort, trial),
                        "matrix_cell_id": matrix_id(topology, scenario, model, effort),
                        "trial": trial, "topology": topology, "scenario": scenario,
                        "model": model, "effort": effort, "status": "pending",
                    })
    return cells


def run_payload(plan: dict[str, Any], records: list[dict[str, Any]], status: str) -> dict[str, Any]:
    from agent import topology_control

    finals = sweep.final_records(records)
    system_prompt = (sweep.ROOT / "agent" / "prompt.md").read_text(encoding="utf-8")
    cells = planned_cells(plan)
    return {
        "id": d1_run_id(plan),
        "status": status,
        "mode": "sweep",
        "started_at": plan["created_at"],
        "variants": variants(plan),
        "topologies": [dict(t) for t in topology_control.TOPOLOGIES if t["id"] in plan["topologies"]],
        "scenarios": plan["scenarios"],
        "prompts": plan["prompts"],
        "concurrency": 1,
        "repeats": max(_rounds(plan).values()),
        "limits": plan["limits"],
        "prices": plan.get("prices"),
        "system_prompt": system_prompt,
        "prompt_sha256": hashlib.sha256(system_prompt.encode()).hexdigest(),
        "cell_count": len({c["matrix_cell_id"] for c in cells}),
        "total": len(cells),
        "finished": len(finals),
        "spend_usd": round(sum(sweep.spend(r) for r in records), 4),
        "sweep": {
            "run_id": plan["run_id"], "label": plan["label"], "seed": plan["seed"],
            "target_rounds": plan["target_rounds"], "efforts": plan["efforts"],
            "isolation": plan["isolation"], "caching": plan["caching"],
            "complete_rounds": sweep.completed_rounds(plan, finals),
        },
    }


def _detail(record: dict[str, Any]) -> dict[str, Any]:
    path = record.get("detail_file")
    if path:
        file = Path(path) if Path(path).is_absolute() else sweep.ROOT / path
        if file.is_file():
            return json.loads(file.read_text(encoding="utf-8"))
    return record


def trial_cell(plan: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any]:
    """One results-page trial row from a final sweep record."""
    model, effort = variant_key(detail)
    topology, scenario, trial = detail["topology"], detail["scenario"], detail["round"]
    evaluation = detail.get("evaluation")
    if detail.get("status") == "completed" and (evaluation or {}).get("status") == "completed":
        status, error = "completed", None
    elif detail.get("status") == "completed":
        status, error = "error", (evaluation or {}).get("error") or "The judge did not grade this trial."
    else:
        status, error = "error", f"Excluded (infrastructure): {detail.get('reason') or 'see the sweep logs'}"
    stats = dict(detail.get("stats") or {})
    stats.setdefault("status", detail.get("turn_status") or "error")
    cell: dict[str, Any] = {
        "id": trial_cell_id(topology, scenario, model, effort, trial),
        "matrix_cell_id": matrix_id(topology, scenario, model, effort),
        "trial": trial, "topology": topology, "scenario": scenario, "model": model, "effort": effort,
        "status": status,
        "content": detail.get("diagnosis_text") or "",
        "tools": detail.get("tools") or [],
        "stats": stats,
        "evaluation": evaluation or {"status": "skipped", "reason": "Trial excluded before diagnosis."},
        "sweep": {
            "trial_id": detail.get("trial_id"), "attempt": detail.get("attempt"),
            "turn_status": detail.get("turn_status"), "rule_outcome": detail.get("outcome"),
            "rule_score": {k: (detail.get("score") or {}).get(k) for k in ("family_correct", "location_correct")},
            "network_restart_s": detail.get("network_restart_s"), "trial_seconds": detail.get("trial_seconds"),
            "detail_file": detail.get("detail_file"),
        },
    }
    if error:
        cell["error"] = error
    if cell["content"] or cell["tools"]:
        key = f"{d1_run_id(plan)}:{detail.get('trial_id')}"
        cell["conversation_id"] = uuid.uuid5(_NAMESPACE, key + ":conversation").hex
        cell["message_id"] = uuid.uuid5(_NAMESPACE, key + ":message").hex
    return cell


def chat_messages(plan: dict[str, Any], detail: dict[str, Any], cell: dict[str, Any]) -> tuple[str, dict, dict, list]:
    """Title, user message, assistant payload and provider history for the trial's chat."""
    from agent import topology_control

    labels = {t["id"]: t["label"] for t in topology_control.TOPOLOGIES}
    variant = next(v for v in variants(plan) if v["model"] == cell["model"] and v["effort"] == cell["effort"])
    user = {"role": "user", "content": detail.get("prompt") or plan["prompts"][cell["scenario"]]}
    assistant = {
        "id": cell["message_id"], "role": "assistant", "content": cell["content"], "tools": cell["tools"],
        "stats": cell["stats"], "evaluation": cell["evaluation"],
        "settings": {key: cell[key] for key in ("model", "effort", "topology", "scenario")},
        "benchmark": {"run_id": d1_run_id(plan), "cell_id": cell["id"],
                      "matrix_cell_id": cell["matrix_cell_id"], "trial": cell["trial"]},
        "sweep": cell["sweep"],
    }
    history = [user, {"role": "assistant", "content": cell["content"]}]
    title = (f"Sweep · {labels.get(cell['topology'], cell['topology'])} {cell['scenario']} · "
             f"{variant['label']} / {cell['effort']} · Round {cell['trial']} · {plan['run_id']}")
    return title, user, assistant, history


def ensure_run(plan: dict[str, Any], records: list[dict[str, Any]], status: str) -> None:
    """Create the run (with pending rows) once; later, update it and add rows for new rounds."""
    from agent import store

    run = run_payload(plan, records, status)
    cells = planned_cells(plan)
    existing = store.get_benchmark(run["id"], detail=False)
    if existing is None:
        store.create_benchmark(run, cells)
        return
    store.save_benchmark(run)
    have = {cell["id"] for cell in existing.get("cells", [])}
    missing = [cell for cell in cells if cell["id"] not in have]
    if missing:
        store.add_benchmark_cells(run["id"], missing)


def publish_trial(plan: dict[str, Any], record: dict[str, Any]) -> None:
    from agent import store

    detail = _detail(record)
    cell = trial_cell(plan, detail)
    if cell.get("conversation_id") and store.get(cell["conversation_id"]) is None:
        title, user, assistant, history = chat_messages(plan, detail, cell)
        store.save_benchmark_chat(d1_run_id(plan), cell, title, user, assistant, history)
    else:
        store.save_benchmark_cell(d1_run_id(plan), cell)


def session_status(plan: dict[str, Any], records: list[dict[str, Any]]) -> str:
    finals = sweep.final_records(records)
    done = sweep.completed_rounds(plan, finals)
    return "completed" if all(done[t] >= plan["target_rounds"] for t in plan["topologies"]) else "paused"


class Publisher:
    """Best-effort publishing during a sweep. A D1 failure never stops trials."""

    def __init__(self, run_dir: Path, plan: dict[str, Any]) -> None:
        self.run_dir, self.plan, self.failed = run_dir, plan, False

    def _attempt(self, action: str, function: Any, *args: Any) -> None:
        if self.failed:
            return
        try:
            function(*args)
        except Exception as exc:  # noqa: BLE001 — reported once, records stay local
            self.failed = True
            print(
                f"Warning: results page {action} failed ({type(exc).__name__}: {str(exc)[:200]}). "
                f"Local records are complete; later run: python3 -m experiments.sweep publish "
                f"--run-id {self.plan['run_id']}",
                flush=True,
            )

    def start(self) -> None:
        from agent import store

        self._attempt("setup", store.initialize)
        self._attempt("run update", ensure_run, self.plan, sweep.read_records(self.run_dir), "running")

    def trial(self, record: dict[str, Any]) -> None:
        self._attempt("trial upload", publish_trial, self.plan, record)
        from agent import store

        records = sweep.read_records(self.run_dir)
        self._attempt("run update", store.save_benchmark, run_payload(self.plan, records, "running"))

    def finish(self) -> None:
        from agent import store

        records = sweep.read_records(self.run_dir)
        status = session_status(self.plan, records)
        self._attempt("run update", store.save_benchmark, run_payload(self.plan, records, status))


def publish_all(run_dir: Path) -> tuple[int, list[str]]:
    """Upload every final trial again (idempotent). Returns (count, errors)."""
    from agent import store

    plan = sweep.load_plan(run_dir)
    records = sweep.read_records(run_dir)
    store.initialize()
    ensure_run(plan, records, session_status(plan, records))
    errors = []
    finals = sweep.final_records(records)
    for record in finals.values():
        try:
            publish_trial(plan, record)
        except Exception as exc:  # noqa: BLE001 — keep going, report each
            errors.append(f"{record.get('trial_id')}: {type(exc).__name__}: {str(exc)[:200]}")
    return len(finals) - len(errors), errors
