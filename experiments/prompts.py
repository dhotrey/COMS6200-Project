"""Evaluator-side prompts and family ids. Not imported by the baseline."""

from __future__ import annotations

PROMPTS = {
    "F1": "h1 can no longer reach h5. Diagnose and localise the fault.",
    "F2": "Transfers from h1 to h5 are very slow. Investigate and localise the cause.",
    "F3": "h1 can no longer reach h5. Diagnose and localise the fault.",
    "F4": "h1 can no longer reach h5. Diagnose and localise the fault.",
    "F5": "h1 and h2 can no longer reach h5. Diagnose and localise the fault.",
}

FAMILIES = {
    "F1": "link_failure",
    "F2": "congestion",
    "F3": "policy_drop",
    "F4": "forwarding_loop",
    "F5": "missing_flow",
}

SCENARIOS = ("F1", "F2", "F3", "F4", "F5")
