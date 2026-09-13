"""Operator catalogue helpers keep scenario ids and ground truth off the model path."""
import os

from agent import fault_control


def test_public_status_strips_ground_truth(monkeypatch):
    monkeypatch.setattr(
        fault_control,
        "status",
        lambda: {
            "ok": True,
            "data": {
                "active": True,
                "state": {
                    "scenario_id": "F1",
                    "ground_truth": {"hidden": True},
                    "expected_correction": "nope",
                },
            },
        },
    )
    result = fault_control.public_status()
    assert result["ok"] is True
    assert result["active"] is True
    assert result["scenario_id"] == "F1"
    assert result["runnable"] == sorted(fault_control.RUNNABLE)
    assert "ground_truth" not in result
    assert "expected_correction" not in result
    assert set(result) == {"ok", "active", "scenario_id", "runnable", "error"}


def test_load_requires_root(monkeypatch):
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    result = fault_control.load_scenario("F1")
    assert result["ok"] is False
    assert "root" in result["error"].lower()


def test_load_resets_then_injects(monkeypatch):
    calls = []
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(fault_control, "reset", lambda: calls.append("reset") or {"ok": True})
    monkeypatch.setattr(
        fault_control, "inject", lambda sid: calls.append(sid) or {"ok": True, "data": {}}
    )
    monkeypatch.setattr(
        fault_control,
        "status",
        lambda: {"ok": True, "data": {"active": True, "state": {"scenario_id": "F2"}}},
    )
    result = fault_control.load_scenario("F2")
    assert calls == ["reset", "F2"]
    assert result["ok"] is True
    assert result["scenario_id"] == "F2"
