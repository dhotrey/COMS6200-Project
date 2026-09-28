"""Protocol v1 scoring. Location and hedge rules are fixed here."""

from __future__ import annotations

import re
from typing import Any

from experiments.prompts import FAMILIES

_RANK = re.compile(r"(?i)most (?:likely|plausibly)\s+([^.;]+)")
_OR = re.compile(r"(?i)\s+\bor\b\s+")
_REVISION = re.compile(r"(?i)the actual (?:cause|fault) is|the cause is")

_FAMILY_PATTERNS = (
    ("link_failure", re.compile(r"(?i)link (?:failure|down)|port (?:is )?down|link is down")),
    ("congestion", re.compile(r"(?i)congest|contention|shaping|rate limit|constrained queue|queue buildup")),
    ("policy_drop", re.compile(r"(?i)\bdrop\b|policy|acl|filter|no action|noaction")),
    ("forwarding_loop", re.compile(r"(?i)\bloop\b|\bcycle\b")),
    ("missing_flow", re.compile(r"(?i)missing (?:flow|rule|forwarding)|absent (?:flow|rule)|no (?:baseline )?(?:forwarding )?(?:flow|rule)")),
)


def evaluate(result: dict[str, Any], scenario: str, *, method: str) -> dict[str, Any]:
    """Score one diagnostic result. scenario is evaluator-side only."""
    if scenario not in FAMILIES:
        return _error(f"unknown scenario {scenario}")
    if method == "baseline":
        family = result.get("diagnosis_family")
        location_text = result.get("diagnosis_location") or ""
        span = result.get("diagnosis_text") or ""
        family_correct = int(family == FAMILIES[scenario])
        location_correct = int(bool(location_text) and location_matches(scenario, str(location_text)))
        return _scores(span or str(location_text), family_correct, location_correct, None)
    if method == "llm":
        text = str(result.get("diagnosis_text") or "")
        span = primary_span(text)
        clauses, ranked = _clauses(span)
        found = _families(clauses)
        if not ranked and len(found) > 1:
            family_correct = 0
        else:
            family_correct = int(found == {FAMILIES[scenario]})
        location_correct = int(_location_bits(scenario, clauses, ranked))
        return _scores(span, family_correct, location_correct, None)
    return _error(f"unknown method {method}")


def primary_span(text: str) -> str:
    """Use the final conclusion, not a markdown heading or an opening plan."""
    body = "\n".join(line for line in text.splitlines() if not line.strip().startswith("#")).strip()
    if not body:
        return ""
    revisions = list(_REVISION.finditer(body))
    if revisions:
        return body[revisions[-1].start() :].strip()
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", body) if part.strip()]
    cue = re.compile(r"(?i)therefore|this looks|most (?:likely|plausibly)|the (?:cause|fault) is|localis")
    chosen = ""
    for paragraph in paragraphs:
        if cue.search(paragraph) or _families([paragraph]):
            chosen = paragraph
    return chosen or (paragraphs[-1] if paragraphs else "")


def location_matches(scenario: str, text: str) -> bool:
    predicates = {
        "F1": _f1,
        "F2": _f2,
        "F3": _f3,
        "F4": _f4,
        "F5": _f5,
    }
    return predicates[scenario](text.lower())


def _scores(span: str, family_correct: int, location_correct: int, error: str | None) -> dict[str, Any]:
    return {
        "family_correct": family_correct,
        "location_correct": location_correct,
        "full_diagnosis_correct": int(family_correct == 1 and location_correct == 1),
        "primary_conclusion_span": span,
        "evaluation_error": error,
    }


def _error(message: str) -> dict[str, Any]:
    scored = _scores("", 0, 0, message)
    scored["family_correct"] = None
    scored["location_correct"] = None
    scored["full_diagnosis_correct"] = None
    return scored


def _clauses(span: str) -> tuple[list[str], bool]:
    match = _RANK.search(span)
    if match:
        return [match.group(0).strip()], True
    parts = [part.strip() for part in _OR.split(span) if part.strip()]
    return parts or [span], False


def _families(clauses: list[str]) -> set[str]:
    found: set[str] = set()
    for clause in clauses:
        for name, pattern in _FAMILY_PATTERNS:
            if pattern.search(clause):
                found.add(name)
    return found


def _location_bits(scenario: str, clauses: list[str], ranked: bool) -> bool:
    if ranked:
        return location_matches(scenario, clauses[0])
    location_clauses = [clause for clause in clauses if _looks_like_location(clause)]
    if not location_clauses:
        return False
    return all(location_matches(scenario, clause) for clause in location_clauses)


def _looks_like_location(clause: str) -> bool:
    lowered = clause.lower()
    if re.search(r"\bs[1-6]\b|\bh[1-8]\b", lowered):
        return True
    return "beyond" in lowered or "host" in lowered


def _f1(text: str) -> bool:
    if re.search(r"s3\s*[-–—↔/]+\s*s1|s1\s*[-–—↔/]+\s*s3", text):
        return True
    if re.search(r"s3\s*(:|port\s*)1\b|s3-eth1", text):
        return True
    if re.search(r"s1\s*(:|port\s*)2\b|s1-eth2", text):
        return True
    return False


def _f2(text: str) -> bool:
    if re.search(r"s1\s*[-–—↔/]+\s*s5|s5\s*[-–—↔/]+\s*s1", text):
        return True
    if re.search(r"s1\s*(:|port\s*)4\b|s1-eth4", text):
        return True
    if re.search(r"s5\s*(:|port\s*)1\b|s5-eth1", text):
        return True
    return False


def _f3(text: str) -> bool:
    return bool(
        re.search(r"\bs3\b", text)
        and re.search(r"\bh1\b", text)
        and re.search(r"\bh5\b", text)
        and re.search(r"drop|policy|acl|filter|noaction|no action", text)
    )


def _f4(text: str) -> bool:
    if not all(re.search(rf"\b{name}\b", text) for name in ("s3", "s4", "s1")):
        return False
    if not (re.search(r"\bh1\b", text) and re.search(r"\bh5\b", text)):
        return False
    return bool(re.search(r"loop|cycle|->|→", text))


def _f5(text: str) -> bool:
    return bool(
        re.search(r"\bs3\b", text)
        and re.search(r"\bh5\b", text)
        and re.search(r"missing|absent|no (?:baseline )?(?:forwarding )?(?:flow|rule)", text)
    )
