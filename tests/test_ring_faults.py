"""Static checks for the ring5s5h fault catalogue and catalogue selection.

Does not contact ONOS or Mininet and mutates nothing. A packet walk over the
baseline forwarding tables, with each scenario's fault applied, checks that
the symptoms in faults/expectations.py follow from where the fault is placed:
for main6s8h (restating the frozen v1 scripts) and for ring5s5h.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
from types import ModuleType
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "forwarding"))
sys.path.insert(0, str(ROOT))

# In-process checks use the main6s8h literals; ring checks pass ring data
# explicitly or run in a subprocess.
os.environ["COMS6200_TOPOLOGY"] = "main6s8h"

import baseline_forwarding as bf  # noqa: E402
from faults import injector as inj  # noqa: E402
from faults import ring_scenarios, scenarios  # noqa: E402
from faults import state as fault_state  # noqa: E402
from faults.expectations import EXPECTATIONS  # noqa: E402
from faults.registry import CATALOGUES  # noqa: E402
from faults.scenarios import (  # noqa: E402
    AclScenario,
    CongestionScenario,
    LinkFailureScenario,
    LoopScenario,
    MissingFlowScenario,
    Scenario,
)
from topologies import ring_spec  # noqa: E402
from topologies import spec as main_spec  # noqa: E402

RING_UNICAST = bf.tree_forwarding(
    ring_spec.SWITCHES, ring_spec.INTER_SWITCH_LINKS, ring_spec.HOST_ATTACHMENTS, bf.RING_RESERVED_LINKS
)[0]
PLANS: dict[str, tuple[ModuleType, dict[str, dict[str, int]], dict[str, Scenario]]] = {
    "main6s8h": (main_spec, bf.UNICAST_EGRESS, scenarios.SCENARIOS),
    "ring5s5h": (ring_spec, RING_UNICAST, ring_scenarios.SCENARIOS),
}
RING_PORTS = {f"s{n}-eth{p}" for n in range(1, 6) for p in range(1, 4)}

Overlay = tuple[set[tuple[str, int]], dict[tuple[str, str, str], int | None], set[tuple[str, str]]]


def _overlay(scenario: Scenario | None) -> Overlay:
    """(down switch ports, experiment rules (switch, src, dst) -> port|None=drop, removed (switch, dst))."""
    down: set[tuple[str, int]] = set()
    rules: dict[tuple[str, str, str], int | None] = {}
    removed: set[tuple[str, str]] = set()
    if isinstance(scenario, LinkFailureScenario):
        down = {(end.switch, end.port) for end in scenario.endpoints}
    elif isinstance(scenario, AclScenario):
        rules[(scenario.switch, scenario.src_host, scenario.dst_host)] = None
    elif isinstance(scenario, LoopScenario):
        for hop in scenario.hops:
            rules[(hop.switch, scenario.src_host, scenario.dst_host)] = hop.out_port
    elif isinstance(scenario, MissingFlowScenario):
        removed = {(scenario.switch, scenario.dst_host)}
    return down, rules, removed


def _walk(
    spec: ModuleType, unicast: dict[str, dict[str, int]], src: str, dst: str, overlay: Overlay
) -> tuple[str, list[tuple[str, int]]]:
    """Follow one src->dst frame: ('delivered'|'dropped'|'looped', egress switch ports)."""
    down, rules, removed = overlay
    switch = next(a.switch for a in spec.HOST_ATTACHMENTS if a.host == src and a.role == "primary")
    path: list[tuple[str, int]] = []
    for _hop in range(3 * len(spec.SWITCHES)):
        rule = rules.get((switch, src, dst), -1)
        if rule is None:
            return "dropped", path
        if rule != -1:
            port = rule
        elif (switch, dst) in removed or dst not in unicast.get(switch, {}):
            return "dropped", path
        else:
            port = unicast[switch][dst]
        peer = spec.peer_of(switch, port)
        if (switch, port) in down or peer is None:
            return "dropped", path
        path.append((switch, port))
        if peer["kind"] == "host":
            return ("delivered" if peer["id"] == dst else "dropped"), path
        switch = str(peer["id"])
    return "looped", path


def _ping(spec: ModuleType, unicast: dict[str, dict[str, int]], src: str, dst: str, overlay: Overlay) -> bool:
    return (
        _walk(spec, unicast, src, dst, overlay)[0] == "delivered"
        and _walk(spec, unicast, dst, src, overlay)[0] == "delivered"
    )


def test_expectations_cover_every_catalogue() -> None:
    assert set(EXPECTATIONS) == set(CATALOGUES), sorted(EXPECTATIONS)
    for topology, catalogue in CATALOGUES.items():
        assert set(EXPECTATIONS[topology]) == set(catalogue.scenarios), topology
        hosts = set(PLANS[topology][0].HOSTS)
        for sid, expectation in EXPECTATIONS[topology].items():
            pairs = list(expectation.unreachable) + list(expectation.reachable)
            pairs += [expectation.slow] if expectation.slow else []
            assert pairs, (topology, sid)
            assert {host for pair in pairs for host in pair} <= hosts, (topology, sid, pairs)


def test_expected_symptoms_follow_from_fault_placement() -> None:
    for topology, (spec, unicast, catalogue) in PLANS.items():
        healthy = _overlay(None)
        for sid, expectation in EXPECTATIONS[topology].items():
            overlay = _overlay(catalogue[sid])
            for src, dst in expectation.unreachable:
                assert _ping(spec, unicast, src, dst, healthy), (topology, sid, "healthy", src, dst)
                assert not _ping(spec, unicast, src, dst, overlay), (topology, sid, "should fail", src, dst)
            for src, dst in expectation.reachable:
                assert _ping(spec, unicast, src, dst, overlay), (topology, sid, "should work", src, dst)
            if expectation.slow:
                assert _ping(spec, unicast, *expectation.slow, overlay), (topology, sid, "slow pair")


def test_congestion_bottleneck_is_on_target_and_background_paths() -> None:
    for topology, (spec, unicast, catalogue) in PLANS.items():
        f2 = catalogue["F2"]
        assert isinstance(f2, CongestionScenario)
        shaped = next((e.switch, e.port) for e in f2.endpoints if e.switch == f2.shape_switch)
        assert f2.shape_iface == f"{shaped[0]}-eth{shaped[1]}"
        for src, dst in ((f2.target_src, f2.target_dst), (f2.background_src, f2.background_dst)):
            outcome, path = _walk(spec, unicast, src, dst, _overlay(None))
            assert outcome == "delivered" and shaped in path, (topology, src, dst, path)


def test_loop_circulates_through_safety_link() -> None:
    for topology, (spec, unicast, catalogue) in PLANS.items():
        f4 = catalogue["F4"]
        assert isinstance(f4, LoopScenario)
        outcome, path = _walk(spec, unicast, f4.src_host, f4.dst_host, _overlay(f4))
        link = f4.safety_link
        ends = ((link.a, link.a_port), (link.b, link.b_port))
        safety = next(end for end in ends if end[0] == f4.safety_shape_switch)
        assert outcome == "looped", (topology, outcome, path)
        assert path[-len(f4.hops):].count(safety) == 1, (topology, path)
        for hop in f4.hops:
            peer = spec.peer_of(hop.switch, hop.out_port)
            assert peer is not None and peer["kind"] == "switch", (topology, hop)


def test_ring_placement() -> None:
    f1, f2, f3, f4, f5 = (ring_scenarios.SCENARIOS[sid] for sid in ("F1", "F2", "F3", "F4", "F5"))
    assert set(f1.interfaces) == {"s3-eth1", "s4-eth2"}
    assert f2.shape_iface == "s2-eth1" and (f2.background_src, f2.background_dst) == ("h2", "h4")
    assert f3.switch == "s4"
    assert f4.safety_iface == "s5-eth1"
    assert (f4.safety_link,) == bf.RING_RESERVED_LINKS, "F4 must loop over the link baseline leaves unused"
    assert (f5.switch, f5.dst_host) == ("s2", "h5")
    for scenario in ring_scenarios.SCENARIOS.values():
        assert scenario.ground_truth()["catalogue_version"] == "ring5s5h-v1"
        assert scenario.catalogue_version == ring_scenarios.CATALOGUE_VERSION
    for scenario in scenarios.SCENARIOS.values():
        assert scenario.ground_truth()["catalogue_version"] == "v1"
    ifaces = set(f1.interfaces) | {f2.shape_iface, f4.safety_iface}
    assert ifaces <= RING_PORTS, ifaces


def _subprocess_json(code: str, topology: str, extra_env: dict[str, str] | None = None) -> dict:
    env = dict(os.environ, COMS6200_TOPOLOGY=topology, PYTHONPATH=str(ROOT), **(extra_env or {}))
    completed = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_selected_catalogue_and_f5_target() -> None:
    code = (
        "import json\n"
        "from faults import f5_missing as f5\n"
        "from faults.registry import ACTIVE\n"
        "from forwarding.baseline_forwarding import expected_flow_count, expected_flow_specs\n"
        "target = f5._target_spec(ACTIVE.scenarios['F5'])\n"
        "print(json.dumps({'version': ACTIVE.version, 'status': ACTIVE.status,\n"
        "  'runnable': sorted(ACTIVE.runnable), 'switch': target.switch, 'outputs': target.outputs,\n"
        "  'in_plan': target in expected_flow_specs(), 'flows': expected_flow_count()}))\n"
    )
    main = _subprocess_json(code, "main6s8h")
    assert (main["version"], main["status"]) == ("v1", "frozen"), main
    assert (main["switch"], main["outputs"], main["in_plan"], main["flows"]) == ("s3", [1], True, 56), main
    ring = _subprocess_json(code, "ring5s5h")
    assert (ring["version"], ring["status"]) == ("ring5s5h-v1", "draft"), ring
    assert ring["runnable"] == ["F1", "F2", "F3", "F4", "F5"]
    assert (ring["switch"], ring["outputs"], ring["in_plan"], ring["flows"]) == ("s2", [1], True, 38), ring


def test_datapath_guard_main6s8h() -> None:
    main_ports = inj.expected_switch_interfaces()
    assert len(main_ports) == 29 and "s6-eth5" in main_ports
    with mock.patch.object(inj, "_switch_interfaces", return_value=set(main_ports)):
        inj._require_selected_datapath()
    with mock.patch.object(inj, "_switch_interfaces", return_value=set(RING_PORTS)):
        try:
            inj._require_selected_datapath()
        except inj.FaultError as exc:
            assert exc.code == "TOPOLOGY_MISMATCH"
            assert "s6-eth1" in exc.details["missing"] and not exc.details["unexpected"], exc.details
        else:
            raise AssertionError("ring datapath must be rejected for main6s8h")


def test_inject_checks_datapath_before_mutating() -> None:
    """sudo can drop COMS6200_TOPOLOGY; the datapath check still stops main F1 on a ring."""
    handler = mock.Mock(return_value={})
    with tempfile.TemporaryDirectory() as raw:
        directory = pathlib.Path(raw)
        with mock.patch.object(fault_state, "STATE_DIR", directory), \
                mock.patch.object(fault_state, "STATE_PATH", directory / "fault-state.json"), \
                mock.patch.object(os, "geteuid", return_value=0, create=True), \
                mock.patch.object(inj, "_switch_interfaces", return_value=set(RING_PORTS)), \
                mock.patch.dict(inj._INJECTORS, {"F1": handler}):
            result = inj.inject("F1")
    assert result["ok"] is False and result["error"]["code"] == "TOPOLOGY_MISMATCH", result
    handler.assert_not_called()


def test_ring_guards_in_subprocess() -> None:
    code = (
        "import json, os\n"
        "from unittest import mock\n"
        "from faults import injector as inj\n"
        "main_ports = {f's{n}-eth{p}' for n, ports in {1: range(1, 6), 2: range(1, 6), 3: range(1, 6),\n"
        "  4: range(1, 6), 5: range(1, 5), 6: range(1, 6)}.items() for p in ports}\n"
        "out = {'expected': sorted(inj.expected_switch_interfaces())}\n"
        "handler = mock.Mock(return_value={})\n"
        "with mock.patch.object(os, 'geteuid', return_value=0, create=True), \\\n"
        "        mock.patch.object(inj, '_switch_interfaces', return_value=main_ports), \\\n"
        "        mock.patch.dict(inj._INJECTORS, {'F1': handler}):\n"
        "    result = inj.inject('F1')\n"
        "out['inject_on_main'] = result['error']['code']\n"
        "out['unexpected'] = (result['error'].get('details') or {}).get('unexpected')\n"
        "out['handler_called'] = handler.called\n"
        "with mock.patch.object(inj, '_switch_interfaces', return_value=set(out['expected'])):\n"
        "    inj._require_selected_datapath()\n"
        "status = inj.status()\n"
        "out['status'] = [status['ok'], status['data']['catalogue_version'], status['data']['topology']]\n"
        "reset = inj.reset()\n"
        "out['reset'] = reset['error']['code'] if not reset['ok'] else reset['data'].get('status')\n"
        "print(json.dumps(out))\n"
    )
    with tempfile.TemporaryDirectory() as raw:
        state = pathlib.Path(raw) / "fault-state.json"
        state.write_text(
            json.dumps(
                {"status": "ACTIVE", "scenario_id": "F1", "ground_truth": {"catalogue_version": "v1"}}
            ),
            encoding="utf-8",
        )
        result = _subprocess_json(code, "ring5s5h", {"COMS6200_FAULT_STATE_DIR": raw})
        assert state.exists(), "a refused reset must keep the state file"
    assert set(result["expected"]) == RING_PORTS, result["expected"]
    assert result["inject_on_main"] == "FAULT_ALREADY_ACTIVE", result
    assert result["status"] == [True, "ring5s5h-v1", "ring5s5h"], result
    assert result["reset"] == "STATE_CATALOGUE_MISMATCH", result

    with tempfile.TemporaryDirectory() as raw:
        result = _subprocess_json(code, "ring5s5h", {"COMS6200_FAULT_STATE_DIR": raw})
    assert result["inject_on_main"] == "TOPOLOGY_MISMATCH" and not result["handler_called"], result
    assert {"s1-eth4", "s6-eth1"} <= set(result["unexpected"]), result
    assert result["reset"] == "IDLE", result


def test_protocol_v1_runner_refuses_ring() -> None:
    code = (
        "import json\n"
        "from experiments.runner import topology_error\n"
        "print(json.dumps({'error': topology_error()}))\n"
    )
    assert _subprocess_json(code, "main6s8h")["error"] is None
    assert "protocol v1 runs on main6s8h" in _subprocess_json(code, "ring5s5h")["error"]


def test_live_verifier_is_data_driven() -> None:
    source = (ROOT / "scripts" / "verify_faults.py").read_text(encoding="utf-8")
    compile(source, "verify_faults.py", "exec")
    for needle in ("EXPECTATIONS[TOPOLOGY]", "expected_flow_count()", "2 * len(INTER_SWITCH_LINKS)"):
        assert needle in source, needle
    for literal in ("56", "20 directed", '"h6"', "s1-eth4", "s3-eth5"):
        assert literal not in source, f"verifier hard-codes {literal}"


def test_verifier_counts_onos_noaction_as_drop() -> None:
    """ONOS reports an empty (drop) treatment as [{"type": "NOACTION"}]."""
    import importlib.util

    module_spec = importlib.util.spec_from_file_location("verify_faults", ROOT / "scripts" / "verify_faults.py")
    assert module_spec is not None and module_spec.loader is not None
    verifier = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(verifier)
    f3 = scenarios.F3
    device = verifier.DEVICE_IDS[f3.switch]
    noaction = {"deviceId": device, "treatment": {"instructions": [{"type": "NOACTION"}]}}
    output = {"deviceId": device, "treatment": {"instructions": [{"type": "OUTPUT", "port": "1"}]}}
    for flows, failures in (([noaction], 0), ([output], 1), ([noaction, output], 0)):
        checker = verifier.Checker()
        with mock.patch.object(verifier, "list_experiment_flows", return_value=flows), \
                contextlib.redirect_stdout(io.StringIO()):
            verifier.family_evidence(checker, None, None, f3)
        assert checker.failed == failures, (flows, checker.failed)


def main() -> int:
    checks = (
        test_expectations_cover_every_catalogue,
        test_expected_symptoms_follow_from_fault_placement,
        test_congestion_bottleneck_is_on_target_and_background_paths,
        test_loop_circulates_through_safety_link,
        test_ring_placement,
        test_selected_catalogue_and_f5_target,
        test_datapath_guard_main6s8h,
        test_inject_checks_datapath_before_mutating,
        test_ring_guards_in_subprocess,
        test_protocol_v1_runner_refuses_ring,
        test_live_verifier_is_data_driven,
        test_verifier_counts_onos_noaction_as_drop,
    )
    failed = 0
    for check in checks:
        try:
            check()
            print(f"PASS {check.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {check.__name__}: {exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
