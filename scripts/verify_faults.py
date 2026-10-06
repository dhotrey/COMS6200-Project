#!/usr/bin/env python3
"""Live, data-driven verification of the selected fault catalogue.

For each scenario: healthy gate, inject, check the expected symptoms
(faults/expectations.py) and family evidence, reset, healthy gate. Expected
counts come from the selected topology (COMS6200_TOPOLOGY) and its forwarding
plan, not from main6s8h literals.

For main6s8h the frozen record stays scripts/verify_fault_catalogue.sh.
Running this script there cross-checks the verifier itself.

Operator only: mutates the testbed. Requires root (does not call sudo) and
ONOS_USER / ONOS_PASSWORD. Not an LLM tool.

  sudo --preserve-env=COMS6200_TOPOLOGY,ONOS_USER,ONOS_PASSWORD \\
    python3 scripts/verify_faults.py [F1 F2 ...]
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from faults import injector  # noqa: E402
from faults.common import FaultError, iface_operstate, tc_show  # noqa: E402
from faults.expectations import EXPECTATIONS, SLOW_RATIO, Expectation  # noqa: E402
from faults.onos_experiment import list_experiment_flows, onos_client  # noqa: E402
from faults.registry import ACTIVE  # noqa: E402
from faults.scenarios import (  # noqa: E402
    AclScenario,
    CongestionScenario,
    LinkFailureScenario,
    LoopScenario,
    MissingFlowScenario,
    Scenario,
)
from forwarding.baseline_forwarding import (  # noqa: E402
    DEVICE_IDS,
    OnosClient,
    expected_flow_count,
    list_baseline_flows,
)
from telemetry.gateway import TelemetryGateway  # noqa: E402
from topologies.active import HOSTS, INTER_SWITCH_LINKS, TOPOLOGY  # noqa: E402

CONVERGE_TIMEOUT_S = 30.0
LOOP_SAMPLE_S = 2.0
# A running F4 loop circulates packets at the safety TBF rate (thousands per
# second). Without it the safety link carries only ONOS LLDP/BDDP.
LOOP_MIN_PACKETS = 100


class Checker:
    def __init__(self) -> None:
        self.failed = 0

    def check(self, ok: bool, label: str, detail: Any = None) -> bool:
        print(f"{'PASS' if ok else 'FAIL'}  {label}" + ("" if detail is None else f"  [{detail}]"))
        if not ok:
            self.failed += 1
        return ok


def _directed_links(client: OnosClient) -> int:
    return len(client.get("links").get("links") or [])


def _received(result: dict[str, Any]) -> int | None:
    if not result.get("ok"):
        return None
    return int((result.get("data") or {}).get("received", 0))


def _iperf_bps(gw: TelemetryGateway, src: str, dst: str) -> float | None:
    result = gw.iperf(src, dst, duration=3)
    data = result.get("data") or {}
    if not result.get("ok"):
        return None
    value = data.get("receiver_bits_per_sec") or data.get("sender_bits_per_sec")
    return float(value) if value is not None else None


def _tx_packets(iface: str) -> int:
    return int(Path("/sys/class/net", iface, "statistics", "tx_packets").read_text().strip())


def _shaped_ifaces() -> list[str]:
    assert ACTIVE is not None
    ifaces = []
    for scenario in ACTIVE.scenarios.values():
        if isinstance(scenario, CongestionScenario):
            ifaces.append(scenario.shape_iface)
        if isinstance(scenario, LoopScenario):
            ifaces.append(scenario.safety_iface)
    return ifaces


def _wait_links(client: OnosClient, want: int) -> int:
    deadline = time.time() + CONVERGE_TIMEOUT_S
    links = _directed_links(client)
    while links != want and time.time() < deadline:
        time.sleep(1.0)
        links = _directed_links(client)
    return links


def healthy_gate(chk: Checker, gw: TelemetryGateway, client: OnosClient, label: str) -> bool:
    print(f"===== HEALTHY GATE: {label} =====")
    results = []
    want_links = 2 * len(INTER_SWITCH_LINKS)
    links = _wait_links(client, want_links)
    results.append(chk.check(links == want_links, f"{label}: {links}/{want_links} directed links"))
    added = sum(1 for flow in list_baseline_flows(client) if flow.get("state") == "ADDED")
    want_flows = expected_flow_count()
    results.append(chk.check(added == want_flows, f"{label}: {added}/{want_flows} baseline flows ADDED"))
    experiment = len(list_experiment_flows(client))
    results.append(chk.check(experiment == 0, f"{label}: {experiment} experiment flows"))
    status = injector.status()
    active = bool((status.get("data") or {}).get("active"))
    results.append(chk.check(bool(status.get("ok")) and not active, f"{label}: no active fault", status.get("error")))
    shaped = [iface for iface in _shaped_ifaces() if "tbf" in tc_show(iface).lower()]
    results.append(chk.check(not shaped, f"{label}: no residual TBF", shaped or None))
    pairs = [(src, dst) for src in HOSTS for dst in HOSTS if src != dst]
    good = sum(1 for src, dst in pairs if (_received(gw.ping(src, dst, count=1)) or 0) > 0)
    results.append(chk.check(good == len(pairs), f"{label}: pingall {good}/{len(pairs)}"))
    return all(results)


def family_evidence(chk: Checker, client: OnosClient, gw: TelemetryGateway, scenario: Scenario) -> None:
    sid = scenario.scenario_id
    if isinstance(scenario, LinkFailureScenario):
        want = 2 * len(INTER_SWITCH_LINKS) - 2
        links = _wait_links(client, want)
        chk.check(links == want, f"{sid}: ONOS directed links {links}/{want}")
        for iface in scenario.interfaces:
            state = iface_operstate(iface)
            chk.check(state != "up", f"{sid}: {iface} is {state}")
    elif isinstance(scenario, CongestionScenario):
        shown = tc_show(scenario.shape_iface)
        chk.check("tbf" in shown.lower(), f"{sid}: TBF on {scenario.shape_iface}")
    elif isinstance(scenario, AclScenario):
        device = DEVICE_IDS[scenario.switch]
        # ONOS reports the empty (drop) treatment as [{"type": "NOACTION"}],
        # so a drop is a rule with no OUTPUT instruction.
        drops = [
            flow
            for flow in list_experiment_flows(client)
            if flow.get("deviceId") == device
            and not any(
                str(item.get("type", "")).upper() == "OUTPUT"
                for item in (flow.get("treatment") or {}).get("instructions") or []
            )
        ]
        chk.check(
            len(drops) == 1,
            f"{sid}: {len(drops)} experiment DROP rule(s) on {scenario.switch}",
            [(flow.get("treatment") or {}).get("instructions") for flow in drops] or None,
        )
    elif isinstance(scenario, LoopScenario):
        iface = scenario.safety_iface
        chk.check("tbf" in tc_show(iface).lower(), f"{sid}: safety TBF on {iface}")
        flows = len(list_experiment_flows(client))
        chk.check(flows == len(scenario.hops), f"{sid}: {flows}/{len(scenario.hops)} loop rules")
        gw.ping(scenario.src_host, scenario.dst_host, count=3)
        before = _tx_packets(iface)
        time.sleep(LOOP_SAMPLE_S)
        delta = _tx_packets(iface) - before
        chk.check(
            delta >= LOOP_MIN_PACKETS,
            f"{sid}: loop traffic on {iface}: {delta} packets in {LOOP_SAMPLE_S:.0f}s",
        )
    elif isinstance(scenario, MissingFlowScenario):
        count = len(list_baseline_flows(client))
        want = expected_flow_count() - 1
        chk.check(count == want, f"{sid}: {count}/{want} baseline flows")


def symptoms(
    chk: Checker,
    gw: TelemetryGateway,
    sid: str,
    expectation: Expectation,
    healthy_bps: float | None,
) -> None:
    for src, dst in expectation.unreachable:
        received = _received(gw.ping(src, dst, count=3))
        chk.check(received == 0, f"{sid}: {src}->{dst} fails", f"received={received}")
    for src, dst in expectation.reachable:
        received = _received(gw.ping(src, dst, count=3))
        chk.check((received or 0) > 0, f"{sid}: {src}->{dst} still works", f"received={received}")
    if expectation.slow is not None:
        src, dst = expectation.slow
        faulted = _iperf_bps(gw, src, dst)
        ratio = None if not healthy_bps or faulted is None else faulted / healthy_bps
        chk.check(
            ratio is not None and ratio <= SLOW_RATIO,
            f"{sid}: {src}->{dst} throughput ratio <= {SLOW_RATIO}",
            f"healthy={healthy_bps} faulted={faulted} ratio={ratio}",
        )


def verify_scenario(
    chk: Checker,
    gw: TelemetryGateway,
    client: OnosClient,
    scenario: Scenario,
    expectation: Expectation,
) -> bool:
    sid = scenario.scenario_id
    print(f"\n########## {sid} {scenario.fault_family}: {scenario.description} ##########")
    failed_before = chk.failed
    healthy_bps = _iperf_bps(gw, *expectation.slow) if expectation.slow else None
    if expectation.slow:
        chk.check(bool(healthy_bps), f"{sid}: healthy iperf measured", healthy_bps)
    result = injector.inject(sid)
    if not chk.check(bool(result.get("ok")), f"{sid}: injected", result.get("error")):
        return False
    try:
        family_evidence(chk, client, gw, scenario)
        symptoms(chk, gw, sid, expectation, healthy_bps)
    except (FaultError, OSError) as exc:
        chk.check(False, f"{sid}: evidence collection", exc)
    finally:
        reset = injector.reset()
        chk.check(bool(reset.get("ok")), f"{sid}: reset", reset.get("error"))
    return healthy_gate(chk, gw, client, f"after_{sid}") and chk.failed == failed_before


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("scenarios", nargs="*", help="scenario IDs (default: all, in order)")
    args = parser.parse_args(argv)
    if ACTIVE is None:
        print(f"ERROR: no fault catalogue for COMS6200_TOPOLOGY={TOPOLOGY}")
        return 1
    if os.geteuid() != 0:
        print("ERROR: ROOT_REQUIRED — run as root (this script does not invoke sudo).")
        return 1
    if not os.environ.get("ONOS_USER") or not os.environ.get("ONOS_PASSWORD"):
        print("ERROR: ONOS_USER and ONOS_PASSWORD must be set (values not printed).")
        return 1
    selected = [sid.upper() for sid in args.scenarios] or sorted(ACTIVE.scenarios)
    unknown = [sid for sid in selected if sid not in ACTIVE.scenarios]
    if unknown:
        print(f"ERROR: unknown scenario(s) {unknown}; runnable: {sorted(ACTIVE.runnable)}")
        return 1

    print(f"Topology: {TOPOLOGY}  catalogue: {ACTIVE.version} ({ACTIVE.status})")
    print(f"Scenarios: {' '.join(selected)}")
    chk = Checker()
    gw = TelemetryGateway()
    client = onos_client()
    if not healthy_gate(chk, gw, client, "start"):
        print(f"\nFault verification ({TOPOLOGY}, {ACTIVE.version}): FAILED (unhealthy start)")
        return 1
    passed = []
    for sid in selected:
        if not verify_scenario(chk, gw, client, ACTIVE.scenarios[sid], EXPECTATIONS[TOPOLOGY][sid]):
            break
        passed.append(sid)
    if chk.failed == 0:
        print(f"\nFault verification ({TOPOLOGY}, {ACTIVE.version}): ALL {len(passed)} SCENARIOS PASSED")
        return 0
    print(f"\nFault verification ({TOPOLOGY}, {ACTIVE.version}): FAILED ({chk.failed} check(s))")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
