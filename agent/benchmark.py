"""Operator-only exploratory benchmark. Nothing runs until explicitly started."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import logging
import math
import os
import time
import uuid

from experiments.prompts import PROMPTS
from . import config, fault_control, judge, store, tools, topology_control
from .loop import run as diagnose

EFFORTS = ("low", "medium", "high", "xhigh")
SCENARIOS = tuple(f"F{i}" for i in range(1, 6))
TERMINAL = {"completed", "error", "cancelled", "skipped", "interrupted"}
DEFAULT_REPEATS = 3
MAX_REPEATS = 50


def aggregate_cells(trials):
    """Collapse trial rows into matrix cells; old rows are single-trial cells."""
    groups = {}
    for trial in trials:
        groups.setdefault(trial.get("matrix_cell_id", trial["id"]), []).append(trial)
    cells = []
    for cell_id, group in groups.items():
        group = sorted(group, key=lambda t: t.get("trial", 1))
        first = group[0]
        distribution = {"correct": 0, "partial": 0, "incorrect": 0}
        for trial in group:
            evaluation = trial.get("evaluation") or {}
            if trial.get("status") != "completed" or evaluation.get("status") != "completed":
                continue
            verdict = evaluation.get("verdict")
            if verdict in {"mostly_correct", "partially_correct"}:
                verdict = "partial"
            if verdict in distribution:
                distribution[verdict] += 1
        graded = sum(distribution.values())
        finished = sum(t.get("status") in TERMINAL for t in group)
        if graded == len(group):
            status = "completed"
        elif all(t.get("status") == "pending" for t in group):
            status = "pending"
        elif finished < len(group):
            status = "running"
        else:
            status = "incomplete"
        highest = max(distribution.values())
        leaders = [outcome for outcome, count in distribution.items() if count == highest and count > 0]
        verdict = leaders[0] if len(leaders) == 1 else None
        labels = {"correct": "Correct", "partial": "Mostly / partially correct", "incorrect": "Incorrect"}
        label = f"{graded}/{len(group)} trials graded"
        if status == "completed":
            label = labels[verdict] if verdict else "Inconclusive (tied outcomes)"
        cells.append({"id": cell_id, **{key: first.get(key) for key in ("topology", "scenario", "model", "effort")},
                      "status": status, "verdict": verdict if status == "completed" else None,
                      "label": label,
                      "distribution": distribution, "graded": graded, "finished": finished,
                      "total": len(group), "cost": cost_summary(group),
                      "trials": [public_cell(t) for t in group]})
    return cells


def variants():
    return [{"model": model["id"], "label": model["label"], "effort": effort,
             "deprecated": model.get("deprecated", False)}
            for model in config.MODELS
            for effort in (EFFORTS if model.get("reasoning", True) else ("none",))
            if effort in model["efforts"]]


def public_cell(cell, detail=False):
    result = {k: v for k, v in cell.items()
              if k not in {"evaluation", "content", "tools", "stats"}}
    evaluation = judge.public(cell.get("evaluation"))
    if evaluation and not detail:
        evaluation = {k: v for k, v in evaluation.items() if k in {"status", "verdict", "label", "error"}}
    if evaluation:
        result["evaluation"] = evaluation
    if detail:
        result.update(content=cell.get("content", ""), tools=cell.get("tools", []),
                      stats=cell.get("stats", {}))
    return result


def public_run(item):
    result = {k: v for k, v in item.items() if k not in {"cells", "system_prompt"}}
    result.setdefault("repeats", 1)
    if "cells" in item:
        result.update(run_costs(item["cells"]))
        result["cells"] = aggregate_cells(item["cells"])
        result["cell_count"] = len(result["cells"])
        result["graded"] = sum(c["graded"] for c in result["cells"])
        result["finished"] = sum(c["finished"] for c in result["cells"])
        result["errors"] = sum(c.get("status") in {"error", "interrupted"} for c in item["cells"])
    return result


def cost_summary(cells):
    """Sum costs calculated from reported usage; missing usage is not a billing zero."""
    totals = {"diagnosis_usd": 0.0, "judge_usd": 0.0, "explanation_usd": 0.0,
              "total_usd": 0.0, "incomplete": False}
    for cell in cells:
        stats = cell.get("stats") or {}
        evaluation = cell.get("evaluation") or {}
        explanation = evaluation.get("explanation") or {}
        attempted = bool(stats.get("model_calls") or cell.get("content") or
                         cell.get("status") in {"running", "grading", "completed", "cancelled", "interrupted"})
        parts = [("diagnosis_usd", stats.get("cost_usd"), attempted),
                 ("judge_usd", evaluation.get("cost_usd"), evaluation.get("status") in {"pending", "completed", "error"}),
                 ("explanation_usd", explanation.get("cost_usd"), explanation.get("status") in {"pending", "completed", "error"})]
        for key, value, requested in parts:
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
                totals[key] += value
            elif requested:
                totals["incomplete"] = True
        if (stats.get("usage_complete") is not None and not stats["usage_complete"]) or cell.get("status") in {"running", "grading"}:
            totals["incomplete"] = True
    totals["total_usd"] = totals["diagnosis_usd"] + totals["judge_usd"] + totals["explanation_usd"]
    return totals


def run_costs(cells):
    return {"cost": cost_summary(cells),
            "costs_by_model": {model: cost_summary([c for c in cells if c.get("model") == model])
                               for model in {c.get("model") for c in cells if c.get("model")}}}


async def finish_thread(function, *args, propagate_cancel=True):
    """Cancellation must not release a testbed or storage operation mid-thread."""
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            break
    if cancelled and propagate_cancel:
        if not task.cancelled():
            task.exception()
        raise asyncio.CancelledError
    return task.result()


class Benchmark:
    def __init__(self, client):
        self.client = client
        self.active = None
        self.task = None
        self.stop_requested = False
        self.pause_requested = False
        self.workers = []
        self.probe_lock = asyncio.Lock()
        self.explanations = {}
        self.explanation_lock = asyncio.Lock()
        self.persistence_lock = asyncio.Lock()

    async def start(self, selected, concurrency, repeats=DEFAULT_REPEATS):
        if self.active:
            raise RuntimeError("A benchmark is already running.")
        available = {(v["model"], v["effort"]): v for v in variants()}
        keys = [(v["model"], v["effort"]) for v in selected]
        if not keys or len(set(keys)) != len(keys) or any(key not in available for key in keys):
            raise ValueError("Select unique supported model/thinking combinations.")
        if concurrency not in range(1, 5):
            raise ValueError("Concurrency must be between 1 and 4.")
        if isinstance(repeats, bool) or not isinstance(repeats, int) or not 1 <= repeats <= MAX_REPEATS:
            raise ValueError(f"Runs per cell must be an integer between 1 and {MAX_REPEATS}.")
        if not self.client:
            raise RuntimeError("Configure the AI Gateway and restart the server.")
        prompt = (config.ROOT / "prompt.md").read_text()
        item = {"id": uuid.uuid4().hex, "status": "starting",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "variants": [deepcopy(available[key]) for key in keys],
                "topologies": list(topology_control.TOPOLOGIES), "scenarios": list(SCENARIOS),
                "prompts": dict(PROMPTS), "concurrency": concurrency, "repeats": repeats,
                "limits": {**config.runtime_limits(), "max_turn_tokens": int(os.getenv("MAX_TURN_TOKENS", "0"))}, "system_prompt": prompt,
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                "cell_count": 15 * len(keys), "total": 15 * len(keys) * repeats, "finished": 0,
                "mode": "exploratory", "prices": deepcopy(config.PRICES)}
        cells = [{"id": f"{topology['id']}:{fault}:{v['model']}:{v['effort']}:trial:{trial}",
                  "matrix_cell_id": f"{topology['id']}:{fault}:{v['model']}:{v['effort']}", "trial": trial,
                  "topology": topology["id"], "scenario": fault,
                  "model": v["model"], "effort": v["effort"], "status": "pending"}
                 for topology in item["topologies"] for fault in SCENARIOS
                 for trial in range(1, repeats + 1) for v in item["variants"]]
        # Reserve before the first await: two Play clicks cannot overlap setup.
        self.active = item
        self.stop_requested = False
        self.pause_requested = False
        try:
            await finish_thread(store.create_benchmark, deepcopy(item), cells)
        except BaseException:
            item.update(status="error", error="Benchmark creation interrupted or could not be saved. No scenarios were run.")
            try:
                await finish_thread(store.save_benchmark, deepcopy(item))
            except BaseException:
                logging.getLogger(__name__).warning("Benchmark creation persistence failed")
            self.active = None
            raise
        self.task = asyncio.create_task(self.execute(item, cells))
        return public_run(item)

    def stop(self, *, paused=False):
        if self.active:
            self.stop_requested = True
            self.pause_requested = self.pause_requested or paused
            self.active["status"] = "pausing" if self.pause_requested else "stopping"
            for task in self.workers:
                task.cancel()

    async def save_run(self, item):
        async with self.persistence_lock:
            await finish_thread(store.save_benchmark, deepcopy(item))

    async def save_cell(self, item, cell):
        async with self.persistence_lock:
            await finish_thread(store.save_benchmark_cell, item["id"], deepcopy(cell))

    async def probe(self, name, arguments):
        started = time.perf_counter()
        async with self.probe_lock:
            waited = time.perf_counter() - started
            result = await tools.execute_tool(name, arguments)
            result["queue_wait_seconds"] = waited
            return result

    async def trial(self, item, cell, slots, template):
        async with slots:
            if self.stop_requested:
                return
            cell["status"] = "running"
            state = {"content": "", "tools": [], "stats": {}}
            question = item["prompts"][cell["scenario"]]
            evaluation = deepcopy(template)
            user = {"role": "user", "content": question}
            history = [user]
            chat_saved = diagnosis_completed = False
            async def save_chat():
                nonlocal chat_saved
                cell.setdefault("conversation_id", uuid.uuid4().hex)
                cell.setdefault("message_id", uuid.uuid4().hex)
                cell["evaluation"] = evaluation
                settings = {key: cell[key] for key in ("model", "effort", "topology", "scenario")}
                assistant = {"id": cell["message_id"], "role": "assistant", **state,
                             "settings": settings, "evaluation": evaluation,
                             "benchmark": {"run_id": item["id"], "cell_id": cell["id"],
                                           "matrix_cell_id": cell["matrix_cell_id"], "trial": cell["trial"]}}
                if not diagnosis_completed:
                    assistant = {**assistant, "content": state["content"] + "\n\n" + cell.get("error", "Diagnosis did not complete.")}
                provider_history = history if diagnosis_completed else [user, {"role": "assistant", "content": assistant["content"]}]
                label = next(t["label"] for t in item["topologies"] if t["id"] == cell["topology"])
                model_label = next(v["label"] for v in item["variants"] if v["model"] == cell["model"])
                title = f"Benchmark · {label} {cell['scenario']} · {model_label} / {cell['effort']} · Trial {cell['trial']}/{item['repeats']} · {item['id'][:6]}"
                async with self.persistence_lock:
                    await finish_thread(store.save_benchmark_chat, item["id"], deepcopy(cell), title,
                                        user, deepcopy(assistant), deepcopy(provider_history), propagate_cancel=False)
                chat_saved = True
            async def persist(value):
                cell["evaluation"] = value
                async with self.persistence_lock:
                    await finish_thread(store.update_evaluation, cell["conversation_id"], cell["message_id"], deepcopy(value))
            async def record_usage():
                cell.update(state)
                await self.save_cell(item, cell)
            try:
                await self.save_cell(item, cell)
                # This local history contains only the symptom and this run's outputs.
                async for _ in diagnose(self.client, history, cell["model"], cell["effort"], state,
                                        tool_executor=self.probe, prompt=item["system_prompt"],
                                        limits=item["limits"], on_usage=record_usage):
                    pass
                diagnosis_completed = True
                cell.update(state)
                cell["stats"]["status"] = "completed"
                cell["stats"]["tool_queue_wait_seconds"] = sum(
                    t.get("queue_wait_seconds", 0) for t in state["tools"])
                cell["status"] = "grading"
                evaluation["answer"] = state["content"]
                await save_chat()
                if evaluation["status"] == "pending":
                    key = (cell["conversation_id"], cell["message_id"], "judge")
                    judge.launch(key[0], key[1], "judge", judge.evaluate(self.client, key[0], key[1], evaluation, persist=persist))
                    await judge.JOBS[key]
                if self.stop_requested:
                    cell["status"] = "cancelled"
                elif evaluation["status"] == "completed":
                    cell["status"] = "completed"
                else:
                    cell.update(status="error", error=evaluation.get("error", "Evaluation failed."))
            except asyncio.CancelledError:
                cell.update(state)
                cell.update(status="cancelled", error="Run stopped before this cell finished.")
                cell["stats"].update(status="cancelled", usage_complete=False)
            except Exception as exc:
                cell.update(state)
                cell.update(status="error", error=judge.safe_error(exc, "Benchmark diagnosis"))
                cell["stats"].update(status="error", usage_complete=False)
            finally:
                cell["stats"]["tool_queue_wait_seconds"] = sum(
                    t.get("queue_wait_seconds", 0) for t in cell.get("tools", []))
                if not chat_saved:
                    if not diagnosis_completed:
                        evaluation = {"status": "skipped", "reason": "Diagnosis did not complete."}
                    await save_chat()
                item["finished"] += 1
                await self.save_cell(item, cell)
                await self.save_run(item)

    async def execute(self, item, cells):
        network_used = False
        try:
            item["status"] = "running"
            await self.save_run(item)
            for topology in item["topologies"]:
                for fault in SCENARIOS:
                    for trial in range(1, item["repeats"] + 1):
                        if self.stop_requested:
                            break
                        item["current"] = {"topology": topology["id"], "scenario": fault, "trial": trial}
                        await self.save_run(item)
                        network_used = True
                        # Reapply the scenario for each repeat, before any variants run.
                        result = await finish_thread(fault_control.load_scenario, fault, topology["id"])
                        tools.refresh_tools()
                        if not result.get("ok") or result.get("scenario_id") != fault or result.get("topology") != topology["id"]:
                            raise RuntimeError(result.get("error") or "Scenario setup did not match the requested network.")
                        if self.stop_requested:
                            break
                        batch = [c for c in cells if c["topology"] == topology["id"] and c["scenario"] == fault and c["trial"] == trial]
                        template = judge.prepare({"topology": topology["id"], "scenario": fault},
                                                 item["prompts"][fault], [])
                        if template["status"] != "pending":
                            raise RuntimeError(template.get("error") or "Scenario rubric unavailable.")
                        slots = asyncio.Semaphore(item["concurrency"])
                        self.workers = [asyncio.create_task(self.trial(item, cell, slots, template)) for cell in batch]
                        outcomes = await asyncio.gather(*self.workers, return_exceptions=True)
                        self.workers = []
                        failure = next((outcome for outcome in outcomes if isinstance(outcome, Exception)), None)
                        if failure:
                            raise failure
                    if self.stop_requested:
                        break
                if self.stop_requested:
                    break
            item["status"] = ("paused" if self.pause_requested else "cancelled") if self.stop_requested else "completed"
        except asyncio.CancelledError:
            self.stop()
            await asyncio.gather(*self.workers, return_exceptions=True)
            item["status"] = "paused" if self.pause_requested else "cancelled"
        except Exception as exc:
            self.stop()
            await asyncio.gather(*self.workers, return_exceptions=True)
            item.update(status="error", error=judge.safe_error(exc, "Benchmark"))
        finally:
            # Keep the reservation until ALL probes and fault cleanup finish.
            if item["status"] != "error":
                item["status"] = ("pausing" if self.pause_requested else "stopping") if self.stop_requested else "running"
            item["phase"] = "cleanup"
            try:
                if network_used:
                    result = await finish_thread(fault_control.reset_scenario, propagate_cancel=False)
                    tools.refresh_tools()
                    if not result.get("ok"):
                        raise RuntimeError(result.get("error") or "Fault cleanup failed.")
            except Exception as exc:
                topology_control.error = judge.safe_error(exc, "Benchmark cleanup")
                item.update(status="error", error=topology_control.error)
            try:
                skipped = []
                for cell in cells:
                    if cell["status"] not in TERMINAL:
                        cell.update(status="skipped", error="Benchmark ended before this cell ran.")
                        skipped.append(cell)
                if skipped:
                    async with self.persistence_lock:
                        await finish_thread(store.save_benchmark_cells, item["id"], deepcopy(skipped), propagate_cancel=False)
                if item["status"] != "error":
                    item["status"] = ("paused" if self.pause_requested else "cancelled") if self.stop_requested else "completed"
                item.update(run_costs(cells))
                item["finished"] = sum(c["status"] in TERMINAL for c in cells)
                item["finished_at"] = datetime.now(timezone.utc).isoformat()
                item.pop("current", None)
                item.pop("phase", None)
                await self.save_run(item)
            except Exception:
                logging.getLogger(__name__).exception("Benchmark result persistence failed")
            finally:
                self.workers = []
                self.active = None

    async def explain(self, run_id, cell_id):
        key = (run_id, cell_id)
        async with self.explanation_lock:
            cell = await asyncio.to_thread(store.get_benchmark_cell, run_id, cell_id)
            if not cell:
                raise LookupError("Benchmark cell not found.")
            evaluation = cell.get("evaluation") or {}
            if cell.get("status") != "completed" or evaluation.get("status") != "completed":
                raise RuntimeError("Wait for a completed assessment before explaining it.")
            if key in self.explanations or (evaluation.get("explanation") or {}).get("status") == "completed":
                return public_cell(cell, detail=True)
            if not self.client:
                raise RuntimeError("Configure the AI Gateway and restart the server.")
            evaluation["explanation"] = {"status": "pending", "model": judge.EXPLAIN_MODEL, "effort": "high"}
            async def persist(value):
                # Updating only evaluation avoids overwriting a final cell status.
                async with self.persistence_lock:
                    await finish_thread(store.save_benchmark_evaluation, run_id, cell_id, deepcopy(value))
            await persist(evaluation)
            task = asyncio.create_task(judge.explain(self.client, None, None, evaluation, persist=persist))
            self.explanations[key] = task
            def done(task):
                self.explanations.pop(key, None)
                if not task.cancelled() and task.exception():
                    logging.getLogger(__name__).warning("Benchmark explanation persistence failed")
            task.add_done_callback(done)
            return public_cell(cell, detail=True)

    async def shutdown(self):
        self.stop()
        if self.task and not self.task.done():
            # Setup threads finish first; execute's finally performs the reset.
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        tasks = list(self.explanations.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
