"""Authoritative protocol-v1 run order.

Generated with CPython 3.12.3 random.Random(seed).shuffle. If regeneration
disagrees, keep these lists and stop.
"""

from __future__ import annotations

import random
import sys

LLM_SEED = 6200
BASELINE_SEED = 6201

LLM_ORDER: tuple[tuple[str, int], ...] = (
    ("F1", 5), ("F5", 6), ("F4", 7), ("F3", 2), ("F3", 3),
    ("F4", 3), ("F1", 6), ("F2", 3), ("F4", 2), ("F4", 4),
    ("F5", 2), ("F5", 5), ("F1", 4), ("F3", 8), ("F2", 6),
    ("F1", 8), ("F3", 7), ("F3", 5), ("F4", 8), ("F4", 1),
    ("F2", 1), ("F5", 1), ("F3", 6), ("F3", 1), ("F2", 7),
    ("F5", 3), ("F2", 5), ("F1", 1), ("F4", 5), ("F4", 6),
    ("F3", 4), ("F1", 7), ("F2", 2), ("F5", 8), ("F2", 4),
    ("F5", 4), ("F1", 2), ("F5", 7), ("F1", 3), ("F2", 8),
)

BASELINE_ORDER: tuple[tuple[str, int], ...] = (
    ("F1", 1), ("F5", 8), ("F5", 5), ("F1", 2), ("F1", 7),
    ("F3", 5), ("F3", 7), ("F4", 5), ("F4", 1), ("F5", 4),
    ("F2", 3), ("F3", 1), ("F1", 3), ("F4", 8), ("F4", 2),
    ("F4", 7), ("F3", 3), ("F1", 4), ("F2", 6), ("F3", 4),
    ("F2", 5), ("F2", 1), ("F1", 8), ("F3", 6), ("F2", 8),
    ("F4", 4), ("F3", 2), ("F1", 5), ("F5", 3), ("F5", 6),
    ("F2", 4), ("F2", 2), ("F4", 6), ("F3", 8), ("F2", 7),
    ("F5", 2), ("F5", 1), ("F1", 6), ("F5", 7), ("F4", 3),
)


def generated_order(seed: int) -> list[tuple[str, int]]:
    pairs = [(scenario, rep) for scenario in ("F1", "F2", "F3", "F4", "F5") for rep in range(1, 9)]
    random.Random(seed).shuffle(pairs)
    return pairs


def order_mismatch() -> str | None:
    llm = generated_order(LLM_SEED)
    baseline = generated_order(BASELINE_SEED)
    if llm != list(LLM_ORDER):
        return (
            f"LLM shuffle seed {LLM_SEED} on Python {sys.version.split()[0]} "
            "does not match the protocol-v1 list"
        )
    if baseline != list(BASELINE_ORDER):
        return (
            f"baseline shuffle seed {BASELINE_SEED} on Python {sys.version.split()[0]} "
            "does not match the protocol-v1 list"
        )
    return None
