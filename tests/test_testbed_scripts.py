"""Static checks for the session testbed helper.

Does not start Mininet, ONOS, or inject faults.
"""

from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "testbed.sh"
RUNNER = ROOT / "scripts" / "run_main6s8h.py"
AGENT_VERIFIER = ROOT / "scripts" / "verify_agent_scenarios.sh"
SETUP_ONOS = ROOT / "setup" / "setup_onos.sh"


def _between(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


def test_helper_files_exist() -> None:
    assert SCRIPT.is_file()
    assert RUNNER.is_file()
    text = SCRIPT.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash")
    assert RUNNER.read_text(encoding="utf-8").startswith("#!/usr/bin/env python3")


def test_testbed_commands_and_catalogue() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    for command in ("start)", "stop)", "inject)", "reset)", "status)"):
        assert command in text, f"missing command {command}"
    for scenario in ("F1", "F2", "F3", "F4", "F5"):
        assert scenario in text
    assert "F6" not in text.split("Catalogue v1 has no F6+", 1)[0]
    assert "python3 -m faults.cli inject" in text
    assert "baseline_forwarding.py" in text
    assert "run_main6s8h.py" in text
    assert "setup_onos.sh" in text
    assert "org.onosproject.fwd" not in text


def test_stop_recovery_covers_every_scenario() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    body = text.split("reset_fault_best_effort() {", 1)[1].split("\n}\n", 1)[0]
    assert "for scenario in F1 F2 F3 F4 F5" in body
    assert '--force-scenario "${scenario}"' in body
    assert "--force-scenario F1" not in text


def test_stop_resets_faults_before_datapath() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    body = _between(text, "cmd_stop() {", "\ncmd_inject()")
    assert body.index("reset_fault_best_effort") < body.index("stop_mininet")
    recovery = text.split("reset_fault_best_effort() {", 1)[1].split("\n}\n", 1)[0]
    assert "faults.cli reset" in recovery
    assert "--force-scenario" in recovery
    for scenario in ("F1", "F2", "F3", "F4", "F5"):
        assert scenario in recovery


def test_normal_stop_leaves_onos_running() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    body = _between(text, "cmd_stop() {", "\ncmd_inject()")
    assert 'if [[ "${with_onos}" -eq 1 ]]' in body
    assert 'stop "${ONOS_CONTAINER}"' in body
    assert "Leaving ONOS container" in body
    before_flag, _, _after = body.partition('if [[ "${with_onos}" -eq 1 ]]')
    assert "ONOS_CONTAINER" not in before_flag
    assert "docker system prune" not in text
    assert "docker rm -f $" not in text
    assert 'rm -f "${ONOS_CONTAINER}"' in text


def test_explicit_full_stop_and_argument_validation() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    main = _between(text, "main() {", "\nmain \"$@\"")
    assert "--with-onos" in main
    assert "unknown argument" in main
    assert "reject_extra" in main
    assert "unexpected argument" in text
    assert "cmd_stop \"${with_onos}\"" in main


def test_start_reuses_creates_or_starts_onos() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    body = _between(text, "ensure_onos_container() {", "\nwait_onos_service()")
    assert "already running; reusing it" in body
    assert "./setup/setup_onos.sh" in body
    assert 'start "${ONOS_CONTAINER}"' in body
    assert "restart" not in body


def test_integration_recovery_is_one_shot() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    body = _between(text, "recover_onos_once() {", "\nmininet_started_by_us()")
    assert body.count("recreate_onos_container") == 1
    assert body.count("ONOS_RECOVERY_USED=1") == 1
    assert "after one container recreation" in body
    assert "while true" not in body
    start = _between(text, "cmd_start() {", "\ncmd_stop()")
    assert start.count("recover_onos_once") == 1
    assert "6 OF_13" in text
    assert "20 directed links" in text


def test_onos_log_reads_are_bounded() -> None:
    for path in (SCRIPT, SETUP_ONOS):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("echo") or "Inspect:" in line:
                continue
            if "logs" not in stripped:
                continue
            if "DOCKER" not in stripped and "docker" not in stripped:
                continue
            assert "--tail" in stripped or "--since" in stripped, f"{path.name}: {stripped}"


def test_agent_verifier_uses_harness_path_for_every_scenario() -> None:
    text = AGENT_VERIFIER.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash")
    assert "SCENARIOS=(F1 F2 F3 F4 F5)" in text
    for scenario in ("F1", "F2", "F3", "F4", "F5"):
        assert f'sid == "{scenario}"' in text, f"no {scenario} observation branch"
    assert "fault_control.load_scenario" in text
    assert "fault_control.reset_scenario" in text
    assert "from agent.tools import execute_tool" in text
    assert "TOOL_DELAY_MIN_SECONDS=0 TOOL_DELAY_MAX_SECONDS=0" in text
    for forbidden in ("agent.loop", "agent.config", "make_client", "/responses"):
        assert forbidden not in text
    blocks = text.split("python3 - <<'PY'\n")[1:]
    assert len(blocks) == 4
    for block in blocks:
        compile(block.split("\nPY\n", 1)[0], str(AGENT_VERIFIER), "exec")


def test_runner_uses_main_topology_and_remote_onos() -> None:
    tree = ast.parse(RUNNER.read_text(encoding="utf-8"), filename=str(RUNNER))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module)
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
    assert "topologies.main_topology" in imported
    assert "MainProjectTopology" in imported
    source = RUNNER.read_text(encoding="utf-8")
    assert "RemoteController" in source
    assert "OVSKernelSwitch" in source
    assert "waitConnected=False" in source
    assert "mininet:<host>" in source


def main() -> int:
    test_helper_files_exist()
    test_testbed_commands_and_catalogue()
    test_stop_recovery_covers_every_scenario()
    test_stop_resets_faults_before_datapath()
    test_normal_stop_leaves_onos_running()
    test_explicit_full_stop_and_argument_validation()
    test_start_reuses_creates_or_starts_onos()
    test_integration_recovery_is_one_shot()
    test_onos_log_reads_are_bounded()
    test_agent_verifier_uses_harness_path_for_every_scenario()
    test_runner_uses_main_topology_and_remote_onos()
    print("test_testbed_scripts: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
