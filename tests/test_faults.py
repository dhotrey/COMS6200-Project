"""Static checks for Fault Catalogue v1 (F1–F5).

Does not mutate live interfaces. Runtime evidence is collected separately.
"""

from __future__ import annotations

import ast
import json
import os
import pathlib
import stat
import subprocess
import sys
import tempfile
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from faults import envelope  # noqa: E402
from faults import injector as inj  # noqa: E402
from faults.catalogue import FAULT_CATALOGUE_VERSION  # noqa: E402
from faults.scenarios import (  # noqa: E402
    EXPERIMENT_APP_ID,
    EXPERIMENT_PRIORITY,
    F1,
    F2,
    F3,
    F4,
    F5,
    RUNNABLE,
    SCENARIOS,
    require_scenario,
)
from faults import state as fault_state  # noqa: E402
from telemetry.schemas import TOOL_SCHEMAS  # noqa: E402


def test_catalogue_version_and_runnable() -> None:
    assert FAULT_CATALOGUE_VERSION == "v1"
    assert set(SCENARIOS) == {"F1", "F2", "F3", "F4", "F5"}
    assert RUNNABLE == frozenset(SCENARIOS)


def test_f1_unchanged_mapping() -> None:
    assert F1.scenario_id == "F1"
    assert F1.fault_family == "link_failure"
    ports = {e.switch: e.port for e in F1.endpoints}
    assert ports["s3"] == 1 and ports["s1"] == 2
    assert set(F1.interfaces) == {"s3-eth1", "s1-eth2"}


def test_f2_canonical_link_and_fixed_rates() -> None:
    assert F2.fault_family == "congestion"
    ports = {e.switch: e.port for e in F2.endpoints}
    assert ports["s1"] == 4 and ports["s5"] == 1
    assert F2.shape_iface == "s1-eth4"
    assert F2.rate == "1mbit"
    assert F2.background_src == "h3" and F2.background_dst == "h6"
    assert F2.target_src == "h1" and F2.target_dst == "h5"


def test_f3_acl_selector_and_priority() -> None:
    assert F3.switch == "s3"
    assert F3.src_host == "h1" and F3.dst_host == "h5"
    assert F3.priority == EXPERIMENT_PRIORITY == 50000
    assert F3.priority > 41000
    assert F3.app_id == EXPERIMENT_APP_ID == "org.coms6200.experiment"
    assert "fault" not in F3.app_id.lower()
    assert "acl" not in F3.app_id.lower()
    assert "F3" not in F3.app_id


def test_f4_loop_path_and_safety() -> None:
    hops = [(h.switch, h.out_port) for h in F4.hops]
    assert hops == [("s3", 5), ("s4", 1), ("s1", 2)]
    assert F4.safety_iface == "s3-eth5"
    assert F4.src_host == "h1" and F4.dst_host == "h5"
    assert F4.app_id == EXPERIMENT_APP_ID


def test_f5_missing_target() -> None:
    assert F5.switch == "s3"
    assert F5.dst_host == "h5"
    assert F5.priority == 41000
    assert F5.app_id == "org.coms6200.baseline"


def test_require_scenario_rejects_unknown() -> None:
    for bad in ("F6", "F1; rm -rf /", "s3-eth1", "127.0.0.1", "", None, 1, "--cmd"):
        try:
            require_scenario(bad)  # type: ignore[arg-type]
        except ValueError:
            pass
        else:
            raise AssertionError(f"scenario {bad!r} should be rejected")


def test_cli_rejects_extra_flags() -> None:
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    cases = [
        ["-m", "faults.cli", "inject", "--scenario", "F1", "--interface", "s3-eth1"],
        ["-m", "faults.cli", "inject", "--scenario", "F2", "--rate", "10mbit"],
        ["-m", "faults.cli", "inject", "--scenario", "F3", "--cmd", "rm"],
        ["-m", "faults.cli", "inject", "--scenario", "F4", "--pid", "1"],
        ["-m", "faults.cli", "inject", "--scenario", "F5", "--flow-id", "9"],
        ["-m", "faults.cli", "inject", "--scenario", "F9"],
        ["-m", "faults.cli", "inject", "--scenario", "F1;rm"],
    ]
    for args in cases:
        completed = subprocess.run(
            [sys.executable, *args],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode != 0, args


def test_no_shell_true_or_eval() -> None:
    faults_dir = ROOT / "faults"
    for path in faults_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        # Avoid matching docstring mentions of the forbidden pattern.
        compact = text.replace(" ", "").replace("\n", "")
        assert "shell=True" not in compact or "shell=False" in compact
        # Stronger: AST check — no Call with shell=True keyword.
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg == "shell" and isinstance(kw.value, ast.Constant):
                        assert kw.value.value is not True, path.name
                if isinstance(node.func, ast.Name):
                    assert node.func.id != "eval"


def test_telemetry_isolation() -> None:
    names = set(TOOL_SCHEMAS)
    assert "inject" not in names
    blob = json.dumps(TOOL_SCHEMAS).lower()
    for token in ("fault_id", "ground_truth", "scenario_id", "expected_correction", "injected_by"):
        assert token not in blob
    tele = ROOT / "telemetry"
    for path in tele.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "import faults" not in text
        assert "from faults" not in text
        assert "fault-state" not in text
        assert "ground_truth" not in text


def test_state_permissions() -> None:
    with tempfile.TemporaryDirectory() as raw:
        directory = pathlib.Path(raw)
        with mock.patch.object(fault_state, "STATE_DIR", directory):
            with mock.patch.object(fault_state, "STATE_PATH", directory / "fault-state.json"):
                path = fault_state.write_state({"status": "ACTIVE", "scenario_id": "F2"})
                assert stat.S_IMODE(path.stat().st_mode) == 0o600
                assert stat.S_IMODE(directory.stat().st_mode) == 0o700


def test_duplicate_injection_rejected() -> None:
    with tempfile.TemporaryDirectory() as raw:
        directory = pathlib.Path(raw)
        with mock.patch.object(fault_state, "STATE_DIR", directory):
            with mock.patch.object(fault_state, "STATE_PATH", directory / "fault-state.json"):
                fault_state.write_state({"status": "ACTIVE", "scenario_id": "F1"})
                result = inj.inject("F2")
                assert result["ok"] is False
                assert result["error"]["code"] == "FAULT_ALREADY_ACTIVE"


def test_root_guard_f1() -> None:
    with mock.patch.object(os, "geteuid", return_value=1000):
        result = inj.inject("F1")
    assert result["ok"] is False
    assert result["error"]["code"] == "ROOT_REQUIRED"


def test_envelope() -> None:
    good = envelope.ok("status", {"active": False})
    assert good["ok"] is True
    bad = envelope.error("inject", "INVALID_SCENARIO", "nope")
    assert bad["ok"] is False


def test_f2_fixed_tc_argv_mocked() -> None:
    from faults import f2_congestion as f2

    with tempfile.TemporaryDirectory() as raw:
        directory = pathlib.Path(raw)
        with mock.patch.object(fault_state, "STATE_DIR", directory):
            with mock.patch.object(fault_state, "STATE_PATH", directory / "fault-state.json"):
                with mock.patch.object(f2, "require_root"):
                    with mock.patch.object(
                        f2,
                        "validate_iface_bridge",
                        return_value={"interface": "s1-eth4", "bridge": "s1", "operstate": "up"},
                    ):
                        with mock.patch.object(f2, "find_host_pid"):
                            with mock.patch.object(f2, "tc_replace_tbf") as tc:
                                with mock.patch.object(f2, "tc_show", return_value="qdisc tbf"):
                                    server = mock.Mock()
                                    server.pid = 101
                                    server.poll.return_value = None
                                    client = mock.Mock()
                                    client.pid = 102
                                    client.poll.return_value = None
                                    started: list[list[str]] = []

                                    def _start(_host, argv):
                                        started.append(list(argv))
                                        return server if len(started) == 1 else client

                                    with mock.patch.object(f2, "start_in_host", side_effect=_start):
                                        result = f2.inject_f2()
                assert result["status"] == "ACTIVE"
                tc.assert_called_once_with("s1-eth4", "1mbit", "32kbit", "400ms")
                assert started[0] == ["iperf3", "-s", "-p", "5202"]
                assert started[1] == ["iperf3", "-c", "10.0.0.6", "-t", "0", "-p", "5202"]
                assert "120" not in started[0] + started[1]
                assert F2.background_duration_s == 0
                assert "F2" not in " ".join(started[0] + started[1])



def test_f2_reset_stops_background_and_tbf() -> None:
    from faults import f2_congestion as f2

    with mock.patch.object(f2, "require_root"):
        with mock.patch.object(
            f2,
            "validate_iface_bridge",
            return_value={"interface": "s1-eth4", "bridge": "s1", "operstate": "up"},
        ):
            with mock.patch.object(f2, "_kill_tracked") as kill:
                with mock.patch.object(f2, "_stop_host_iperf") as stop:
                    with mock.patch.object(f2, "tc_del_root") as tc:
                        with mock.patch.object(f2, "tc_show", return_value="qdisc pfifo_fast"):
                            with mock.patch.object(f2, "clear_state") as clear:
                                result = f2.reset_f2(force=True, payload={"pids": [11, 12]})
    assert result["status"] == "IDLE"
    kill.assert_called_once_with([11, 12])
    assert [call.args[0] for call in stop.call_args_list] == ["h3", "h6"]
    tc.assert_called_once_with("s1-eth4")
    clear.assert_called_once()
    assert "tbf" not in result["tc_show"]


def test_f3_drop_treatment_mocked() -> None:
    from faults import f3_acl as f3
    from faults import onos_experiment as ox

    with tempfile.TemporaryDirectory() as raw:
        directory = pathlib.Path(raw)
        with mock.patch.object(fault_state, "STATE_DIR", directory):
            with mock.patch.object(fault_state, "STATE_PATH", directory / "fault-state.json"):
                with mock.patch.object(f3, "require_root"):
                    with mock.patch.object(f3, "list_experiment_flows", return_value=[]):
                        with mock.patch.object(
                            f3,
                            "install_experiment_flows",
                            return_value=[{"deviceId": "of:3", "id": "9"}],
                        ) as inst:
                            result = f3.inject_f3()
                assert result["status"] == "ACTIVE"
                flow = inst.call_args[0][0][0]
                assert flow["treatment"]["instructions"] == []
                assert flow["appId"] == EXPERIMENT_APP_ID
                assert flow["priority"] == EXPERIMENT_PRIORITY


def test_f4_requires_safety_qdisc_mocked() -> None:
    from faults import f4_loop as f4

    with tempfile.TemporaryDirectory() as raw:
        directory = pathlib.Path(raw)
        with mock.patch.object(fault_state, "STATE_DIR", directory):
            with mock.patch.object(fault_state, "STATE_PATH", directory / "fault-state.json"):
                with mock.patch.object(f4, "require_root"):
                    with mock.patch.object(f4, "list_experiment_flows", return_value=[]):
                        with mock.patch.object(
                            f4,
                            "validate_iface_bridge",
                            return_value={"operstate": "up", "bridge": "s3", "interface": "s3-eth5"},
                        ):
                            with mock.patch.object(f4, "tc_replace_tbf") as tc:
                                with mock.patch.object(f4, "tc_show", return_value="qdisc tbf"):
                                    with mock.patch.object(
                                        f4,
                                        "install_experiment_flows",
                                        return_value=[
                                            {"deviceId": "a", "id": "1"},
                                            {"deviceId": "b", "id": "2"},
                                            {"deviceId": "c", "id": "3"},
                                        ],
                                    ) as inst:
                                        result = f4.inject_f4()
                assert result["status"] == "ACTIVE"
                assert result["flow_count"] == 3
                tc.assert_called_once()
                flows = inst.call_args[0][0]
                assert all(f["treatment"]["instructions"] for f in flows)
                assert all(
                    c["type"] in ("ETH_SRC", "ETH_DST")
                    for f in flows
                    for c in f["selector"]["criteria"]
                )


def test_f5_ambiguous_rejected() -> None:
    from faults import f5_missing as f5

    with mock.patch.object(f5, "list_baseline_flows", return_value=[{}, {}]):
        with mock.patch.object(f5, "flow_matches_spec", return_value=True):
            try:
                f5.resolve_unique_baseline_flow(client=mock.Mock())
            except Exception as exc:  # noqa: BLE001
                assert getattr(exc, "code", "") == "FLOW_AMBIGUOUS"
            else:
                raise AssertionError("ambiguous match should fail")


def test_fixed_argv_no_user_iface() -> None:
    for name in ("injector.py", "common.py", "f2_congestion.py", "cli.py"):
        source = (ROOT / "faults" / name).read_text(encoding="utf-8")
        assert "user_iface" not in source
    assert "--interface" not in (ROOT / "faults" / "cli.py").read_text(encoding="utf-8")
    assert "--rate" not in (ROOT / "faults" / "cli.py").read_text(encoding="utf-8")


def main() -> int:
    checks = (
        test_catalogue_version_and_runnable,
        test_f1_unchanged_mapping,
        test_f2_canonical_link_and_fixed_rates,
        test_f3_acl_selector_and_priority,
        test_f4_loop_path_and_safety,
        test_f5_missing_target,
        test_require_scenario_rejects_unknown,
        test_cli_rejects_extra_flags,
        test_no_shell_true_or_eval,
        test_telemetry_isolation,
        test_state_permissions,
        test_duplicate_injection_rejected,
        test_root_guard_f1,
        test_envelope,
        test_f2_fixed_tc_argv_mocked,
        test_f2_reset_stops_background_and_tbf,
        test_f3_drop_treatment_mocked,
        test_f4_requires_safety_qdisc_mocked,
        test_f5_ambiguous_rejected,
        test_fixed_argv_no_user_iface,
    )
    failed = 0
    for check in checks:
        try:
            check()
            print(f"PASS {check.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {check.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {check.__name__}: {type(exc).__name__}: {exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
