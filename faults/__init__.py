"""M5/M5B operator fault injector (Fault Catalogue v1: F1–F5).

Evaluator/operator only. Not imported by telemetry. Not an LLM tool.
"""

from faults.catalogue import FAULT_CATALOGUE_VERSION
from faults.injector import inject, reset, status
from faults.scenarios import F1, F2, F3, F4, F5, RUNNABLE, SCENARIOS

__all__ = [
    "FAULT_CATALOGUE_VERSION",
    "F1",
    "F2",
    "F3",
    "F4",
    "F5",
    "RUNNABLE",
    "SCENARIOS",
    "inject",
    "reset",
    "status",
]
