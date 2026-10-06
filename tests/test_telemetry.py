"""Static checks for the M4 telemetry gateway.

Does not contact a live ONOS or Mininet instance. Runtime evidence is
collected separately with scripts/verify_telemetry.sh.
"""

from __future__ import annotations

import ast
import json
import os
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
    assert parsed["sender_bytes"] == 2_500_000
    assert parsed["sender_bits_per_sec"] == 10_000_000
    assert parsed["sender_duration_sec"] == 2.0
    assert parsed["receiver_bytes"] == 2_400_000
    assert parsed["receiver_bits_per_sec"] == 9_600_000
    assert parsed["receiver_duration_sec"] == 2.0
    assert parsed["bytes_transferred"] == 2_400_000
    assert parsed["mbit_per_sec"] == 9.6
    assert parsed["retransmissions"] == 1
    assert parsed["retransmits"] == 1
    assert parsed["duration_sec"] == 2.0

    stalled = parse_iperf(json.dumps({
        "end": {
            "sum_sent": {"bytes": 131072, "bits_per_second": 524288, "retransmits": 11, "seconds": 2.0},
            "sum_received": {"bytes": 0, "bits_per_second": 0, "seconds": 2.1},
        }
    }))
    assert stalled["sender_bytes"] == 131072
    assert stalled["sender_bits_per_sec"] == 524288
    assert stalled["receiver_bytes"] == 0
    assert stalled["receiver_bits_per_sec"] == 0
    assert stalled["bytes_transferred"] == 0
    assert stalled["mbit_per_sec"] == 0.0
    assert stalled["retransmits"] == 11

    sender_only = parse_iperf(json.dumps({
        "end": {
            "sum_sent": {"bytes": 1000, "bits_per_second": 8000, "retransmits": 0, "seconds": 1.0},
        }
    }))
    assert sender_only["sender_bytes"] == 1000
    assert sender_only["receiver_bytes"] is None
    assert sender_only["bytes_transferred"] == 1000
    assert sender_only["mbit_per_sec"] == 0.008

    try:
        parse_iperf("not json")
    except ValueError:
        pass
    else:
        raise AssertionError("non-JSON iperf output should fail")
    try:
        parse_iperf(json.dumps({"error": "unable to connect to server"}))
    except ValueError as exc:
        assert "unable to connect" in str(exc)
    else:
        raise AssertionError("iperf command error should fail rather than report zero throughput")


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


def test_tree_topology_metadata_filters_stale_main_devices() -> None:
    class FakeOnos:
        def devices(self):
            return [
                {
                    "id": f"of:000000000000000{idx}",
                    "available": idx < 6,
                    "role": "MASTER" if idx < 6 else "NONE",
                    "annotations": {"protocol": "OF_13"},
                }
                for idx in range(1, 7)
            ]

        def links(self):
            return []

    previous = os.environ.get("COMS6200_TOPOLOGY")
    os.environ["COMS6200_TOPOLOGY"] = "tree5s8h"
    try:
        result = TelemetryGateway(client=FakeOnos()).get_topology()  # type: ignore[arg-type]
    finally:
        if previous is None:
            os.environ.pop("COMS6200_TOPOLOGY", None)
        else:
            os.environ["COMS6200_TOPOLOGY"] = previous

    assert result["ok"] is True
    data = result["data"]
    assert data["summary"]["switches"] == 5
    assert data["summary"]["configured_inter_switch_links"] == 4
    assert data["summary"]["configured_host_attachments"] == 8
    assert data["summary"]["total_physical_links"] == 12
    assert {row["name"] for row in data["switches"]} == {"s1", "s2", "s3", "s4", "s5"}


def test_host_exec_permission_denied_is_not_parse_error() -> None:
    from unittest.mock import patch

    from telemetry.host_exec import HostExecError, run_in_host

    completed = subprocess.CompletedProcess(
        args=["mnexec"],
        returncode=1,
        stdout="",
        stderr="mnexec: Permission denied\n",
    )
    with (
        patch("telemetry.host_exec.find_host_pid", return_value=1),
        patch("telemetry.host_exec._is_host_shell", return_value=True),
        patch("telemetry.host_exec._mnexec", return_value="/usr/bin/mnexec"),
        patch("telemetry.host_exec.subprocess.run", return_value=completed),
    ):
        try:
            run_in_host("h1", ["ping", "-n", "-c", "1", "10.0.0.5"], timeout_s=2.0)
        except HostExecError as exc:
            assert exc.code == "HOST_NAMESPACE_DENIED"
            return
        raise AssertionError("expected HOST_NAMESPACE_DENIED")


def test_iperf_cleanup_only_targets_gateway_port() -> None:
    import re
    from unittest.mock import patch

    from faults.scenarios import F2
    from telemetry.gateway import IPERF_PORT, _stop_host_iperf

    calls: list[list[str]] = []
    with patch(
        "telemetry.gateway.run_in_host",
        side_effect=lambda host, argv, timeout_s: calls.append(argv),
    ):
        _stop_host_iperf("h6")
    assert len(calls) == 1
    argv = calls[0]
    assert argv[:2] == ["pkill", "-f"], argv
    assert "-x" not in argv
    # pkill -f matches the full space-joined command line.
    pattern = re.compile(argv[2])
    gateway_cmdlines = (
        f"iperf3 -s -1 -J -p {IPERF_PORT}",
        f"iperf3 -c 10.0.0.5 -t 2 -J -p {IPERF_PORT}",
        f"/usr/bin/iperf3 -s -1 -J -p {IPERF_PORT}",
    )
    other_cmdlines = (
        f"iperf3 -s -p {F2.iperf_port}",
        f"iperf3 -c 10.0.0.6 -t 0 -p {F2.iperf_port}",
        f"iperf3 -s -p {IPERF_PORT}0",
        "/usr/bin/mnexec -a 123 -- pkill -f " + argv[2],
    )
    assert F2.iperf_port != IPERF_PORT
    for cmdline in gateway_cmdlines:
        assert pattern.search(cmdline), cmdline
    for cmdline in other_cmdlines:
        assert not pattern.search(cmdline), cmdline


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



def test_canonical_tool_list_includes_nmap_and_matches_schemas() -> None:
    from telemetry.gateway import tool_names
    from telemetry.schemas import CANONICAL_TOOL_NAMES, TOOL_SCHEMAS, schema_list

    expected = (
        "get_topology",
        "ping",
        "nmap",
        "get_port_status",
        "get_port_stats",
        "get_link_metrics",
        "get_flow_table",
        "iperf",
    )
    assert CANONICAL_TOOL_NAMES == expected
    assert tool_names() == expected
    names = tuple(item["name"] for item in schema_list())
    assert names == expected
    assert set(names) == set(TOOL_SCHEMAS)


def test_device_normalization_sort() -> None:
    rows = normalize_devices(
        [
            {"id": "of:0000000000000002", "available": True, "annotations": {"datapathDescription": "s2", "protocol": "OF_13"}},
            {"id": "of:0000000000000001", "available": True, "annotations": {"datapathDescription": "s1", "protocol": "OF_13"}},
        ]
    )
    assert [row["name"] for row in rows] == ["s1", "s2"]



def test_link_metrics_mapping_rates_queue_and_no_config_leak() -> None:
    import json
    import subprocess

    from telemetry.link_metrics import (
        build_link_metrics,
        interface_name,
        parse_qdisc_counters,
        public_peer,
        read_qdisc_text,
        require_switch_port,
    )
    from telemetry.schemas import TOOL_SCHEMAS

    assert require_switch_port("s1", 4) == ("s1", 4)
    assert interface_name("s1", 4) == "s1-eth4"
    assert public_peer("s1", 4) == {"switch": "s5", "port": 1}
    assert public_peer("s5", 1) == {"switch": "s1", "port": 4}
    assert public_peer("s3", 3) == {"host": "h1"}

    invalid_switch = TelemetryGateway().get_link_metrics("s9", 4)
    assert invalid_switch["ok"] is False
    assert invalid_switch["error"]["code"] == "INVALID_SWITCH"
    invalid_port = TelemetryGateway().get_link_metrics("s5", 5)
    assert invalid_port["ok"] is False
    assert invalid_port["error"]["code"] == "INVALID_PORT"
    invalid_type = TelemetryGateway().get_link_metrics("s1", "s1-eth4")
    assert invalid_type["ok"] is False
    assert invalid_type["error"]["code"] == "INVALID_PORT"

    shaped = """
qdisc tbf 8008: root refcnt 2 rate 1Mbit burst 4Kb lat 400ms
 Sent 1000 bytes 10 pkt (dropped 0, overlimits 4 requeues 1)
 backlog 1500b 2p requeues 1
"""
    later = """
qdisc tbf 8008: root refcnt 2 rate 1Mbit burst 4Kb lat 400ms
 Sent 2000 bytes 20 pkt (dropped 0, overlimits 9 requeues 3)
 backlog 0b 0p requeues 3
"""
    first = parse_qdisc_counters(shaped)
    second = parse_qdisc_counters(later)
    assert first["backlog_bytes"] == 1500
    assert first["backlog_packets"] == 2
    assert first["overlimits"] == 4
    assert first["requeues"] == 1
    measured = build_link_metrics(
        "s1",
        4,
        True,
        2.0,
        {
            "rx_bytes": 1000, "tx_bytes": 1000,
            "rx_packets": 10, "tx_packets": 10,
            "rx_dropped": 1, "tx_dropped": 2,
            "rx_errors": 3, "tx_errors": 4,
        },
        {
            "rx_bytes": 3000, "tx_bytes": 3500,
            "rx_packets": 20, "tx_packets": 30,
            "rx_dropped": 4, "tx_dropped": 2,
            "rx_errors": 3, "tx_errors": 6,
        },
        first,
        second,
    )
    assert measured["tx_bytes_delta"] == 2500
    assert measured["tx_bits_per_sec"] == 10000.0
    assert measured["rx_packets_delta"] == 10
    assert measured["tx_packets_per_sec"] == 10.0
    assert measured["rx_drops_delta"] == 3
    assert measured["tx_drops_delta"] == 0
    assert measured["rx_errors_delta"] == 0
    assert measured["tx_errors_delta"] == 2
    assert measured["queue_backlog_bytes"] == 0
    assert measured["queue_backlog_packets"] == 0
    assert measured["queue_overlimits_delta"] == 5
    assert measured["queue_requeues_delta"] == 2
    assert measured["peer"] == {"switch": "s5", "port": 1}

    unavailable = build_link_metrics(
        "s1", 4, None, 2.0,
        {"rx_bytes": 1, "tx_bytes": 1, "rx_packets": 1, "tx_packets": 1,
         "rx_dropped": 0, "tx_dropped": 0, "rx_errors": 0, "tx_errors": 0},
        {"rx_bytes": 1, "tx_bytes": 1, "rx_packets": 1, "tx_packets": 1,
         "rx_dropped": 0, "tx_dropped": 0, "rx_errors": 0, "tx_errors": 0},
        parse_qdisc_counters(""),
        parse_qdisc_counters(""),
    )
    assert unavailable["queue_backlog_bytes"] is None
    assert unavailable["queue_overlimits_delta"] is None
    assert unavailable["queue_requeues_delta"] is None
    assert unavailable["tx_bits_per_sec"] == 0.0

    blob = json.dumps({"parsed": first, "result": measured}).lower()
    for forbidden in ("tbf", "1mbit", "400ms", "burst", "qdisc", "noqueue", "f2", "scenario"):
        assert forbidden not in blob

    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs.get("shell")))
        completed = subprocess.CompletedProcess(argv, 0, stdout="backlog 0b 0p\n", stderr="")
        return completed

    import telemetry.link_metrics as link_metrics
    original = link_metrics.subprocess.run
    link_metrics.subprocess.run = fake_run
    try:
        read_qdisc_text("s1-eth4")
        try:
            read_qdisc_text("eth0")
        except ValidationError:
            pass
        else:
            raise AssertionError("unchecked interface should be rejected")
    finally:
        link_metrics.subprocess.run = original
    assert calls == [(["tc", "-s", "qdisc", "show", "dev", "s1-eth4"], False)]

    spec = TOOL_SCHEMAS["get_link_metrics"]
    assert spec["parameters"]["additionalProperties"] is False
    assert spec["parameters"]["properties"]["port"]["maximum"] == 5
    description = spec["description"].lower()
    for forbidden in ("f2", "congestion", "tbf", "bottleneck"):
        assert forbidden not in description
    validate_arguments("get_link_metrics", {"sw": "s1", "port": 4})
    try:
        validate_arguments("get_link_metrics", {"sw": "s1", "port": 4, "dev": "s1-eth4"})
    except ValidationError:
        pass
    else:
        raise AssertionError("interface argument should be rejected")



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
        test_link_metrics_mapping_rates_queue_and_no_config_leak,
        test_error_envelope,
        test_gateway_validation_errors_use_envelope,
        test_hybrid_topology_does_not_use_onos_hosts,
        test_tree_topology_metadata_filters_stale_main_devices,
        test_host_exec_permission_denied_is_not_parse_error,
        test_iperf_cleanup_only_targets_gateway_port,
        test_tool_schemas_reject_arbitrary_properties,
        test_onos_client_has_no_generic_or_hosts_path,
        test_no_shell_true_in_telemetry_package,
        test_cli_rejects_extra_flags,
        test_cli_rejects_injection_hosts,
        test_device_normalization_sort,
        test_canonical_tool_list_includes_nmap_and_matches_schemas,
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
