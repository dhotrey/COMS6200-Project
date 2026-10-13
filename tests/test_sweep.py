"""Static checks for the exploratory sweep, its scoring and the model lister.

Does not contact ONOS, Mininet or any model provider. The trial flow and the
orchestrator run against fakes.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
from collections import Counter
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
os.environ["COMS6200_TOPOLOGY"] = "main6s8h"

import list_models  # noqa: E402
from experiments import evaluator, sweep, sweep_scoring  # noqa: E402
from experiments.prompts import PROMPTS, SCENARIOS  # noqa: E402
from faults.expectations import EXPECTATIONS  # noqa: E402
from faults.registry import CATALOGUES  # noqa: E402
from topologies.active import SPECS  # noqa: E402

# Answers in the style of the WSL2 pilots (docs/results/llm-diagnosis.md) plus
# hedged, ranked and wrong variants. Scored against every main6s8h scenario.
MAIN_ANSWERS = (
    "s3-eth1 (port 1) <-> s1-eth2 (port 2) is down at both ends; the link is down.",
    "Link failure on s3:1 to s1:2.",
    "Severe congestion on the s1-s5 segment; traffic shaping limits h1 to h5 transfers.",
    "Most likely congestion on s1 port 4 toward s5.",
    "A drop rule on s3 (priority 50000, NOACTION) blocks h1 to h5.",
    "A forwarding loop: h1 to h5 traffic cycles s3 -> s4 -> s1 -> s3.",
    "The forwarding rule for h5 is missing on s3, so h1 and h2 cannot reach h5.",
    "The link is down or a drop rule on s3 blocks h1 to h5.",
    "Congestion on the s3-s1 link.",
    "Missing flow for h5 on s1.",
    "I could not determine the cause.",
)


def _correct_text(scenario) -> str:
    """A right answer built from where the fault is placed."""
    family = scenario.fault_family
    if family in ("link_failure", "congestion"):
        link = scenario.link
        word = "is down" if family == "link_failure" else "is congested by traffic shaping"
        return f"The {link.a}-{link.b} link {word}."
    if family == "acl_policy_error":
        return f"A drop rule on {scenario.switch} blocks {scenario.src_host} to {scenario.dst_host}."
    if family == "forwarding_loop":
        cycle = [hop.switch for hop in scenario.hops] + [scenario.hops[0].switch]
        return f"Forwarding loop: {scenario.src_host} to {scenario.dst_host} cycles {' -> '.join(cycle)}."
    return f"There is a missing forwarding rule for {scenario.dst_host} on {scenario.switch}."


def test_topologies_match_specs_and_catalogues() -> None:
    assert sweep.TOPOLOGIES == tuple(SPECS), (sweep.TOPOLOGIES, tuple(SPECS))
    assert set(sweep.TOPOLOGIES) == set(CATALOGUES)
    for topology, catalogue in CATALOGUES.items():
        assert set(catalogue.scenarios) == set(SCENARIOS), topology
        for sid, scenario in catalogue.scenarios.items():
            scored_family = sweep_scoring.SCORING_FAMILY[scenario.fault_family]
            assert scored_family == evaluator.FAMILIES[sid], (topology, sid)


def test_prompts_are_true_on_every_topology() -> None:
    claims = {
        "F1": ("unreachable", (("h1", "h5"),)),
        "F2": ("slow", ("h1", "h5")),
        "F3": ("unreachable", (("h1", "h5"),)),
        "F4": ("unreachable", (("h1", "h5"),)),
        "F5": ("unreachable", (("h1", "h5"), ("h2", "h5"))),
    }
    for topology, expectations in EXPECTATIONS.items():
        for sid, (kind, pairs) in claims.items():
            expected = getattr(expectations[sid], kind)
            if kind == "slow":
                assert expected == pairs, (topology, sid, PROMPTS[sid])
            else:
                assert set(pairs) <= set(expected), (topology, sid, PROMPTS[sid])


def test_rounds_are_complete_seeded_and_distinct() -> None:
    plan = sweep.build_config(run_id="t", models=["m-a", "m-b"], efforts={"m-b": "none"}, seed=7)
    assert plan["efforts"] == {"m-a": "medium", "m-b": "none"} and plan["rounds"] == []
    first = sweep.round_trials(plan, "ring5s5h", 1)
    cells = Counter((t["model"] or "baseline", t["scenario"]) for t in first)
    assert len(first) == 3 * 5 and set(cells.values()) == {1}, cells
    assert all(t["topology"] == "ring5s5h" and t["round"] == 1 for t in first)
    assert [t["index"] for t in first] == list(range(1, 16))
    order = lambda trials: [(t["model"], t["scenario"]) for t in trials]  # noqa: E731
    assert order(sweep.round_trials(plan, "ring5s5h", 1)) == order(first), "same seed, same order"
    assert order(sweep.round_trials(plan, "ring5s5h", 2)) != order(first), "each round reshuffled"
    assert order(sweep.round_trials(plan, "tree5s8h", 1)) != order(first), "each topology reshuffled"
    ids = {t["trial_id"] for r in (1, 2) for t in sweep.round_trials(plan, "ring5s5h", r)}
    assert len(ids) == 30, "trial ids are unique across rounds"
    assert {t["effort"] for t in first if t["model"] == "m-b"} == {"none"}
    assert all(t["model"] is None and t["effort"] is None for t in first if t["method"] == "baseline")
    assert plan["prompts"] == {s: PROMPTS[s] for s in SCENARIOS}
    assert "store=false" in plan["caching"]["provider_storage"]


def test_round_progress_and_next_topology() -> None:
    plan = sweep.build_config(run_id="t", models=["m"], scenarios=("F1",))
    for topology, number in (("ring5s5h", 1), ("ring5s5h", 2), ("tree5s8h", 1)):
        plan["rounds"].append(
            {"topology": topology, "round": number, "trials": sweep.round_trials(plan, topology, number)}
        )
    finals = {t["trial_id"]: {"status": "completed"} for t in sweep.all_trials(plan)}
    tree_trial = sweep.topology_rounds(plan, "tree5s8h")[0]["trials"][0]["trial_id"]
    del finals[tree_trial]
    assert sweep.completed_rounds(plan, finals) == {"main6s8h": 0, "ring5s5h": 2, "tree5s8h": 0}
    assert sweep.suggest_next(plan, finals, "tree5s8h") == "main6s8h"
    finals[tree_trial] = {"status": "completed"}
    plan["rounds"].append({"topology": "main6s8h", "round": 1, "trials": sweep.round_trials(plan, "main6s8h", 1)})
    finals.update(
        {t["trial_id"]: {"status": "completed"} for t in sweep.topology_rounds(plan, "main6s8h")[0]["trials"]}
    )
    # main 1, ring 2, tree 1: after main, the tie goes to the next topology in order.
    assert sweep.suggest_next(plan, finals, "main6s8h") == "tree5s8h"


def test_scoring_matches_frozen_evaluator_on_main6s8h() -> None:
    for sid in SCENARIOS:
        for text in MAIN_ANSWERS:
            frozen = evaluator.evaluate({"diagnosis_text": text}, sid, method="llm")
            ours = sweep_scoring.score("main6s8h", sid, {"diagnosis_text": text}, method="llm")
            assert ours == frozen, (sid, text, ours, frozen)
        for family in (None, *evaluator.FAMILIES.values()):
            for location in ("s3 port 1 to s1 port 2", "s1 port 4", "drop rule on s3 for h1 toward h5",
                             "s3 -> s4 -> s1 for h1 to h5", "missing forwarding rule for h5 on s3", None):
                result = {"diagnosis_family": family, "diagnosis_location": location, "diagnosis_text": "x"}
                frozen = evaluator.evaluate(result, sid, method="baseline")
                ours = sweep_scoring.score("main6s8h", sid, result, method="baseline")
                assert ours == frozen, (sid, family, location)


def test_scoring_uses_each_topologies_fault_locations() -> None:
    for topology, catalogue in CATALOGUES.items():
        for sid, scenario in catalogue.scenarios.items():
            scored = sweep_scoring.score(topology, sid, {"diagnosis_text": _correct_text(scenario)}, method="llm")
            assert sweep_scoring.outcome(scored) == "success", (topology, sid, scored)
    # main6s8h's locations are wrong on the ring for every scenario.
    for sid, scenario in CATALOGUES["main6s8h"].scenarios.items():
        scored = sweep_scoring.score("ring5s5h", sid, {"diagnosis_text": _correct_text(scenario)}, method="llm")
        assert sweep_scoring.outcome(scored) == "partial", (sid, scored)
    # Every location clause must be right, and on the tree s7 counts as a location
    # (main6s8h has no s7, so the frozen detector would ignore that clause).
    text = {"diagnosis_text": "The s1-s2 link is down or the s7 link is down."}
    scored = sweep_scoring.score("tree5s8h", "F1", text, method="llm")
    assert (scored["family_correct"], scored["location_correct"]) == (1, 0), scored
    scored = sweep_scoring.score("tree5s8h", "F1", {"diagnosis_text": "The s1-s2 link is down."}, method="llm")
    assert (scored["family_correct"], scored["location_correct"]) == (1, 1), scored


def test_baseline_location_strings_on_the_ring() -> None:
    cases = {
        "F1": ("link_failure", "s3 port 1 to s4 port 2"),
        "F2": ("congestion", "s2 port 1"),
        "F3": ("policy_drop", "drop rule on s4 for h1 toward h5"),
        "F4": ("forwarding_loop", "s1 -> s2 -> s3 -> s4 -> s5 -> s1 for h1 to h5"),
        "F5": ("missing_flow", "missing forwarding rule for h5 on s2"),
    }
    for sid, (family, location) in cases.items():
        result = {"diagnosis_family": family, "diagnosis_location": location, "diagnosis_text": location}
        scored = sweep_scoring.score("ring5s5h", sid, result, method="baseline")
        assert sweep_scoring.outcome(scored) == "success", (sid, scored)


class FakeHooks:
    def __init__(self, *, topology="ring5s5h", gate=True, inject=True, result=None, raises=False):
        self.calls: list[str] = []
        self._topology, self._gate, self._inject = topology, gate, inject
        self._result, self._raises = result, raises

    def topology(self):
        return self._topology

    def catalogue_version(self):
        return "ring5s5h-v1"

    def gate(self):
        self.calls.append("gate")
        return {"ok": self._gate}

    def inject(self, scenario):
        self.calls.append(f"inject {scenario}")
        return {"ok": self._inject, "data": {"status": "ACTIVE"}, "error": None if self._inject else {"code": "X"}}

    def reset(self):
        self.calls.append("reset")
        return {"ok": True, "data": {"status": "IDLE"}}

    def diagnose(self, trial, prompt):
        self.calls.append("diagnose")
        if self._raises:
            raise RuntimeError("boom")
        return self._result

    def judge(self, trial, prompt, answer):
        self.calls.append("judge")
        return {"status": "completed", "verdict": "correct", "answer": answer}


def _trial(method="llm"):
    return {"trial_id": "r01-ring5s5h-m-F3", "round": 1, "index": 1, "topology": "ring5s5h",
            "scenario": "F3", "method": method, "model": "m" if method == "llm" else None,
            "effort": "medium" if method == "llm" else None}


def test_run_trial_flow_and_isolation() -> None:
    answer = {"status": "completed", "diagnosis_text": "A drop rule on s4 blocks h1 to h5.",
              "stats": {"tool_calls": 3, "cost_usd": 0.01}, "tool_trace": []}
    hooks = FakeHooks(result=answer)
    record = sweep.run_trial(_trial(), PROMPTS["F3"], hooks)
    assert hooks.calls == ["gate", "inject F3", "diagnose", "reset", "judge"], hooks.calls
    assert (record["status"], record["turn_status"], record["outcome"]) == ("completed", "completed", "success")
    assert record["evaluation"]["verdict"] == "correct", "the judge grades the answer after the reset"
    assert record["evaluation"]["answer"] == answer["diagnosis_text"]
    summary = sweep.summary_record(record)
    assert (summary["judge_status"], summary["judge_verdict"]) == ("completed", "correct")
    assert summary["asks_user"] is False
    asking = {**answer, "diagnosis_text": "h1 cannot reach h5. Would you like me to check the flow tables?"}
    assert sweep.summary_record(sweep.run_trial(_trial(), PROMPTS["F3"], FakeHooks(result=asking)))["asks_user"] is True
    baseline = sweep.run_trial(_trial("baseline"), PROMPTS["F3"], FakeHooks(result=answer))
    assert baseline["asks_user"] is None, "the scripted baseline never asks"
    assert record["catalogue_version"] == "ring5s5h-v1" and record["prompt"] == PROMPTS["F3"]
    assert "F3" not in record["prompt"] and "drop" not in record["prompt"]

    hooks = FakeHooks(gate=False)
    assert sweep.run_trial(_trial(), PROMPTS["F3"], hooks)["status"] == "infrastructure"
    assert hooks.calls == ["gate"]
    hooks = FakeHooks(inject=False)
    record = sweep.run_trial(_trial(), PROMPTS["F3"], hooks)
    assert record["status"] == "infrastructure" and hooks.calls == ["gate", "inject F3", "reset"]
    hooks = FakeHooks(topology="main6s8h")
    assert sweep.run_trial(_trial(), PROMPTS["F3"], hooks)["status"] == "infrastructure"
    assert hooks.calls == []
    hooks = FakeHooks(raises=True)
    try:
        sweep.run_trial(_trial(), PROMPTS["F3"], hooks)
    except RuntimeError:
        pass
    assert hooks.calls[-1] == "reset", "reset must run even if the diagnosis crashes"
    hooks = FakeHooks(result={"status": "infrastructure", "error": "Gateway request failed"})
    assert sweep.run_trial(_trial(), PROMPTS["F3"], hooks)["status"] == "infrastructure"


def _new_sweep(run_dir: pathlib.Path, **kwargs) -> dict:
    plan = sweep.build_config(run_id=run_dir.name, **kwargs)
    run_dir.mkdir(parents=True, exist_ok=True)
    sweep.save_plan(run_dir, plan)
    return plan


def _worker_record(trial, attempt, **fields):
    return {**trial, "attempt": attempt, "status": "completed", "outcome": "success", "cost_usd": 0.45,
            "judge_status": "completed", "judge_verdict": "mostly_correct", "judge_cost_usd": 0.05,
            "reset_ok": True, "tool_calls": 4, "input_tokens": 1000, "cached_tokens": 800, **fields}


def _quiet(*patches):
    stack = contextlib.ExitStack()
    for patch in patches:
        stack.enter_context(patch)
    stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
    return stack


def test_repeating_a_topology_adds_rounds_and_resumes() -> None:
    with tempfile.TemporaryDirectory() as raw:
        run_dir = pathlib.Path(raw) / "sweep-test"
        plan = _new_sweep(run_dir, models=["m"], scenarios=("F1", "F2"))
        attempts: Counter = Counter()
        failing: set[str] = set()

        def worker(_python, _run_dir, trial, attempt):
            attempts[trial["trial_id"]] += 1
            if trial["trial_id"] in failing:
                return sweep.infrastructure_record(trial, attempt, "gate failed")
            return _worker_record(trial, attempt)

        restart = mock.Mock(return_value={"ok": True, "seconds": 1.0})

        def patches():
            return (mock.patch.object(sweep, "restart_network", restart),
                    mock.patch.object(sweep, "run_worker", worker),
                    mock.patch.object(sweep, "testbed", return_value=0))

        failing.add("ring5s5h-r01-m-F1")
        with _quiet(*patches()):
            assert sweep.run_topology(run_dir, plan, "ring5s5h", python="py", max_cost_usd=None) == 0
        records = sweep.read_records(run_dir)
        finals = sweep.final_records(records)
        assert attempts["ring5s5h-r01-m-F1"] == 2 and finals["ring5s5h-r01-m-F1"]["status"] == "excluded"
        assert [r["status"] for r in records if r["trial_id"] == "ring5s5h-r01-m-F1"] == ["infrastructure", "excluded"]
        assert len(finals) == 4 and restart.call_count == 5
        assert [(r["topology"], r["round"]) for r in sweep.load_plan(run_dir)["rounds"]] == [("ring5s5h", 1)]

        # Running the same topology again adds round 2 (new trials, new order) instead of skipping.
        with _quiet(*patches()):
            sweep.run_topology(run_dir, plan, "ring5s5h", python="py", max_cost_usd=None)
        saved = sweep.load_plan(run_dir)
        assert [(r["topology"], r["round"]) for r in saved["rounds"]] == [("ring5s5h", 1), ("ring5s5h", 2)]
        assert sum(count for trial, count in attempts.items() if "-r02-" in trial) == 4

        # --retry-excluded reruns only the excluded trial before any new round; --rounds 2 runs two rounds.
        failing.clear()
        with _quiet(*patches()):
            sweep.run_topology(run_dir, plan, "ring5s5h", python="py", max_cost_usd=None, retry_excluded=True)
        assert attempts["ring5s5h-r01-m-F1"] == 3 and len(sweep.load_plan(run_dir)["rounds"]) == 2
        with _quiet(*patches()):
            sweep.run_topology(run_dir, plan, "tree5s8h", rounds=2, python="py", max_cost_usd=None)
        assert [r["round"] for r in sweep.topology_rounds(sweep.load_plan(run_dir), "tree5s8h")] == [1, 2]

        # An interrupted round is resumed, not restarted.
        unfinished = sweep.round_trials(plan, "main6s8h", 1)
        plan["rounds"].append({"topology": "main6s8h", "round": 1, "trials": unfinished})
        sweep.save_plan(run_dir, plan)
        sweep.append_record(run_dir, _worker_record(unfinished[0], 1))
        before = sum(attempts.values())
        with _quiet(*patches()):
            sweep.run_topology(run_dir, plan, "main6s8h", python="py", max_cost_usd=None)
        assert sum(attempts.values()) - before == len(unfinished) - 1
        assert len(sweep.topology_rounds(plan, "main6s8h")) == 1

        sweep.write_summary(run_dir)
        summary = (run_dir / "summary.md").read_text(encoding="utf-8")
        assert "EXPLORATORY SWEEP / NOT PROTOCOL V1" in summary and "| m |" in summary
        assert "| ring5s5h | 2 / 5 | 2 |" in summary and "| tree5s8h | 2 / 5 | 2 |" in summary, summary
        assert "## Judge: success by method and topology" in summary
        assert "## Rule-based cross-check by method and topology" in summary
        assert "## Judge vs rule-based agreement (binary success)" in summary
        # Every worker record is judge "mostly_correct" (binary success) and rule "success": all agree.
        assert "(100%)" in summary.split("## Judge vs rule-based agreement")[1], summary
        assert "judge $" in summary


def test_run_stops_on_reset_failure_spend_cap_and_repeated_exclusions() -> None:
    with tempfile.TemporaryDirectory() as raw:
        run_dir = pathlib.Path(raw) / "sweep-stop"
        plan = _new_sweep(run_dir, models=["m"], scenarios=("F1", "F2"))
        trials = sweep.round_trials(plan, "ring5s5h", 1)
        cases = (
            (lambda _p, _d, t, a: _worker_record(t, a, reset_ok=False), None, 3, 1),
            (lambda _p, _d, t, a: _worker_record(t, a), 0.4, 2, 1),
            (lambda _p, _d, t, a: sweep.infrastructure_record(t, a, "x"), None, 4, 3),
        )
        for worker, cap, code, final_count in cases:
            for path in run_dir.glob("trials.jsonl"):
                path.unlink()
            with _quiet(mock.patch.object(sweep, "restart_network", return_value={"ok": True, "seconds": 1.0}),
                        mock.patch.object(sweep, "run_worker", worker),
                        mock.patch.object(sweep, "testbed", return_value=0)):
                assert sweep.run_trials(run_dir, trials, python="py", max_cost_usd=cap) == code
            assert len(sweep.final_records(sweep.read_records(run_dir))) == final_count, code


def test_asks_user_reads_only_the_final_paragraph() -> None:
    # Endings seen from gpt-4.1-mini/nano in the first live round.
    assert sweep_scoring.asks_user("Ping fails with 100% loss. Should I start by testing h1 to h2?")
    assert sweep_scoring.asks_user(
        "Throughput is low.\n\nWould you like me to run this test? If yes, please specify the duration."
    )
    assert sweep_scoring.asks_user("I will check the topology next. Would you like me to proceed with that?")
    # A conclusion, a stated plan, or a question settled earlier is not handing the turn back.
    assert not sweep_scoring.asks_user("**Diagnosis:** the s3-s4 link is down.\n\n**Next step:** restore it.")
    assert not sweep_scoring.asks_user("Next, I will verify s4 port 1 to confirm its status.")
    assert not sweep_scoring.asks_user(
        "Should I suspect h5? No: h4 to h5 works.\n\nThe fault is a drop rule on s4 for h1 to h5."
    )
    assert not sweep_scoring.asks_user("Why is s1-s5 unused? The baseline reserves it.")
    assert not sweep_scoring.asks_user("")


def test_summary_counts_answers_that_ask_the_user() -> None:
    with tempfile.TemporaryDirectory() as raw:
        run_dir = pathlib.Path(raw) / "sweep-asks"
        plan = _new_sweep(run_dir, models=["m"], scenarios=("F1", "F2"))
        trials = sweep.round_trials(plan, "ring5s5h", 1)
        plan["rounds"].append({"topology": "ring5s5h", "round": 1, "trials": trials})
        sweep.save_plan(run_dir, plan)
        llm = [t for t in trials if t["method"] == "llm"]
        sweep.append_record(run_dir, _worker_record(llm[0], 1, asks_user=True))
        # A record from before the field existed: worked out from its saved answer.
        detail = pathlib.Path(raw) / "old.json"
        detail.write_text(json.dumps({"diagnosis_text": "The s3-s4 link is down."}), encoding="utf-8")
        sweep.append_record(run_dir, _worker_record(llm[1], 1, detail_file=str(detail)))
        for trial in trials:
            if trial["method"] == "baseline":
                sweep.append_record(run_dir, _worker_record(trial, 1, asks_user=None))
        summary = sweep.write_summary(run_dir).read_text(encoding="utf-8")
        section = summary.split("## Ended by asking the user")[1].split("##")[0]
        assert "| m | — | 1/2 (50%) | — | 1/2 (50%) |" in section, section
        assert "| baseline | — | — | — | — |" in section, section
        assert "coarse check" in summary
        assert "asks_user" not in json.loads((run_dir / "trials.jsonl").read_text().splitlines()[1]), (
            "the backfill only feeds the summary; trials.jsonl stays as written"
        )


def test_wilson_interval() -> None:
    low, high = sweep.wilson(8, 8)
    assert high == 1.0 and 0.6 < low < 0.7, (low, high)
    assert sweep.wilson(0, 0) == (0.0, 0.0)
    low, high = sweep.wilson(4, 8)
    assert low < 0.5 < high


def test_plan_command_runs_without_agent_dependencies() -> None:
    env = {k: v for k, v in os.environ.items() if k != "COMS6200_TOPOLOGY"}
    completed = subprocess.run(
        [sys.executable, "-m", "experiments.sweep", "plan", "--models", "m-a", "m-b"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    assert "One round:  15 trials on one topology" in completed.stdout, completed.stdout
    assert "min including a network restart per trial" in completed.stdout, completed.stdout
    assert "Target:     5 rounds x 3 topologies = 225 trials" in completed.stdout, completed.stdout


def test_list_models_reads_env_and_never_prints_secrets() -> None:
    with tempfile.TemporaryDirectory() as raw:
        env_file = pathlib.Path(raw) / ".env"
        env_file.write_text(
            "# comment\nexport CLOUDFLARE_ACCOUNT_ID='acct'\nCLOUDFLARE_AI_GATEWAY_ID=\"gw\"\n"
            "CLOUDFLARE_AI_GATEWAY_API_TOKEN=secret-token-123\nOTHER=x\n",
            encoding="utf-8",
        )
        with mock.patch.dict(os.environ, {"CLOUDFLARE_AI_GATEWAY_ID": "gw-env"}):
            values = list_models.settings(env_file)
    assert values["CLOUDFLARE_ACCOUNT_ID"] == "acct" and values["CLOUDFLARE_AI_GATEWAY_ID"] == "gw-env"
    assert values["CLOUDFLARE_AI_GATEWAY_API_TOKEN"] == "secret-token-123"
    assert list_models.chat_models(["gpt-5.6-luna", "gpt-4o-audio", "o4-mini", "text-embedding-3", "gpt-image-1"]) == [
        "gpt-5.6-luna", "o4-mini"]
    assert {"gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol", "gpt-6-astra"} <= list_models.configured_ids()

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    seen = {}

    def urlopen(request, timeout):
        seen["url"], seen["headers"] = request.full_url, dict(request.header_items())
        return Response(json.dumps({"data": [{"id": "gpt-5.6-luna"}, {"id": "gpt-x-mini"}]}).encode())

    out = io.StringIO()
    with mock.patch.object(list_models, "settings", return_value=values), \
            mock.patch("urllib.request.urlopen", urlopen), contextlib.redirect_stdout(out):
        assert list_models.main([]) == 0
    assert seen["url"].endswith("/acct/gw-env/openai/models"), seen["url"]
    assert seen["headers"]["Cf-aig-authorization"] == "Bearer secret-token-123"
    assert seen["headers"]["User-agent"] == "coms6200-list-models/1.0", "urllib's default UA gets error 1010"
    assert "gpt-x-mini" in out.getvalue() and "already in agent/config.py" in out.getvalue()
    assert "secret-token-123" not in out.getvalue()

    out = io.StringIO()
    with mock.patch.object(list_models, "settings", return_value={**values, "CLOUDFLARE_ACCOUNT_ID": ""}), \
            contextlib.redirect_stdout(out):
        assert list_models.main([]) == 1
    assert "CLOUDFLARE_ACCOUNT_ID" in out.getvalue() and "secret-token-123" not in out.getvalue()


def main() -> int:
    checks = (
        test_topologies_match_specs_and_catalogues,
        test_prompts_are_true_on_every_topology,
        test_rounds_are_complete_seeded_and_distinct,
        test_round_progress_and_next_topology,
        test_scoring_matches_frozen_evaluator_on_main6s8h,
        test_scoring_uses_each_topologies_fault_locations,
        test_baseline_location_strings_on_the_ring,
        test_run_trial_flow_and_isolation,
        test_repeating_a_topology_adds_rounds_and_resumes,
        test_run_stops_on_reset_failure_spend_cap_and_repeated_exclusions,
        test_asks_user_reads_only_the_final_paragraph,
        test_summary_counts_answers_that_ask_the_user,
        test_wilson_interval,
        test_plan_command_runs_without_agent_dependencies,
        test_list_models_reads_env_and_never_prints_secrets,
    )
    failed = 0
    for check in checks:
        try:
            check()
            print(f"PASS {check.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {check.__name__}: {exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
