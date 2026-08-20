"""Static checks for the main topology and provisional controller source.

Does not start Mininet or ONOS. Runtime evidence must come from the Ubuntu
server after this code is pulled.
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOPO = ROOT / "topologies" / "main_topology.py"
CTRL = ROOT / "controllers" / "main_controller.py"

INTER_SWITCH = {
    ("s1", "s2", 1, 1),
    ("s1", "s3", 2, 1),
    ("s1", "s4", 3, 1),
    ("s1", "s5", 4, 1),
    ("s1", "s6", 5, 1),
    ("s2", "s3", 2, 2),
    ("s2", "s4", 3, 2),
    ("s2", "s5", 4, 2),
    ("s2", "s6", 5, 2),
    ("s3", "s4", 5, 5),
}

HOST_SWITCH = {
    ("s3", "h1", 3, 0),
    ("s3", "h2", 4, 0),
    ("s4", "h3", 3, 0),
    ("s4", "h4", 4, 0),
    ("s5", "h5", 3, 0),
    ("s5", "h6", 4, 0),
    ("s6", "h7", 3, 0),
    ("s6", "h8", 4, 0),
    ("s6", "h6", 5, 1),
}


def _source(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _call_names(tree: ast.AST, method: str) -> list[ast.Call]:
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == method:
                calls.append(node)
    return calls


def _kw(call: ast.Call, name: str) -> ast.AST | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _const_str(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _const_int(node: ast.AST | None) -> int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    return None


def _name(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    return _const_str(node)


def _parsed_links(tree: ast.AST) -> list[tuple[str, str, int | None, int | None]]:
    links: list[tuple[str, str, int | None, int | None]] = []
    for call in _call_names(tree, "addLink"):
        if len(call.args) < 2:
            continue
        a = _name(call.args[0])
        b = _name(call.args[1])
        assert a is not None and b is not None, "addLink arguments must be names"
        links.append((a, b, _const_int(_kw(call, "port1")), _const_int(_kw(call, "port2"))))
    return links


def test_topology_counts() -> None:
    tree = ast.parse(_source(TOPO))
    switches = _call_names(tree, "addSwitch")
    hosts = _call_names(tree, "addHost")
    links = _parsed_links(tree)
    assert len(switches) == 6, f"expected 6 switches, got {len(switches)}"
    assert len(hosts) == 8, f"expected 8 hosts, got {len(hosts)}"
    assert len(links) == 19, f"expected 19 links, got {len(links)}"

    inter = [link for link in links if link[0].startswith("s") and link[1].startswith("s")]
    host = [link for link in links if link[0].startswith("s") and link[1].startswith("h")]
    assert len(inter) == 10, f"expected 10 inter-switch links, got {len(inter)}"
    assert len(host) == 9, f"expected 9 host-switch links, got {len(host)}"


def test_topology_identities() -> None:
    tree = ast.parse(_source(TOPO))
    for call in _call_names(tree, "addSwitch"):
        dpid = _const_str(_kw(call, "dpid"))
        protocols = _const_str(_kw(call, "protocols"))
        fail_mode = _const_str(_kw(call, "failMode"))
        name = _const_str(call.args[0] if call.args else None)
        assert dpid is not None and re.fullmatch(r"000000000000000[1-6]", dpid), (
            f"{name} dpid={dpid}"
        )
        if protocols is not None:
            assert protocols == "OpenFlow13", f"{name} protocols={protocols}"
        if fail_mode is not None:
            assert fail_mode == "secure", f"{name} failMode={fail_mode}"

    source = _source(TOPO)
    assert "protocols" in source and "OpenFlow13" in source
    assert "failMode" in source and "secure" in source
    assert 'topos = {"main6s8h"' in source or "topos = {'main6s8h'" in source

    for idx in range(1, 9):
        assert f"10.0.0.{idx}/24" in source
        assert f"00:00:00:00:00:0{idx}" in source


def test_explicit_port_map() -> None:
    tree = ast.parse(_source(TOPO))
    links = {(a, b, p1, p2) for a, b, p1, p2 in _parsed_links(tree)}
    missing_inter = INTER_SWITCH - links
    missing_host = HOST_SWITCH - links
    assert not missing_inter, f"missing inter-switch links: {sorted(missing_inter)}"
    assert not missing_host, f"missing host-switch links: {sorted(missing_host)}"
    extra = links - INTER_SWITCH - HOST_SWITCH
    assert not extra, f"unexpected links: {sorted(extra)}"


def test_enhancement_ports() -> None:
    tree = ast.parse(_source(TOPO))
    links = _parsed_links(tree)
    assert ("s3", "s4", 5, 5) in links, "missing s3:5 <-> s4:5 access-edge test link"
    assert ("s6", "h6", 5, 1) in links, "missing s6:5 <-> h6 secondary interface"
    assert ("s5", "h6", 4, 0) in links, "h6 primary attachment to s5:4 must remain"

    source = _source(TOPO)
    assert 'intfName2="h6-eth0"' in source or "intfName2='h6-eth0'" in source
    assert 'intfName2="h6-eth1"' in source or "intfName2='h6-eth1'" in source
    assert "00:00:00:00:06:02" in source


def test_controller_baseline_constants() -> None:
    source = _source(CTRL)
    assert "ofproto_v1_3.OFP_VERSION" in source
    assert "OFP_VERSIONS" in source
    assert "BASELINE_PRIORITY = 100" in source
    assert "BASELINE_COOKIE = 0x1000" in source
    assert "ofproto.OFPP_NORMAL" not in source
    assert "ofproto.OFPP_FLOOD" not in source
    assert "simple_switch_13" not in source


def main() -> int:
    checks = (
        test_topology_counts,
        test_topology_identities,
        test_explicit_port_map,
        test_enhancement_ports,
        test_controller_baseline_constants,
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
