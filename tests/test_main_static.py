"""Static checks for the main topology and controller source.

Does not start Mininet or Ryu. Runtime evidence must come from the Ubuntu
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


def test_topology_counts() -> None:
    tree = ast.parse(_source(TOPO))
    switches = _call_names(tree, "addSwitch")
    hosts = _call_names(tree, "addHost")
    links = _call_names(tree, "addLink")
    assert len(switches) == 6, f"expected 6 switches, got {len(switches)}"
    assert len(hosts) == 8, f"expected 8 hosts, got {len(hosts)}"
    assert len(links) == 17, f"expected 17 links, got {len(links)}"


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
        # protocols/failMode may be passed via SWITCH_OPTS unpacking
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
    source = _source(TOPO)
    expected = [
        "port1=1, port2=1",  # s1-s2
        "port1=2, port2=1",  # s1-s3
        "port1=3, port2=1",  # s1-s4
        "port1=4, port2=1",  # s1-s5
        "port1=5, port2=1",  # s1-s6
        "port1=2, port2=2",  # s2-s3
        "port1=3, port2=2",  # s2-s4
        "port1=4, port2=2",  # s2-s5
        "port1=5, port2=2",  # s2-s6
    ]
    for fragment in expected:
        assert fragment in source, f"missing link ports: {fragment}"


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
