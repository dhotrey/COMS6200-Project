"""Topology-aware scoring for the exploratory sweep (experiments/sweep.py).

Same rubric as protocol v1 (experiments/evaluator.py): the fault family comes
from the final conclusion span with its hedge rules, and the location must be
named in that span. The one difference is where the expected location comes
from: each topology's fault catalogue (faults/registry.py) instead of main6s8h
literals. For main6s8h the result matches the frozen evaluator
(tests/test_sweep.py). The frozen evaluator is not changed.

Evaluator-side only: never imported by telemetry, the agent or the baseline.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from experiments.evaluator import _clauses, _error, _families, _scores, primary_span
from experiments.prompts import FAMILIES
from faults.registry import CATALOGUES
from faults.scenarios import (
    AclScenario,
    CongestionScenario,
    LinkFailureScenario,
    LoopScenario,
    MissingFlowScenario,
    Scenario,
)
from topologies.active import SPECS

# Catalogue family names -> protocol v1 scoring families.
SCORING_FAMILY = {
    "link_failure": "link_failure",
    "congestion": "congestion",
    "acl_policy_error": "policy_drop",
    "forwarding_loop": "forwarding_loop",
    "missing_flow": "missing_flow",
}

_SEP = r"\s*[-–—↔/]+\s*"
_DROP = r"drop|policy|acl|filter|noaction|no action"
_MISSING = r"missing|absent|no (?:baseline )?(?:forwarding )?(?:flow|rule)"
_LOOP = r"loop|cycle|->|→"
_ASKS_USER = re.compile(
    r"(?i)\b(?:would you like|do you want|shall i|should i|can i|may i|let me know|please (?:confirm|specify|advise))\b"
)


def outcome(scored: dict[str, Any]) -> str:
    """success = family and location; partial = one of them; fail = neither."""
    if scored.get("evaluation_error"):
        return "error"
    hits = int(scored.get("family_correct") or 0) + int(scored.get("location_correct") or 0)
    return ("fail", "partial", "success")[hits]


def asks_user(answer: str) -> bool:
    """The answer ends by handing a question back to the user instead of concluding.

    A trial is one turn, so nobody answers. Only the final paragraph counts, so a
    question raised and answered earlier in the text does not. Analysis only: it
    changes no score.
    """
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", answer.strip()) if part.strip()]
    last = paragraphs[-1] if paragraphs else ""
    return "?" in last and bool(_ASKS_USER.search(last))


def location_matcher(scenario: Scenario) -> Callable[[str], bool]:
    """Predicate over lower-cased text, built from where the fault was placed."""
    if isinstance(scenario, (LinkFailureScenario, CongestionScenario)):
        link = scenario.link
        a, b = re.escape(link.a), re.escape(link.b)
        patterns = [
            rf"{a}{_SEP}{b}|{b}{_SEP}{a}",
            rf"{a}\s*(:|port\s*){link.a_port}\b|{a}-eth{link.a_port}",
            rf"{b}\s*(:|port\s*){link.b_port}\b|{b}-eth{link.b_port}",
        ]
        return lambda text: any(re.search(pattern, text) for pattern in patterns)
    if isinstance(scenario, AclScenario):
        names = (scenario.switch, scenario.src_host, scenario.dst_host)
        return lambda text: _all_named(text, names) and bool(re.search(_DROP, text))
    if isinstance(scenario, LoopScenario):
        names = tuple(dict.fromkeys(hop.switch for hop in scenario.hops))
        names += (scenario.src_host, scenario.dst_host)
        return lambda text: _all_named(text, names) and bool(re.search(_LOOP, text))
    if isinstance(scenario, MissingFlowScenario):
        names = (scenario.switch, scenario.dst_host)
        return lambda text: _all_named(text, names) and bool(re.search(_MISSING, text))
    raise ValueError(f"no location rule for {type(scenario).__name__}")


def _all_named(text: str, names: tuple[str, ...]) -> bool:
    return all(re.search(rf"\b{re.escape(name)}\b", text) for name in names)


def _location_clause_detector(topology: str) -> Callable[[str], bool]:
    """Protocol v1 rule: a clause is a location if it names a switch or host."""
    spec = SPECS[topology]
    names = "|".join(re.escape(name) for name in (*spec.SWITCHES, *spec.HOSTS))
    pattern = re.compile(rf"\b(?:{names})\b")
    return lambda clause: bool(pattern.search(clause.lower())) or any(
        word in clause.lower() for word in ("beyond", "host")
    )


def score(topology: str, scenario_id: str, result: dict[str, Any], *, method: str) -> dict[str, Any]:
    """Score one diagnosis against the fault placed on that topology."""
    catalogue = CATALOGUES.get(topology)
    if catalogue is None or scenario_id not in catalogue.scenarios or scenario_id not in FAMILIES:
        return _error(f"unknown topology/scenario {topology}/{scenario_id}")
    scenario = catalogue.scenarios[scenario_id]
    expected_family = FAMILIES[scenario_id]
    if SCORING_FAMILY.get(scenario.fault_family) != expected_family:
        return _error(f"{topology} {scenario_id} family {scenario.fault_family} != {expected_family}")
    matches = location_matcher(scenario)

    if method == "baseline":
        location = str(result.get("diagnosis_location") or "")
        family_correct = int(result.get("diagnosis_family") == expected_family)
        location_correct = int(bool(location) and matches(location.lower()))
        span = str(result.get("diagnosis_text") or "") or location
        return _scores(span, family_correct, location_correct, None)
    if method == "llm":
        span = primary_span(str(result.get("diagnosis_text") or ""))
        clauses, ranked = _clauses(span)
        found = _families(clauses)
        if not ranked and len(found) > 1:
            family_correct = 0
        else:
            family_correct = int(found == {expected_family})
        if ranked:
            location_correct = matches(clauses[0].lower())
        else:
            is_location = _location_clause_detector(topology)
            located = [clause for clause in clauses if is_location(clause)]
            location_correct = bool(located) and all(matches(clause.lower()) for clause in located)
        return _scores(span, family_correct, int(location_correct), None)
    return _error(f"unknown method {method}")
