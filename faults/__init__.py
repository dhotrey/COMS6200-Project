"""M5 operator fault injector (F1 link failure + reset).

Evaluator/operator only. Not imported by telemetry. Not an LLM tool.
"""

from faults.injector import inject, reset, status
from faults.scenarios import F1, RUNNABLE, SCENARIOS

__all__ = ["F1", "RUNNABLE", "SCENARIOS", "inject", "reset", "status"]
