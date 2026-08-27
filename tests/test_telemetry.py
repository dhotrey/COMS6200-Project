"""Static checks for the M4 telemetry gateway.

Does not contact a live ONOS or Mininet instance. Runtime evidence is
collected separately with scripts/verify_telemetry.sh.
"""

from __future__ import annotations

import ast
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from topologies.spec import (  # noqa: E402
    HOST_ATTACHMENTS,
    HOSTS,
    INTER_SWITCH_LINKS,
    SWITCHES,
)
from telemetry.envelope import error, ok  # noqa: E402
from telemetry.gateway import TelemetryGateway  # noqa: E402
from telemetry.parsers import (  # noqa: E402
    normalize_devices,
    normalize_flows,
    normalize_port_stats,
    normalize_ports,
    parse_iperf,
    parse_ping,
    physical_links_from_onos,
)
from telemetry.schemas import TOOL_SCHEMAS, validate_arguments  # noqa: E402
from telemetry.validate import ValidationError, require_host, require_switch  # noqa: E402

TOPO = ROOT / "topologies" / "main_topology.py"
TELEMETRY = ROOT / "telemetry"


def _const_int(node: ast.AST | None) -> int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    return None


def _name(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def test_host_and_switch_allow_lists() -> None:
    assert HOSTS == ("h1", "h2", "h3", "h4", "h5", "h6", "h7", "h8")
    assert SWITCHES == ("s1", "s2", "s3", "s4", "s5", "s6")
    for host in HOSTS:
        assert require_host(host) == host
    for switch in SWITCHES:
        assert require_switch(switch) == switch


def test_rejects_invalid_hosts_and_switches() -> None:
    for value in ("; rm -rf /", "127.0.0.1", "h9", "s1;reboot", "", 1, None):
        try:
            require_host(value)
        except ValidationError as exc:
            assert exc.code == "INVALID_HOST"
        else:
            raise AssertionError(f"host {value!r} should be rejected")
    for value in ("s7", "of:0000000000000001", "s3;id", "/onos/v1/devices", None):
        try:
            require_switch(value)
        except ValidationError as exc:
            assert exc.code == "INVALID_SWITCH"
        else:
            raise AssertionError(f"switch {value!r} should be rejected")


def test_spec_matches_main_topology_links() -> None:
    tree = ast.parse(TOPO.read_text(encoding="utf-8"))
    links: set[tuple[str, str, int, int]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "addLink" or len(node.args) < 2:
            continue
        a = _name(node.args[0])
        b = _name(node.args[1])
        port1 = port2 = None
        for keyword in node.keywords:
            if keyword.arg == "port1":
                port1 = _const_int(keyword.value)
            if keyword.arg == "port2":
                port2 = _const_int(keyword.value)
        assert a and b and port1 is not None and port2 is not None
        links.add((a, b, port1, port2))
    expected_inter = {(item.a, item.b, item.a_port, item.b_port) for item in INTER_SWITCH_LINKS}
    expected_host = {
        (item.switch, item.host, item.switch_port, item.host_port) for item in HOST_ATTACHMENTS
    }
    assert expected_inter <= links
    assert expected_host <= links
    assert len(INTER_SWITCH_LINKS) == 10
    assert len(HOST_ATTACHMENTS) == 9


def test_h6_primary_and_secondary_mapping() -> None:
    primary = [item for item in HOST_ATTACHMENTS if item.host == "h6" and item.role == "primary"]
    secondary = [item for item in HOST_ATTACHMENTS if item.host == "h6" and item.role == "secondary"]
    assert len(primary) == 1
    assert len(secondary) == 1
    assert primary[0].switch == "s5"
    assert primary[0].switch_port == 4
    assert primary[0].host_intf == "h6-eth0"
    assert primary[0].ipv4 == "10.0.0.6/24"
    assert primary[0].mac == "00:00:00:00:00:06"
    assert secondary[0].switch == "s6"
    assert secondary[0].switch_port == 5
    assert secondary[0].host_intf == "h6-eth1"
    assert secondary[0].ipv4 is None
    assert secondary[0].mac == "00:00:00:00:06:02"


def test_onos_directed_link_dedup() -> None:
    raw = []
    for link in INTER_SWITCH_LINKS:
        left = f"of:000000000000000{link.a[-1]}"
        right = f"of:000000000000000{link.b[-1]}"
        raw.append(
            {
                "src": {"device": left, "port": str(link.a_port)},
                "dst": {"device": right, "port": str(link.b_port)},
                "state": "ACTIVE",
                "type": "DIRECT",
            }
        )
        raw.append(
            {
                "src": {"device": right, "port": str(link.b_port)},
                "dst": {"device": left, "port": str(link.a_port)},
                "state": "ACTIVE",
                "type": "DIRECT",
            }
        )
    assert len(raw) == 20
    physical = physical_links_from_onos(raw)
    assert len(physical) == 10
    names = {
        tuple(sorted((row["a"]["switch"], row["b"]["switch"])))
        for row in physical
    }
    assert ("s3", "s4") in names
    assert physical == sorted(
        physical,
        key=lambda row: (
            str(row["a"]["switch"]),
            int(row["a"]["port"]),
            str(row["b"]["switch"]),
            int(row["b"]["port"]),
        ),
    )


def test_configured_host_attachments() -> None:
    from telemetry.validate import host_attachments

    rows = host_attachments()
    assert len(rows) == 9
    assert all(row["source"] == "configured" for row in rows)
    hosts = [row["host"] for row in rows]
    assert hosts.count("h6") == 2


def test_ping_parser() -> None:
    text = (
        "PING 10.0.0.5 (10.0.0.5) 56(84) bytes of data.\n"
        "64 bytes from 10.0.0.5: icmp_seq=1 ttl=64 time=0.412 ms\n"
        "--- 10.0.0.5 ping statistics ---\n"
        "3 packets transmitted, 3 received, 0% packet loss, time 2045ms\n"
        "rtt min/avg/max/mdev = 0.312/0.401/0.512/0.080 ms\n"
    )
    parsed = parse_ping(text)
    assert parsed["sent"] == 3
    assert parsed["received"] == 3
    assert parsed["loss_pct"] == 0.0
    assert parsed["rtt_min_ms"] == 0.312
    assert parsed["rtt_avg_ms"] == 0.401
    assert parsed["rtt_max_ms"] == 0.512

    lost = parse_ping("3 packets transmitted, 0 received, 100% packet loss, time 2045ms\n")
    assert lost["received"] == 0
    assert lost["loss_pct"] == 100.0
    assert lost["rtt_avg_ms"] is None


def test_iperf_json_parser() -> None:
    payload = {
        "end": {
            "sum_sent": {"bytes": 2_500_000, "bits_per_second": 10_000_000, "retransmits": 1, "seconds": 2.0},
            "sum_received": {"bytes": 2_400_000, "bits_per_second": 9_600_000, "seconds": 2.0},
        }
    }
    parsed = parse_iperf(json.dumps(payload))
    assert parsed["bytes_transferred"] == 2_400_000
    assert parsed["mbit_per_sec"] == 9.6
    assert parsed["retransmissions"] == 1
    assert parsed["duration_sec"] == 2.0
    try:
        parse_iperf("not json")
    except ValueError:
        pass
    else:
        raise AssertionError("non-JSON iperf output should fail")


def test_flow_normalization_and_order() -> None:
    flows = [
        {
            "id": "2",
            "deviceId": "of:0000000000000003",
            "tableId": 0,
            "state": "ADDED",
            "priority": 41000,
            "appId": "org.coms6200.baseline",
            "selector": {"criteria": [{"type": "ETH_DST", "mac": "00:00:00:00:00:01"}]},
            "treatment": {"instructions": [{"type": "OUTPUT", "port": "3"}]},
            "packets": 4,
            "bytes": 400,
            "life": 12,
        },
        {
            "id": "1",
            "deviceId": "of:0000000000000003",
            "tableId": 0,
            "state": "ADDED",
            "priority": 42000,
            "appId": "org.coms6200.baseline",
            "selector": {"criteria": [{"type": "ETH_TYPE", "ethType": "0x806"}]},
            "treatment": {"instructions": [{"type": "OUTPUT", "port": "1"}]},
            "packets": 1,
            "bytes": 64,
            "life": 12,
        },
        {
            "id": "9",
            "deviceId": "of:0000000000000001",
            "priority": 41000,
        },
    ]
    rows = normalize_flows("s3", "of:0000000000000003", flows)
    assert len(rows) == 2
    assert rows[0]["priority"] == 42000
    assert rows[1]["id"] == "2"
    assert "fault" not in json.dumps(rows).lower()
    assert rows[0]["app_id"] == "org.coms6200.baseline"


def test_port_normalization() -> None:
    ports = [
        {
            "port": "3",
            "isEnabled": True,
            "type": "copper",
            "portSpeed": 10000,
            "annotations": {"portName": "s3-eth3"},
        },
        {
            "port": "1",
            "isEnabled": True,
            "type": "copper",
            "portSpeed": 10000,
            "annotations": {"portName": "s3-eth1"},
        },
    ]
    rows = normalize_ports("s3", ports)
    assert [row["port"] for row in rows] == [1, 3]
    assert rows[0]["enabled"] is True
    assert rows[0]["peer"] == {"kind": "switch", "id": "s1", "port": 2}
    assert rows[1]["peer"] == {"kind": "host", "id": "h1", "intf": "h1-eth0", "role": "primary"}
    assert "admin_state" not in rows[0]
    assert "operational_state" not in rows[0]


def test_port_stats_rates_and_null_utilization() -> None:
    first = [
        {
            "device": "of:0000000000000003",
            "ports": [
                {
                    "port": 1,
                    "packetsReceived": 10,
                    "packetsSent": 11,
                    "bytesReceived": 1000,
                    "bytesSent": 2000,
                    "packetsRxDropped": 0,
                    "packetsTxDropped": 0,
                    "packetsRxErrors": 0,
                    "packetsTxErrors": 0,
                    "durationSec": 10,
                }
            ],
        }
    ]
    second = [
        {
            "device": "of:0000000000000003",
            "ports": [
                {
                    "port": 1,
                    "packetsReceived": 20,
                    "packetsSent": 21,
                    "bytesReceived": 3000,
                    "bytesSent": 6000,
                    "packetsRxDropped": 1,
                    "packetsTxDropped": 0,
                    "packetsRxErrors": 0,
                    "packetsTxErrors": 0,
                    "durationSec": 11,
                }
            ],
        }
    ]
    data = normalize_port_stats("s3", "of:0000000000000003", first, second, 1.0)
    assert data["ports"][0]["rx_bits_per_sec"] == 16000.0
    assert data["ports"][0]["tx_bits_per_sec"] == 32000.0
    assert data["ports"][0]["utilization_pct"] is None
    assert data["rate_method"] == "two_sample_byte_delta"


def test_error_envelope() -> None:
    payload = error("ping", "INVALID_HOST", "host must be one of ...")
    assert payload["ok"] is False
    assert payload["data"] is None
    assert payload["tool"] == "ping"
    assert payload["error"]["code"] == "INVALID_HOST"
    assert "Traceback" not in json.dumps(payload)
    good = ok("get_topology", {"summary": {}})
    assert good["ok"] is True
    assert good["error"] is None
    assert good["timestamp"].endswith("Z")


def test_gateway_validation_errors_use_envelope() -> None:
    gateway = TelemetryGateway(client=object())  # type: ignore[arg-type]
    ping = gateway.ping("; rm -rf /", "h5")
    assert ping["ok"] is False
    assert ping["error"]["code"] == "INVALID_HOST"
    status = gateway.get_port_status("s7")
    assert status["ok"] is False
    assert status["error"]["code"] == "INVALID_SWITCH"
    ip_host = gateway.ping("127.0.0.1", "h5")
    assert ip_host["error"]["code"] == "INVALID_HOST"


def test_hybrid_topology_does_not_use_onos_hosts() -> None:
    class FakeOnos:
        def devices(self):
            return [
                {
                    "id": f"of:000000000000000{idx}",
                    "available": True,
                    "role": "MASTER",
                    "hw": "Open vSwitch",
                    "sw": "3.3.9",
                    "annotations": {"protocol": "OF_13", "datapathDescription": f"s{idx}"},
                }
                for idx in range(1, 7)
            ]

        def links(self):
            rows = []
            for link in INTER_SWITCH_LINKS:
                left = f"of:000000000000000{link.a[-1]}"
                right = f"of:000000000000000{link.b[-1]}"
                rows.append(
                    {
                        "src": {"device": left, "port": link.a_port},
                        "dst": {"device": right, "port": link.b_port},
                        "state": "ACTIVE",
                        "type": "DIRECT",
                    }
                )
                rows.append(
                    {
                        "src": {"device": right, "port": link.b_port},
                        "dst": {"device": left, "port": link.a_port},
                        "state": "ACTIVE",
                        "type": "DIRECT",
                    }
                )
            return rows

        def hosts(self):  # pragma: no cover - must not be called
            raise AssertionError("get_topology must not query ONOS /hosts")

    gateway = TelemetryGateway(client=FakeOnos())  # type: ignore[arg-type]
    result = gateway.get_topology()
    assert result["ok"] is True
    data = result["data"]
    assert data["summary"]["switches"] == 6
    assert data["summary"]["physical_inter_switch_links"] == 10
    assert data["summary"]["configured_host_attachments"] == 9
    assert data["summary"]["logical_hosts"] == 8
    assert data["summary"]["total_physical_links"] == 19
    assert data["summary"]["onos_host_discovery"] == "not_used"
    h6 = [row for row in data["host_attachments"] if row["host"] == "h6"]
    assert {row["role"] for row in h6} == {"primary", "secondary"}


def test_tool_schemas_reject_arbitrary_properties() -> None:
    validate_arguments("get_topology", {})
    validate_arguments("ping", {"src": "h1", "dst": "h5"})
    try:
        validate_arguments("ping", {"src": "h1", "dst": "h5", "cmd": "rm -rf /"})
    except ValidationError as exc:
        assert exc.code == "INVALID_ARGUMENT"
    else:
        raise AssertionError("extra ping property should be rejected")
    try:
        validate_arguments("get_port_status", {"sw": "s7"})
    except ValidationError as exc:
        assert "allowed" in exc.message or exc.code == "INVALID_ARGUMENT"
    else:
        raise AssertionError("s7 should be rejected by schema")
    try:
        validate_arguments("ping", {"src": "127.0.0.1", "dst": "h5"})
    except ValidationError:
        pass
    else:
        raise AssertionError("IP src should be rejected by schema")
    try:
        validate_arguments("get_flow_table", {"sw": "s3", "path": "/onos/v1/flows"})
    except ValidationError:
        pass
    else:
        raise AssertionError("arbitrary REST path property should be rejected")
    assert TOOL_SCHEMAS["ping"]["parameters"]["additionalProperties"] is False


def test_onos_client_has_no_generic_or_hosts_path() -> None:
    source = (TELEMETRY / "onos_client.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    methods = {
        item.name
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "OnosClient"
        for item in node.body
        if isinstance(item, ast.FunctionDef)
    }
    assert "hosts" not in methods
    public = {name for name in methods if not name.startswith("_")}
    assert "get" not in public
    assert "/hosts" not in source
    assert "from_env" in methods
    assert "devices" in methods
    assert "links" in methods
    assert "flows" in methods
    assert "device_ports" in methods
    assert "port_statistics" in methods
    gateway_src = (TELEMETRY / "gateway.py").read_text(encoding="utf-8")
    assert "/hosts" not in gateway_src
    assert "shell=True" not in gateway_src


def test_no_shell_true_in_telemetry_package() -> None:
    for path in TELEMETRY.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "shell=True" not in text.replace(" ", "")
        assert "shell = True" not in text


def test_cli_rejects_extra_flags() -> None:
    env = {**dict(**{k: v for k, v in __import__("os").environ.items()}), "PYTHONPATH": str(ROOT)}
    cases = [
        ["-m", "telemetry.cli", "get-topology", "--path", "/onos/v1/devices"],
        ["-m", "telemetry.cli", "ping", "--src", "h1", "--dst", "h5", "--cmd", "rm"],
        ["-m", "telemetry.cli", "iperf", "--src", "h1", "--dst", "h5", "--flags", "-u"],
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
        combined = completed.stdout + completed.stderr
        assert "unrecognized arguments" in combined or "invalid" in combined.lower()


def test_cli_rejects_injection_hosts() -> None:
    env = {"PYTHONPATH": str(ROOT), **{k: v for k, v in __import__("os").environ.items()}}
    completed = subprocess.run(
        [sys.executable, "-m", "telemetry.cli", "ping", "--src", "; rm -rf /", "--dst", "h5"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    payload = json.loads(completed.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "INVALID_HOST"
    assert "Traceback" not in completed.stdout


def test_device_normalization_sort() -> None:
    rows = normalize_devices(
        [
            {"id": "of:0000000000000002", "available": True, "annotations": {"datapathDescription": "s2", "protocol": "OF_13"}},
            {"id": "of:0000000000000001", "available": True, "annotations": {"datapathDescription": "s1", "protocol": "OF_13"}},
        ]
    )
    assert [row["name"] for row in rows] == ["s1", "s2"]


def main() -> int:
    checks = (
        test_host_and_switch_allow_lists,
        test_rejects_invalid_hosts_and_switches,
        test_spec_matches_main_topology_links,
        test_h6_primary_and_secondary_mapping,
        test_onos_directed_link_dedup,
        test_configured_host_attachments,
        test_ping_parser,
        test_iperf_json_parser,
        test_flow_normalization_and_order,
        test_port_normalization,
        test_port_stats_rates_and_null_utilization,
        test_error_envelope,
        test_gateway_validation_errors_use_envelope,
        test_hybrid_topology_does_not_use_onos_hosts,
        test_tool_schemas_reject_arbitrary_properties,
        test_onos_client_has_no_generic_or_hosts_path,
        test_no_shell_true_in_telemetry_package,
        test_cli_rejects_extra_flags,
        test_cli_rejects_injection_hosts,
        test_device_normalization_sort,
    )
    failed = 0
    for check in checks:
        try:
            check()
            print(f"PASS {check.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {check.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001 — report unexpected test errors
            failed += 1
            print(f"FAIL {check.__name__}: {type(exc).__name__}: {exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
