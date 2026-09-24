"""Operator catalogue helpers keep scenario ids and ground truth off the model path."""
import os

import pytest

from agent import fault_control

CATALOGUE = ("F1", "F2", "F3", "F4", "F5")


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


def test_every_catalogue_scenario_is_runnable():
    assert fault_control.RUNNABLE == frozenset(CATALOGUE)


@pytest.mark.parametrize("scenario", CATALOGUE)
def test_load_and_reset_each_scenario(monkeypatch, scenario):
    calls = []
    state = {}
    monkeypatch.setattr(os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(
        fault_control, "reset", lambda: calls.append("reset") or state.clear() or {"ok": True}
    )

    def inject(sid):
        calls.append(sid)
        state.update(scenario_id=sid, ground_truth={"hidden": True})
        return {"ok": True, "data": {"scenario_id": sid}}

    monkeypatch.setattr(fault_control, "inject", inject)
    monkeypatch.setattr(
        fault_control,
        "status",
        lambda: {"ok": True, "data": {"active": bool(state), "state": dict(state)}},
    )
    loaded = fault_control.load_scenario(scenario)
    assert calls == ["reset", scenario]
    assert loaded["ok"] is True and loaded["active"] is True
    assert loaded["scenario_id"] == scenario
    assert "ground_truth" not in loaded
    reset = fault_control.reset_scenario()
    assert reset["ok"] is True and reset["active"] is False
    assert reset["scenario_id"] is None


@pytest.mark.parametrize("scenario", CATALOGUE)
def test_failed_inject_reports_error_for_each_scenario(monkeypatch, scenario):
    monkeypatch.setattr(os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(fault_control, "reset", lambda: {"ok": True})
    monkeypatch.setattr(
        fault_control,
        "inject",
        lambda sid: {"ok": False, "error": {"code": "X", "message": f"{sid} inject failed"}},
    )
    monkeypatch.setattr(fault_control, "status", lambda: {"ok": True, "data": {"active": False}})
    result = fault_control.load_scenario(scenario)
    assert result["ok"] is False
    assert result["error"] == f"{scenario} inject failed"
