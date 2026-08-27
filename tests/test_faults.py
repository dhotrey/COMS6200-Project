"""Static checks for M5 F1 fault injector.

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
from faults.scenarios import F1, RUNNABLE, SCENARIOS, require_scenario  # noqa: E402
from faults import state as fault_state  # noqa: E402
from telemetry.schemas import TOOL_SCHEMAS  # noqa: E402


def test_f1_canonical_mapping() -> None:
    assert F1.scenario_id == "F1"
    assert F1.fault_family == "link_failure"
    ends = F1.endpoints
    names = {ends[0].switch, ends[1].switch}
    assert names == {"s1", "s3"}
    ports = {e.switch: e.port for e in ends}
    assert ports["s3"] == 1
    assert ports["s1"] == 2
    assert set(F1.interfaces) == {"s3-eth1", "s1-eth2"}
    assert "F1" in RUNNABLE
    assert set(SCENARIOS) == {"F1"}


def test_require_scenario_rejects_unknown() -> None:
    for bad in ("F2", "F1; rm -rf /", "s3-eth1", "127.0.0.1", "", None, 1):
        try:
            require_scenario(bad)  # type: ignore[arg-type]
        except ValueError:
            pass
        else:
            raise AssertionError(f"scenario {bad!r} should be rejected")


def test_ground_truth_schema() -> None:
    gt = F1.ground_truth()
    assert gt["scenario_id"] == "F1"
    assert gt["fault_family"] == "link_failure"
    assert set(gt["location"]["link"]) == {"s1", "s3"}
    assert gt["location"]["ports"]["s3"] == 1
    assert gt["location"]["ports"]["s1"] == 2
    assert set(gt["location"]["interfaces"]) == {"s3-eth1", "s1-eth2"}


def test_cli_rejects_extra_flags_and_interfaces() -> None:
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    cases = [
        ["-m", "faults.cli", "inject", "--scenario", "F1", "--interface", "s3-eth1"],
        ["-m", "faults.cli", "inject", "--scenario", "F1", "--cmd", "rm"],
        ["-m", "faults.cli", "inject", "--scenario", "F1", "--link", "s3-s1"],
        ["-m", "faults.cli", "inject", "--scenario", "F1", "--pid", "1"],
        ["-m", "faults.cli", "inject", "--scenario", "F2"],
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
        assert "shell=True" not in text.replace(" ", "")
        assert "shell = True" not in text
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id != "eval"


def test_telemetry_schemas_have_no_fault_tools() -> None:
    names = set(TOOL_SCHEMAS)
    assert "inject" not in names
    assert "fault" not in names
    assert "F1" not in names
    blob = json.dumps(TOOL_SCHEMAS).lower()
    assert "fault_id" not in blob
    assert "ground_truth" not in blob
    assert "scenario_id" not in blob


def test_telemetry_does_not_import_faults() -> None:
    tele = ROOT / "telemetry"
    for path in tele.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "import faults" not in text
        assert "from faults" not in text
        assert "fault-state" not in text
        assert "ground_truth" not in text


def test_state_permissions(tmp_path: pathlib.Path | None = None) -> None:
    with tempfile.TemporaryDirectory() as raw:
        directory = pathlib.Path(raw)
        with mock.patch.object(fault_state, "STATE_DIR", directory):
            with mock.patch.object(fault_state, "STATE_PATH", directory / "fault-state.json"):
                path = fault_state.write_state({"status": "ACTIVE", "scenario_id": "F1"})
                mode = stat.S_IMODE(path.stat().st_mode)
                assert mode == 0o600
                dir_mode = stat.S_IMODE(directory.stat().st_mode)
                assert dir_mode == 0o700
                loaded = fault_state.read_state()
                assert loaded is not None
                assert loaded["scenario_id"] == "F1"
                fault_state.clear_state()
                assert fault_state.read_state() is None


def test_duplicate_injection_rejected() -> None:
    with tempfile.TemporaryDirectory() as raw:
        directory = pathlib.Path(raw)
        with mock.patch.object(fault_state, "STATE_DIR", directory):
            with mock.patch.object(fault_state, "STATE_PATH", directory / "fault-state.json"):
                fault_state.write_state({"status": "ACTIVE", "scenario_id": "F1"})
                with mock.patch.object(inj, "require_root"):
                    result = inj.inject("F1")
                assert result["ok"] is False
                assert result["error"]["code"] == "FAULT_ALREADY_ACTIVE"


def test_root_guard() -> None:
    with mock.patch.object(os, "geteuid", return_value=1000):
        result = inj.inject("F1")
    assert result["ok"] is False
    assert result["error"]["code"] == "ROOT_REQUIRED"


def test_envelope() -> None:
    good = envelope.ok("status", {"active": False})
    assert good["ok"] is True
    assert good["component"] == "faults"
    bad = envelope.error("inject", "INVALID_SCENARIO", "nope")
    assert bad["ok"] is False
    assert "Traceback" not in json.dumps(bad)


def test_inject_happy_path_mocked() -> None:
    with tempfile.TemporaryDirectory() as raw:
        directory = pathlib.Path(raw)
        with mock.patch.object(fault_state, "STATE_DIR", directory):
            with mock.patch.object(fault_state, "STATE_PATH", directory / "fault-state.json"):
                with mock.patch.object(inj, "require_root"):
                    with mock.patch.object(
                        inj,
                        "validate_endpoints",
                        side_effect=[
                            [
                                {"switch": "s1", "port": 2, "interface": "s1-eth2", "bridge": "s1", "operstate": "up"},
                                {"switch": "s3", "port": 1, "interface": "s3-eth1", "bridge": "s3", "operstate": "up"},
                            ],
                            [
                                {"switch": "s1", "port": 2, "interface": "s1-eth2", "bridge": "s1", "operstate": "down"},
                                {"switch": "s3", "port": 1, "interface": "s3-eth1", "bridge": "s3", "operstate": "down"},
                            ],
                        ],
                    ):
                        with mock.patch.object(inj, "_set_link") as set_link:
                            result = inj.inject("F1")
                assert result["ok"] is True
                assert result["data"]["status"] == "ACTIVE"
                assert set(result["data"]["interfaces"]) == {"s1-eth2", "s3-eth1"}
                assert set_link.call_count == 2
                assert fault_state.active_state() is not None


def test_reset_clears_state_mocked() -> None:
    with tempfile.TemporaryDirectory() as raw:
        directory = pathlib.Path(raw)
        with mock.patch.object(fault_state, "STATE_DIR", directory):
            with mock.patch.object(fault_state, "STATE_PATH", directory / "fault-state.json"):
                fault_state.write_state(
                    {
                        "status": "ACTIVE",
                        "scenario_id": "F1",
                        "interfaces": ["s1-eth2", "s3-eth1"],
                    }
                )
                with mock.patch.object(inj, "require_root"):
                    with mock.patch.object(
                        inj,
                        "validate_endpoints",
                        side_effect=[
                            [
                                {"switch": "s1", "port": 2, "interface": "s1-eth2", "bridge": "s1", "operstate": "down"},
                                {"switch": "s3", "port": 1, "interface": "s3-eth1", "bridge": "s3", "operstate": "down"},
                            ],
                            [
                                {"switch": "s1", "port": 2, "interface": "s1-eth2", "bridge": "s1", "operstate": "up"},
                                {"switch": "s3", "port": 1, "interface": "s3-eth1", "bridge": "s3", "operstate": "up"},
                            ],
                        ],
                    ):
                        with mock.patch.object(inj, "_set_link") as set_link:
                            result = inj.reset()
                assert result["ok"] is True
                assert result["data"]["status"] == "IDLE"
                assert set_link.call_count == 2
                assert fault_state.read_state() is None


def test_fixed_argv_no_user_iface() -> None:
    source = (ROOT / "faults" / "injector.py").read_text(encoding="utf-8")
    assert "shell=True" not in source
    assert "user_iface" not in source
    assert "--interface" not in (ROOT / "faults" / "cli.py").read_text(encoding="utf-8")


def main() -> int:
    checks = (
        test_f1_canonical_mapping,
        test_require_scenario_rejects_unknown,
        test_ground_truth_schema,
        test_cli_rejects_extra_flags_and_interfaces,
        test_no_shell_true_or_eval,
        test_telemetry_schemas_have_no_fault_tools,
        test_telemetry_does_not_import_faults,
        test_state_permissions,
        test_duplicate_injection_rejected,
        test_root_guard,
        test_envelope,
        test_inject_happy_path_mocked,
        test_reset_clears_state_mocked,
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
