"""Expected observable symptoms per catalogue scenario, for operator verification.

scripts/verify_faults.py checks these live. tests/test_ring_faults.py checks
them statically against a packet walk over the baseline forwarding tables.
The main6s8h entries restate what the frozen v1 verify_fault_f*.sh scripts
check; they are not a new definition of Fault Catalogue v1.

Operator/evaluator only. Never imported by telemetry or given to the agent.
"""

from __future__ import annotations

from dataclasses import dataclass

# Same threshold as scripts/verify_fault_f2.sh (DEGRADE_MAX_RATIO).
SLOW_RATIO = 0.25

Pair = tuple[str, str]


@dataclass(frozen=True)
class Expectation:
    unreachable: tuple[Pair, ...] = ()  # ping src->dst must receive nothing
    reachable: tuple[Pair, ...] = ()  # ping src->dst must still get replies
    slow: Pair | None = None  # iperf src->dst must fall to SLOW_RATIO of healthy or less


EXPECTATIONS: dict[str, dict[str, Expectation]] = {
    "main6s8h": {
        "F1": Expectation(unreachable=(("h1", "h5"),), reachable=(("h1", "h2"), ("h3", "h5"))),
        "F2": Expectation(reachable=(("h1", "h5"),), slow=("h1", "h5")),
        "F3": Expectation(unreachable=(("h1", "h5"),), reachable=(("h2", "h5"), ("h1", "h6"))),
        "F4": Expectation(unreachable=(("h1", "h5"),), reachable=(("h1", "h2"), ("h3", "h5"))),
        "F5": Expectation(
            unreachable=(("h1", "h5"), ("h2", "h5")),
            reachable=(("h1", "h6"), ("h3", "h5")),
        ),
    },
    "ring5s5h": {
        "F1": Expectation(
            unreachable=(("h1", "h5"), ("h3", "h4")),
            reachable=(("h1", "h2"), ("h1", "h3"), ("h4", "h5")),
        ),
        "F2": Expectation(reachable=(("h1", "h5"),), slow=("h1", "h5")),
        "F3": Expectation(
            unreachable=(("h1", "h5"),),
            reachable=(("h2", "h5"), ("h1", "h4"), ("h3", "h5")),
        ),
        "F4": Expectation(
            unreachable=(("h1", "h5"),),
            reachable=(("h1", "h2"), ("h2", "h5"), ("h3", "h5")),
        ),
        "F5": Expectation(
            unreachable=(("h1", "h5"), ("h2", "h5")),
            reachable=(("h3", "h5"), ("h4", "h5"), ("h1", "h4")),
        ),
    },
    "tree5s8h": {
        "F1": Expectation(unreachable=(('h1', 'h5'),), reachable=(('h5', 'h6'), ('h7', 'h8'))),
        "F2": Expectation(reachable=(('h1', 'h5'),), slow=('h1', 'h5')),
        "F3": Expectation(unreachable=(('h1', 'h5'),), reachable=(('h2', 'h5'), ('h3', 'h5'))),
        "F4": Expectation(unreachable=(('h1', 'h5'),), reachable=(('h3', 'h5'), ('h7', 'h8'))),
        "F5": Expectation(unreachable=(('h1', 'h5'), ('h2', 'h5')), reachable=(('h5', 'h6'), ('h1', 'h6'))),
    },
}
