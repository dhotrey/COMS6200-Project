"""Static checks for deterministic main6s8h baseline forwarding.

Does not contact ONOS or Mininet. Runtime evidence is collected separately
on the Ubuntu server.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "forwarding"))

import baseline_forwarding as bf  # noqa: E402


def test_primary_host_macs() -> None:
    expected = {
        "h1": "00:00:00:00:00:01",
        "h2": "00:00:00:00:00:02",
        "h3": "00:00:00:00:00:03",
        "h4": "00:00:00:00:00:04",
        "h5": "00:00:00:00:00:05",
        "h6": "00:00:00:00:00:06",
        "h7": "00:00:00:00:00:07",
        "h8": "00:00:00:00:00:08",
    }
    assert bf.HOST_MACS == expected
    assert "00:00:00:00:06:02" not in bf.HOST_MACS.values()


def test_s1_mapping() -> None:
    assert bf.UNICAST_EGRESS["s1"] == {
        "h1": 2,
        "h2": 2,
        "h3": 3,
        "h4": 3,
        "h5": 4,
        "h6": 4,
        "h7": 5,
        "h8": 5,
    }


def test_access_switch_mappings() -> None:
    assert bf.UNICAST_EGRESS["s3"] == {
        "h1": 3,
        "h2": 4,
        "h3": 1,
        "h4": 1,
        "h5": 1,
        "h6": 1,
        "h7": 1,
        "h8": 1,
    }
    assert bf.UNICAST_EGRESS["s4"] == {
        "h1": 1,
        "h2": 1,
        "h3": 3,
        "h4": 4,
        "h5": 1,
        "h6": 1,
        "h7": 1,
        "h8": 1,
    }
    assert bf.UNICAST_EGRESS["s5"] == {
        "h1": 1,
        "h2": 1,
        "h3": 1,
        "h4": 1,
        "h5": 3,
        "h6": 4,
        "h7": 1,
        "h8": 1,
    }
    assert bf.UNICAST_EGRESS["s6"] == {
        "h1": 1,
        "h2": 1,
        "h3": 1,
        "h4": 1,
        "h5": 1,
        "h6": 1,
        "h7": 3,
        "h8": 4,
    }


def test_s2_has_no_host_forwarding() -> None:
    assert "s2" not in bf.UNICAST_EGRESS
    assert bf.ARP_ACTIVE_PORTS["s2"] == ()
    assert all(spec.switch != "s2" for spec in bf.expected_flow_specs())


def test_h6_uses_s5_not_s6() -> None:
    assert bf.UNICAST_EGRESS["s1"]["h6"] == 4
    assert bf.UNICAST_EGRESS["s5"]["h6"] == 4
    assert bf.UNICAST_EGRESS["s6"]["h6"] == 1


def test_reserved_links_never_in_outputs() -> None:
    specs = bf.expected_flow_specs()
    for spec in specs:
        reserved = bf.RESERVED_PORTS[spec.switch]
        overlap = set(spec.outputs) & reserved
        assert not overlap, f"{spec.switch} outputs reserved {overlap}"

    s3_s4_outputs = [
        spec
        for spec in specs
        if (spec.switch == "s3" and 5 in spec.outputs) or (spec.switch == "s4" and 5 in spec.outputs)
    ]
    assert s3_s4_outputs == []

    s1_s2 = [spec for spec in specs if spec.switch == "s1" and 1 in spec.outputs]
    assert s1_s2 == []

    s2_uplinks = [
        spec
        for spec in specs
        if spec.switch in {"s3", "s4", "s5", "s6"} and 2 in spec.outputs
    ]
    assert s2_uplinks == []

    h6_secondary = [spec for spec in specs if spec.switch == "s6" and 5 in spec.outputs]
    assert h6_secondary == []


def test_arp_active_tree_ports() -> None:
    assert bf.ARP_ACTIVE_PORTS["s1"] == (2, 3, 4, 5)
    assert bf.ARP_ACTIVE_PORTS["s3"] == (1, 3, 4)
    assert bf.ARP_ACTIVE_PORTS["s4"] == (1, 3, 4)
    assert bf.ARP_ACTIVE_PORTS["s5"] == (1, 3, 4)
    assert bf.ARP_ACTIVE_PORTS["s6"] == (1, 3, 4)
    for switch, ports in bf.ARP_ACTIVE_PORTS.items():
        assert set(ports).isdisjoint(bf.RESERVED_PORTS[switch]), switch


def test_arp_never_outputs_ingress() -> None:
    for switch, ports in bf.ARP_ACTIVE_PORTS.items():
        for in_port in ports:
            outs = bf.arp_outputs(switch, in_port)
            assert in_port not in outs
            assert set(outs) == set(ports) - {in_port}


def test_no_duplicate_selectors() -> None:
    keys = [(spec.device_id, spec.priority, spec.selector) for spec in bf.expected_flow_specs()]
    dupes = [item for item, count in Counter(keys).items() if count > 1]
    assert dupes == []


def test_flow_counts_and_priorities() -> None:
    specs = bf.expected_flow_specs()
    assert len(specs) == 56
    counts = bf.expected_count_by_switch()
    assert counts == {"s1": 12, "s2": 0, "s3": 11, "s4": 11, "s5": 11, "s6": 11}
    assert bf.BASELINE_UNICAST_PRIORITY == 41000
    assert bf.BASELINE_ARP_PRIORITY == 42000
    assert bf.BASELINE_ARP_PRIORITY > 40000
    assert bf.BASELINE_UNICAST_PRIORITY > 40000
    assert bf.FAULT_PRIORITY > bf.BASELINE_ARP_PRIORITY
    assert all(spec.priority != 40000 for spec in specs)
    assert bf.APP_NAME == "org.coms6200.baseline"


def test_json_uses_multiple_outputs_for_arp() -> None:
    arp = next(spec for spec in bf.expected_flow_specs() if spec.kind == "arp" and spec.switch == "s3")
    payload = bf.spec_to_onos_json(arp)
    ports = [item["port"] for item in payload["treatment"]["instructions"]]
    assert payload["treatment"]["instructions"][0]["type"] == "OUTPUT"
    assert len(ports) >= 2
    assert "FLOOD" not in ports
    assert "NORMAL" not in ports
    assert payload["appId"] == bf.APP_NAME
    assert payload["isPermanent"] is True


def main() -> int:
    checks = (
        test_primary_host_macs,
        test_s1_mapping,
        test_access_switch_mappings,
        test_s2_has_no_host_forwarding,
        test_h6_uses_s5_not_s6,
        test_reserved_links_never_in_outputs,
        test_arp_active_tree_ports,
        test_arp_never_outputs_ingress,
        test_no_duplicate_selectors,
        test_flow_counts_and_priorities,
        test_json_uses_multiple_outputs_for_arp,
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
