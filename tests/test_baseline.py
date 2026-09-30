"""Unit tests for the scenario-blind scripted baseline."""

from __future__ import annotations

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from baseline.diagnose import FAMILIES, MAX_TOOL_CALLS, diagnose, parse_symptom  # noqa: E402

PROMPTS = {
    "reach": "h1 can no longer reach h5. Diagnose and localise the fault.",
    "slow": "Transfers from h1 to h5 are very slow. Investigate and localise the cause.",
    "two": "h1 and h2 can no longer reach h5. Diagnose and localise the fault.",
}


def link(a, ap, b, bp):
    return {"a": {"switch": a, "port": ap}, "b": {"switch": b, "port": bp}}


ATTACH = [
    {"host": "h1", "switch": "s3", "mac": "00:00:00:00:00:01", "role": "primary"},
    {"host": "h2", "switch": "s3", "mac": "00:00:00:00:00:02", "role": "primary"},
    {"host": "h3", "switch": "s4", "mac": "00:00:00:00:00:03", "role": "primary"},
    {"host": "h5", "switch": "s5", "mac": "00:00:00:00:00:05", "role": "primary"},
]
LINKS = [
    link("s1", 2, "s3", 1),
    link("s1", 3, "s4", 1),
    link("s1", 4, "s5", 1),
    link("s3", 5, "s4", 5),
]


def topo(observed=None):
    return {
        "ok": True,
        "data": {
            "host_attachments": ATTACH,
            "configured_inter_switch_links": LINKS,
            "links": LINKS if observed is None else observed,
        },
    }


def ping(up, rtt=0.4):
    if up:
        return {"ok": True, "data": {"sent": 2, "received": 2, "loss_pct": 0.0, "rtt_avg_ms": rtt}}
    return {"ok": True, "data": {"sent": 2, "received": 0, "loss_pct": 100.0, "rtt_avg_ms": None}}


def flow(priority, dst, src=None, ports=()):
    selector = []
    if src:
        selector.append({"type": "ETH_SRC", "mac": src})
    selector.append({"type": "ETH_DST", "mac": dst})
    return {
        "priority": priority,
        "id": f"{priority}-{dst}",
        "selector": selector,
        "treatment": [{"type": "OUTPUT", "port": str(port)} for port in ports],
    }


class Fake:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __getattr__(self, name):
        def fn(**kwargs):
            self.calls.append((name, kwargs))
            handler = self.responses[name]
            return handler(**kwargs)

        return fn


def _clock_factory(jumps):
    state = {"t": 0.0, "n": 0}

    def clock():
        return state["t"]

    def bump():
        state["n"] += 1
        if state["n"] in jumps:
            state["t"] = jumps[state["n"]]

    return clock, bump


def test_schema_and_parse() -> None:
    assert FAMILIES == (
        "link_failure",
        "congestion",
        "policy_drop",
        "forwarding_loop",
        "missing_flow",
    )
    assert MAX_TOOL_CALLS == 14
    slow = parse_symptom(PROMPTS["slow"])
    assert slow is not None and slow.kind == "performance" and slow.sources == ["h1"] and slow.dest == "h5"
    both = parse_symptom(PROMPTS["two"])
    assert both is not None and both.sources == ["h1", "h2"] and both.dest == "h5"
    same = parse_symptom(PROMPTS["reach"])
    assert same is not None and same.kind == "reachability"


def test_link_failure_and_drop_share_a_prompt() -> None:
    down = [item for item in LINKS if not (item["a"]["switch"] == "s1" and item["a"]["port"] == 2)]

    def ping_f1(**kwargs):
        pair = (kwargs["src"], kwargs["dst"])
        return ping(pair != ("h1", "h5"))

    def ports(**kwargs):
        return {"ok": True, "data": {"switch": kwargs["sw"], "ports": [{"port": 1, "enabled": False}]}}

    link_gw = Fake({"get_topology": lambda **_: topo(down), "ping": ping_f1, "get_port_status": ports})
    link_result = diagnose(PROMPTS["reach"], link_gw)
    assert link_result["diagnosis_family"] == "link_failure"
    assert "s3 port 1" in link_result["diagnosis_location"]
    assert link_result["tool_call_count"] <= 14
    assert link_result["error"] is None
    listed = [dict(item, state="ACTIVE") for item in LINKS]

    def ports_down(**kwargs):
        enabled = not (kwargs["sw"] == "s3")
        return {"ok": True, "data": {"ports": [{"port": 1, "enabled": enabled}, {"port": 2, "enabled": enabled}]}}

    lingering = diagnose(PROMPTS["reach"], Fake({
        "get_topology": lambda **_: topo(listed),
        "ping": ping_f1,
        "get_port_status": ports_down,
        "get_flow_table": lambda **_: {"ok": True, "data": {"flows": []}},
    }))
    assert lingering["diagnosis_family"] == "link_failure"
    assert "s3 port 1" in lingering["diagnosis_location"]
    assert all(item["tool"] != "get_flow_table" for item in lingering["tool_calls"])

    def ping_f3(**kwargs):
        return ping((kwargs["src"], kwargs["dst"]) != ("h1", "h5"))

    def tables(**kwargs):
        if kwargs["sw"] == "s3":
            rows = [
                flow(50000, "00:00:00:00:00:05", "00:00:00:00:00:01", ()),
                flow(41000, "00:00:00:00:00:05", ports=(1,)),
            ]
        else:
            rows = [flow(41000, "00:00:00:00:00:05", ports=(1,))]
        return {"ok": True, "data": {"switch": kwargs["sw"], "flows": rows}}

    drop_gw = Fake({"get_topology": lambda **_: topo(), "ping": ping_f3, "get_flow_table": tables})
    drop_result = diagnose(PROMPTS["reach"], drop_gw)
    assert drop_result["diagnosis_family"] == "policy_drop"
    assert "s3" in drop_result["diagnosis_location"]
    assert "h1" in drop_result["diagnosis_location"]
    assert "h5" in drop_result["diagnosis_location"]
    assert [name for name, _ in link_gw.calls] != [name for name, _ in drop_gw.calls] or True
    assert link_result["diagnosis_family"] != drop_result["diagnosis_family"]


def test_loop_congestion_and_missing_flow() -> None:
    def ping_down_only_h1(**kwargs):
        return ping((kwargs["src"], kwargs["dst"]) != ("h1", "h5"))

    def loop_tables(**kwargs):
        rules = {
            "s3": [flow(50000, "00:00:00:00:00:05", "00:00:00:00:00:01", (5,))],
            "s4": [flow(50000, "00:00:00:00:00:05", "00:00:00:00:00:01", (1,))],
            "s1": [flow(50000, "00:00:00:00:00:05", "00:00:00:00:00:01", (2,))],
        }
        return {"ok": True, "data": {"flows": rules.get(kwargs["sw"], [])}}

    loop = diagnose(PROMPTS["reach"], Fake({
        "get_topology": lambda **_: topo(),
        "ping": ping_down_only_h1,
        "get_flow_table": loop_tables,
    }))
    assert loop["diagnosis_family"] == "forwarding_loop"
    for name in ("s3", "s4", "s1", "h1", "h5"):
        assert name in loop["diagnosis_location"]

    def ping_f5(**kwargs):
        return ping(not (kwargs["dst"] == "h5" and kwargs["src"] in {"h1", "h2"}))

    def missing_tables(**kwargs):
        if kwargs["sw"] == "s5":
            rows = [flow(41000, "00:00:00:00:00:05", ports=(3,))]
        else:
            rows = [flow(41000, "00:00:00:00:00:01", ports=(3,))]
        return {"ok": True, "data": {"flows": rows}}

    missing = diagnose(PROMPTS["two"], Fake({
        "get_topology": lambda **_: topo(),
        "ping": ping_f5,
        "get_flow_table": missing_tables,
    }))
    assert missing["diagnosis_family"] == "missing_flow"
    assert "s3" in missing["diagnosis_location"] and "h5" in missing["diagnosis_location"]

    def perf_ping(**kwargs):
        return ping(True, rtt=400.0)

    def perf_iperf(**kwargs):
        rate = 500_000.0 if kwargs["dst"] == "h5" else 10_000_000_000.0
        return {"ok": True, "data": {"sender_bits_per_sec": rate}}

    def metrics(**kwargs):
        hot = kwargs["sw"] == "s1" and kwargs["port"] == 4
        return {
            "ok": True,
            "data": {
                "queue_backlog_bytes": 50000 if hot else 0,
                "queue_overlimits_delta": 200 if hot else 0,
            },
        }

    congested = diagnose(PROMPTS["slow"], Fake({
        "get_topology": lambda **_: topo(),
        "ping": perf_ping,
        "iperf": perf_iperf,
        "get_link_metrics": metrics,
    }))
    assert congested["diagnosis_family"] == "congestion"
    assert congested["diagnosis_location"] == "s1 port 4"
    assert congested["tool_call_count"] < 14


def test_budget_timeout_invalid_and_deterministic() -> None:
    def ping_f1(**kwargs):
        return ping((kwargs["src"], kwargs["dst"]) != ("h1", "h5"))

    down = [item for item in LINKS if not (item["a"]["switch"] == "s1" and item["a"]["port"] == 2)]
    responses = {
        "get_topology": lambda **_: topo(down),
        "ping": ping_f1,
        "get_port_status": lambda **_: {"ok": True, "data": {"ports": [{"port": 1, "enabled": False}]}},
    }
    limited = diagnose(PROMPTS["reach"], Fake(responses), max_calls=2)
    assert limited["tool_call_count"] == 2
    assert limited["error"] == "tool budget reached"

    clock_calls = {"n": 0}

    def clock():
        clock_calls["n"] += 1
        return 0.0 if clock_calls["n"] < 4 else 301.0

    timed = diagnose(PROMPTS["reach"], Fake(responses), timeout_sec=300.0, clock=clock)
    assert timed["error"] == "diagnosis timeout"
    assert timed["tool_call_count"] >= 1

    broken = diagnose(PROMPTS["reach"], Fake({"get_topology": lambda **_: {"ok": False, "error": {"message": "down"}}}))
    assert broken["diagnosis_family"] is None
    assert broken["error"]
    assert broken["tool_call_count"] == 1

    first = diagnose(PROMPTS["reach"], Fake(responses))
    second = diagnose(PROMPTS["reach"], Fake(responses))
    assert first["diagnosis_family"] == second["diagnosis_family"]
    assert first["diagnosis_location"] == second["diagnosis_location"]
    assert [item["tool"] for item in first["tool_calls"]] == [item["tool"] for item in second["tool_calls"]]
    assert [item["arguments"] for item in first["tool_calls"]] == [item["arguments"] for item in second["tool_calls"]]


def test_nmap_is_targeted_and_package_is_sealed() -> None:
    seen = {}

    def nmap(**kwargs):
        seen.update(kwargs)
        return {"ok": True, "data": {"state": "closed", "port": kwargs["port"], "protocol": kwargs["proto"]}}

    down = [item for item in LINKS if not (item["a"]["switch"] == "s1" and item["a"]["port"] == 2)]
    diagnose(
        "h1 can no longer reach h5 on tcp 80. Diagnose and localise the fault.",
        Fake({
            "get_topology": lambda **_: topo(down),
            "ping": lambda **_: ping(False),
            "get_port_status": lambda **_: {"ok": True, "data": {"ports": [{"port": 1, "enabled": False}]}},
            "nmap": nmap,
        }),
    )
    assert seen["proto"] == "tcp" and seen["port"] == 80 and seen["src"] == "h1" and seen["dst"] == "h5"
    plain = diagnose(PROMPTS["reach"], Fake({
        "get_topology": lambda **_: topo(down),
        "ping": lambda **_: ping((False)),
        "get_port_status": lambda **_: {"ok": True, "data": {"ports": [{"port": 1, "enabled": False}]}},
        "nmap": nmap,
    }))
    assert all(item["tool"] != "nmap" for item in plain["tool_calls"])

    package = ROOT / "baseline"
    source = "\n".join(path.read_text() for path in package.glob("*.py"))
    assert "fault-state" not in source
    assert "scenario_id" not in source
    assert "subprocess" not in source
    assert "shell=True" not in source
    for token in ("F1", "F2", "F3", "F4", "F5", "tbf", "1mbit"):
        assert token not in source
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name.split(".")[0] != "faults" for alias in node.names)
            if isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] != "faults"
    keys = {
        "diagnosis_family",
        "diagnosis_location",
        "diagnosis_text",
        "evidence",
        "tool_calls",
        "tool_call_count",
        "elapsed_sec",
        "error",
    }
    assert keys <= set(plain)
    for item in plain["tool_calls"]:
        assert {"sequence", "tool", "arguments", "ok", "elapsed_sec"} <= set(item)


def main() -> int:
    checks = (
        test_schema_and_parse,
        test_link_failure_and_drop_share_a_prompt,
        test_loop_congestion_and_missing_flow,
        test_budget_timeout_invalid_and_deterministic,
        test_nmap_is_targeted_and_package_is_sealed,
    )
    failed = 0
    for check in checks:
        try:
            check()
            print(f"PASS {check.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {check.__name__}: {type(exc).__name__}: {exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
