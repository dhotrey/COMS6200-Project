"""Protocol v1 evaluator tests. These lock the rubric before formal answers exist."""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from experiments.evaluator import evaluate, location_matches  # noqa: E402


def test_locations() -> None:
    assert location_matches("F1", "s3 port 1")
    assert location_matches("F1", "s1 port 2")
    assert location_matches("F1", "s3-s1")
    assert not location_matches("F1", "s3")
    assert not location_matches("F1", "s1")
    assert location_matches("F2", "s1 port 4")
    assert location_matches("F2", "s5 port 1")
    assert location_matches("F2", "s1-s5")
    assert not location_matches("F2", "h1-h5")
    assert not location_matches("F2", "s5-h5")
    assert location_matches("F3", "policy drop on s3 for h1 toward h5")
    assert not location_matches("F3", "drop on s3")
    assert location_matches("F4", "forwarding cycle s3 -> s4 -> s1 -> s3 for h1 to h5")
    assert not location_matches("F4", "loop on s1 for h1 to h5")
    assert location_matches("F5", "missing forwarding rule for h5 on s3")
    assert not location_matches("F5", "missing rule for h5")


def test_hedges_and_baseline_fields() -> None:
    hedged = evaluate(
        {"diagnosis_text": "Most likely congestion on s1 port 4, though delay was considered."},
        "F2",
        method="llm",
    )
    assert hedged["family_correct"] == 1
    assert hedged["location_correct"] == 1
    assert hedged["full_diagnosis_correct"] == 1
    assert "Most likely" in hedged["primary_conclusion_span"]

    unranked = evaluate(
        {"diagnosis_text": "The impairment is s1-s5 or immediately beyond."},
        "F2",
        method="llm",
    )
    assert unranked["location_correct"] == 0
    assert unranked["full_diagnosis_correct"] == 0

    mixed = evaluate(
        {"diagnosis_text": "This could be congestion or a drop rule."},
        "F2",
        method="llm",
    )
    assert mixed["family_correct"] == 0

    vague = evaluate({"diagnosis_text": "s3 is involved."}, "F1", method="llm")
    assert vague["location_correct"] == 0
    headed = evaluate(
        {
            "diagnosis_text": (
                "### Diagnosis\n\n"
                "The slowdown localises to the s1-s5 link.\n\n"
                "Therefore, this looks like rate limiting on s1 port 4, rather than a failed link."
            )
        },
        "F2",
        method="llm",
    )
    assert headed["full_diagnosis_correct"] == 1
    assert headed["primary_conclusion_span"].startswith("Therefore")

    baseline = evaluate(
        {
            "diagnosis_family": "link_failure",
            "diagnosis_location": "s3 port 1 to s1 port 2",
            "diagnosis_text": "Link failure on s3 port 1 to s1 port 2.",
        },
        "F1",
        method="baseline",
    )
    assert baseline["full_diagnosis_correct"] == 1

    unknown = evaluate(
        {"diagnosis_family": None, "diagnosis_location": None, "diagnosis_text": "No conclusion."},
        "F5",
        method="baseline",
    )
    assert unknown["family_correct"] == 0
    assert unknown["location_correct"] == 0
    assert unknown["evaluation_error"] is None


def main() -> int:
    failed = 0
    for check in (test_locations, test_hedges_and_baseline_fields):
        try:
            check()
            print(f"PASS {check.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {check.__name__}: {type(exc).__name__}: {exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
