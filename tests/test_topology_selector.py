"""Static checks for COMS6200_TOPOLOGY selection (topologies/active.py).

Does not contact ONOS or Mininet. The selection is read at import time, so
each topology is checked in a fresh interpreter with a controlled environment.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from topologies import ring_spec, tree_spec  # noqa: E402
from topologies import spec as main_spec  # noqa: E402


def _run(code: str, topology: str | None) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if key != "COMS6200_TOPOLOGY"}
    if topology is not None:
        env["COMS6200_TOPOLOGY"] = topology
    env["PYTHONPATH"] = str(ROOT)
    return subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60
    )


def _json(code: str, topology: str | None) -> dict:
    completed = _run(code, topology)
    assert completed.returncode == 0, completed.stderr[-2000:]
    return json.loads(completed.stdout)


_SELECTION = (
    "import json\n"
    "from topologies import active\n"
    "print(json.dumps({'topology': active.TOPOLOGY, 'switches': active.SWITCHES,\n"
    "  'hosts': active.HOSTS, 'devices': active.DEVICE_IDS,\n"
    "  'links': len(active.INTER_SWITCH_LINKS), 'attachments': len(active.HOST_ATTACHMENTS)}))\n"
)


def test_default_is_main6s8h() -> None:
    for value in (None, "", "main6s8h"):
        result = _json(_SELECTION, value)
        assert result["topology"] == "main6s8h", (value, result)
        assert result["switches"] == list(main_spec.SWITCHES)
        assert result["devices"] == main_spec.DEVICE_IDS
        assert (result["links"], result["attachments"]) == (10, 9)


def test_ring_selection() -> None:
    result = _json(_SELECTION, "ring5s5h")
    assert result["topology"] == "ring5s5h"
    assert result["switches"] == list(ring_spec.SWITCHES)
    assert result["hosts"] == list(ring_spec.HOSTS)
    assert result["devices"] == ring_spec.DEVICE_IDS
    assert (result["links"], result["attachments"]) == (5, 5)


def test_tree_selection() -> None:
    result = _json(_SELECTION, "tree5s8h")
    assert result["topology"] == "tree5s8h"
    assert result["switches"] == list(tree_spec.SWITCHES)
    assert result["hosts"] == list(tree_spec.HOSTS)
    assert result["devices"] == tree_spec.DEVICE_IDS
    assert (result["links"], result["attachments"]) == (6, 8)


def test_unknown_topology_is_rejected() -> None:
    completed = _run("import topologies.active", "ring6s6h")
    assert completed.returncode != 0
    assert "COMS6200_TOPOLOGY='ring6s6h' is not one of" in completed.stderr


def test_main6s8h_link_metrics_port_range_unchanged() -> None:
    result = _json(
        "import json\n"
        "from telemetry.schemas import TOOL_SCHEMAS\n"
        "print(json.dumps(TOOL_SCHEMAS['get_link_metrics']['parameters']['properties']['port']))\n",
        None,
    )
    assert result == {"type": "integer", "minimum": 1, "maximum": 5}, result


def test_telemetry_follows_ring() -> None:
    code = """
import json
from telemetry import parsers, validate
from telemetry.gateway import TelemetryGateway
from telemetry.link_metrics import require_switch_port
from telemetry.schemas import TOOL_SCHEMAS
from telemetry.validate import ValidationError
from topologies.active import DEVICE_IDS, INTER_SWITCH_LINKS


def rejected(fn, *args):
    try:
        fn(*args)
    except ValidationError as exc:
        return exc.code
    return None


class FakeOnos:
    def devices(self):
        return [
            {"id": device_id, "available": True, "annotations": {"protocol": "OF_13"}}
            for device_id in DEVICE_IDS.values()
        ]

    def links(self):
        rows = []
        for link in INTER_SWITCH_LINKS:
            a, b = DEVICE_IDS[link.a], DEVICE_IDS[link.b]
            rows.append({"src": {"device": a, "port": link.a_port}, "dst": {"device": b, "port": link.b_port}, "state": "ACTIVE"})
            rows.append({"src": {"device": b, "port": link.b_port}, "dst": {"device": a, "port": link.a_port}, "state": "ACTIVE"})
        return rows


topology = TelemetryGateway(client=FakeOnos()).get_topology()
props = {name: schema["parameters"]["properties"] for name, schema in TOOL_SCHEMAS.items()}
print(json.dumps({
    "ping_hosts": props["ping"]["src"]["enum"],
    "flow_switches": props["get_flow_table"]["sw"]["enum"],
    "link_port": props["get_link_metrics"]["port"],
    "h6": rejected(validate.require_host, "h6"),
    "s6": rejected(validate.require_switch, "s6"),
    "s1_port4": rejected(require_switch_port, "s1", 4),
    "s1_port3": rejected(require_switch_port, "s1", 3),
    "h5_ip": validate.primary_ip("h5"),
    "configured_links": len(parsers.configured_inter_switch_links()),
    "summary": topology["data"]["summary"],
    "observed_names": sorted(row["name"] for row in topology["data"]["switches"]),
    "observed_link_names": sorted(
        f"{row['a']['switch']}:{row['a']['port']}-{row['b']['switch']}:{row['b']['port']}"
        for row in topology["data"]["links"]
    ),
}))
"""
    result = _json(code, "ring5s5h")
    assert result["ping_hosts"] == ["h1", "h2", "h3", "h4", "h5"], result
    assert result["flow_switches"] == ["s1", "s2", "s3", "s4", "s5"], result
    assert result["link_port"] == {"type": "integer", "minimum": 1, "maximum": 3}, result
    assert result["h6"] == "INVALID_HOST" and result["s6"] == "INVALID_SWITCH", result
    assert result["s1_port4"] == "INVALID_PORT" and result["s1_port3"] is None, result
    assert result["h5_ip"] == "10.0.0.5"
    assert result["configured_links"] == 5
    summary = result["summary"]
    assert summary["switches"] == 5 and summary["observed_switches"] == 5, summary
    assert summary["physical_inter_switch_links"] == 5, summary
    assert summary["logical_hosts"] == 5 and summary["total_physical_links"] == 10, summary
    assert result["observed_names"] == ["s1", "s2", "s3", "s4", "s5"], result
    assert result["observed_link_names"] == [
        "s1:1-s2:2",
        "s1:2-s5:1",
        "s2:1-s3:2",
        "s3:1-s4:2",
        "s4:1-s5:2",
    ], result


def main() -> int:
    checks = (
        test_default_is_main6s8h,
        test_ring_selection,
        test_unknown_topology_is_rejected,
        test_main6s8h_link_metrics_port_range_unchanged,
        test_telemetry_follows_ring,
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
