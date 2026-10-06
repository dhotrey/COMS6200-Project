"""Fault catalogue for the selected topology (COMS6200_TOPOLOGY).

main6s8h uses the frozen Fault Catalogue v1 (faults/scenarios.py). ring5s5h
uses its own catalogue (faults/ring_scenarios.py) with the same scenario IDs,
families and handlers at ring locations.

Operator/evaluator only. Never imported by telemetry.
"""

from __future__ import annotations

from dataclasses import dataclass

from faults import ring_scenarios, scenarios
from faults.catalogue import FAULT_CATALOGUE_STATUS, FAULT_CATALOGUE_VERSION
from faults.scenarios import Scenario
from topologies.active import TOPOLOGY


@dataclass(frozen=True)
class Catalogue:
    topology: str
    version: str
    status: str
    scenarios: dict[str, Scenario]

    @property
    def runnable(self) -> frozenset[str]:
        return frozenset(self.scenarios)

    def require_scenario(self, scenario_id: object) -> Scenario:
        if not isinstance(scenario_id, str) or scenario_id not in self.scenarios:
            raise ValueError(f"unknown scenario; allowed runnable: {sorted(self.runnable)}")
        return self.scenarios[scenario_id]


CATALOGUES: dict[str, Catalogue] = {
    "main6s8h": Catalogue(
        "main6s8h", FAULT_CATALOGUE_VERSION, FAULT_CATALOGUE_STATUS, scenarios.SCENARIOS
    ),
    "ring5s5h": Catalogue(
        "ring5s5h",
        ring_scenarios.CATALOGUE_VERSION,
        ring_scenarios.CATALOGUE_STATUS,
        ring_scenarios.SCENARIOS,
    ),
}

ACTIVE: Catalogue | None = CATALOGUES.get(TOPOLOGY)
