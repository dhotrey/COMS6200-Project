"""Offline topology switching and telemetry agreement; no live testbed commands."""

import json
import os
import subprocess
from types import SimpleNamespace

import pytest

from agent import fault_control, tools, topology_control
from topologies import active
from telemetry.gateway import TelemetryGateway
from telemetry.link_metrics import require_switch_port
from telemetry.parsers import normalize_ports
from telemetry.schemas import validate_arguments
from telemetry.validate import ValidationError, host_attachments


@pytest.fixture(autouse=True)
def selection(monkeypatch):
    previous = active.TOPOLOGY
    active.select("main6s8h")
    tools.refresh_tools()
    monkeypatch.setattr(topology_control, "error", None)
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(topology_control, "running_topology", lambda: "main6s8h")
    yield
    active.select(previous)
    tools.refresh_tools()


@pytest.mark.parametrize("target", ["ring5s5h", "tree5s8h"])
def test_switch_clears_old_rules_before_stopping_and_starting(monkeypatch, target):
    calls = []
    monkeypatch.setattr(topology_control, "run_command", lambda argv, topology:
        calls.append((argv, topology)))
    topology_control.load_topology(target)
    assert [argv[-1] for argv, topology in calls] == ["reset", "remove", "stop", "start"]
    assert [topology for argv, topology in calls] == ["main6s8h"] * 3 + [target]
    assert active.TOPOLOGY == target


def test_same_running_topology_is_not_restarted(monkeypatch):
    monkeypatch.setattr(topology_control, "run_command", lambda *args:
        pytest.fail("Restarted an already-running topology"))
    topology_control.load_topology("main6s8h")


def test_failed_switch_is_not_reported_as_loaded(monkeypatch):
    def command(argv, topology):
        if argv[-1] == "start":
            raise RuntimeError("setup failed")
    monkeypatch.setattr(topology_control, "run_command", command)
    monkeypatch.setattr(topology_control, "restore_selection", lambda: None)
    with pytest.raises(RuntimeError, match="setup failed"):
        topology_control.load_topology("ring5s5h")
    assert active.TOPOLOGY == "main6s8h"
    assert topology_control.error == "setup failed"


def test_invalid_or_unprivileged_switch_never_runs_commands(monkeypatch):
    monkeypatch.setattr(topology_control, "run_command", lambda *args: pytest.fail("Ran setup"))
    with pytest.raises(ValueError):
        topology_control.load_topology("ring; echo bad")
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    with pytest.raises(RuntimeError, match="root"):
        topology_control.load_topology("ring5s5h")


def test_failed_reset_names_cleanup_and_missing_command(monkeypatch, caplog):
    monkeypatch.setattr(topology_control.subprocess, "run", lambda *args, **kwargs:
        SimpleNamespace(returncode=1, stderr="", stdout=json.dumps({
            "ok": False, "error": {"code": "COMMAND_UNAVAILABLE",
                                    "message": "tc is not available on PATH"},
        })))
    with pytest.raises(RuntimeError, match="tree5s8h fault reset.*tc is not available"):
        topology_control.run_command(["python", "-m", "faults.cli", "reset"], "tree5s8h")
    assert "fault reset failed" in caplog.text


def test_setup_reason_and_log_redact_environment_secrets(monkeypatch, caplog):
    monkeypatch.setenv("ONOS_PASSWORD", "test-private-password")
    monkeypatch.setattr(topology_control.subprocess, "run", lambda *args, **kwargs:
        SimpleNamespace(returncode=1, stdout="", stderr=
                        "RuntimeError: ONOS rejected test-private-password"))
    with pytest.raises(RuntimeError, match="ring5s5h baseline removal") as failed:
        topology_control.run_command(["python", "forwarding/baseline_forwarding.py", "remove"], "ring5s5h")
    assert "test-private-password" not in str(failed.value) + caplog.text
    assert "[redacted]" in str(failed.value)


def test_selection_restored_after_server_restart(monkeypatch, tmp_path):
    marker = tmp_path / "mininet.ready"
    marker.write_text("tree5s8h\n")
    monkeypatch.setattr(topology_control, "ready_file", lambda: marker)
    monkeypatch.setattr(topology_control, "running_topology", lambda: None)
    topology_control.restore_selection()
    assert active.TOPOLOGY == "tree5s8h"


def test_fault_cli_uses_current_topology_and_strips_ground_truth(monkeypatch):
    active.select("ring5s5h")
    seen = []
    def command(argv, **kwargs):
        seen.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            "ok": True, "data": {"active": True, "state": {
                "scenario_id": "F3", "ground_truth": {"hidden": True},
            }},
        }))
    monkeypatch.setattr(fault_control.subprocess, "run", command)
    result = fault_control.public_status()
    assert result["topology"] == "ring5s5h"
    assert result["scenario_id"] == "F3"
    assert "ground_truth" not in json.dumps(result)
    assert seen[0][1]["env"]["COMS6200_TOPOLOGY"] == "ring5s5h"
    assert seen[0][0][-1] == "status"


def test_telemetry_and_model_allowlists_follow_switches():
    queried = []
    client = SimpleNamespace(
        device_ports=lambda dpid: queried.append(dpid) or [],
        devices=lambda: [], links=lambda: [],
    )
    gateway = TelemetryGateway(client=client)
    for topology, switch_count, host_count in (
        ("main6s8h", 6, 8), ("ring5s5h", 5, 5), ("tree5s8h", 7, 8), ("main6s8h", 6, 8),
    ):
        active.select(topology)
        tools.refresh_tools()
        result = gateway.get_topology()
        assert result["ok"]
        assert result["data"]["summary"]["switches"] == switch_count
        assert result["data"]["summary"]["logical_hosts"] == host_count
        assert result["data"]["host_attachments"] == host_attachments()
        assert gateway.get_port_status("s1")["ok"]
        assert queried[-1] == active.DEVICE_IDS["s1"]
        sw_schema = next(t for t in tools.TOOLS if t["name"] == "get_port_status")
        assert sw_schema["parameters"]["properties"]["sw"]["enum"] == list(active.SWITCHES)
        if topology == "tree5s8h":
            validate_arguments("get_link_metrics", {"sw": "s7", "port": 2})
            assert require_switch_port("s7", 2) == ("s7", 2)
            assert normalize_ports("s7", [{"port": "2"}])[0]["peer"]["id"] == "h7"
        else:
            with pytest.raises(ValidationError):
                validate_arguments("get_port_status", {"sw": "s7"})
        if topology == "ring5s5h":
            with pytest.raises(ValidationError):
                validate_arguments("ping", {"src": "h1", "dst": "h8"})
