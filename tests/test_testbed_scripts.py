"""Static checks for the session testbed helper.

Does not start Mininet, ONOS, or inject faults.
"""

from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "testbed.sh"
RUNNER = ROOT / "scripts" / "run_main6s8h.py"


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
    test_runner_uses_main_topology_and_remote_onos()
    print("test_testbed_scripts: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
