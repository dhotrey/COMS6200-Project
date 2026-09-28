"""Deterministic troubleshooting baseline.

The only inputs are the operator symptom text and TelemetryGateway observations.
This module does not import the fault injector, read fault state, or branch on
a scenario identifier.
"""

from __future__ import annotations

import re
import time
from typing import Any, Callable

MAX_TOOL_CALLS = 14
TIMEOUT_SEC = 300.0
FAMILIES = (
    "link_failure",
    "congestion",
    "policy_drop",
    "forwarding_loop",
    "missing_flow",
)

_HOST = re.compile(r"\bh([1-8])\b", re.IGNORECASE)
_SLOW = re.compile(r"\b(slow|throughput|transfer|transfers)\b", re.IGNORECASE)
_REACH = re.compile(r"\breach\b", re.IGNORECASE)
_PORT_WORD = re.compile(r"\b(tcp|udp)\b[^0-9]{0,12}(\d{1,5})\b", re.IGNORECASE)

# Observed throughput below this, with a fast control path or a queue signal,
# is treated as a capacity constraint. These are measurement thresholds, not
# configured shaper parameters.
_SLOW_BPS = 100_000_000.0
_FAST_BPS = 1_000_000_000.0
_HIGH_RTT_MS = 50.0


class BudgetExceeded(Exception):
    """The 14-call diagnostic budget was consumed."""


class DiagnosisTimeout(Exception):
    """The 300-second diagnostic budget was consumed."""


class _Symptom:
    def __init__(self, kind: str, sources: list[str], dest: str) -> None:
        self.kind = kind
        self.sources = sources
        self.dest = dest


def parse_symptom(prompt: str) -> _Symptom | None:
    """Read endpoints and complaint type from the user sentence.

    This is the same information the user gives the model. It does not map a
    whole sentence onto a stored answer.
    """
    text = prompt or ""
    if _SLOW.search(text):
        hosts = _unique_hosts(text)
        if len(hosts) < 2:
            return None
        return _Symptom("performance", [hosts[0]], hosts[1])
    reach = _REACH.search(text)
    if reach:
        before = _unique_hosts(text[: reach.start()])
        after = _unique_hosts(text[reach.end() :])
        if before and after:
            return _Symptom("reachability", before, after[0])
    hosts = _unique_hosts(text)
    if len(hosts) < 2:
        return None
    return _Symptom("unspecified", [hosts[0]], hosts[1])


def _unique_hosts(text: str) -> list[str]:
    found: list[str] = []
    for match in _HOST.finditer(text):
        name = f"h{match.group(1)}"
        if name not in found:
            found.append(name)
    return found


class _Session:
    def __init__(
        self,
        gateway: Any,
        max_calls: int,
        timeout_sec: float,
        clock: Callable[[], float],
    ) -> None:
        self.gateway = gateway
        self.max_calls = max_calls
        self.clock = clock
        self.started = clock()
        self.deadline = self.started + timeout_sec
        self.trace: list[dict[str, Any]] = []
        self.evidence: list[str] = []
        self.family: str | None = None
        self.location: str | None = None
        self.text = "No conclusive fault family from the completed observations."
        self.error: str | None = None
        self._flows: dict[str, dict[str, Any]] = {}

    def call(self, name: str, **kwargs: Any) -> dict[str, Any]:
        if self.clock() >= self.deadline:
            raise DiagnosisTimeout()
        if len(self.trace) >= self.max_calls:
            raise BudgetExceeded()
        started = self.clock()
        try:
            result = getattr(self.gateway, name)(**kwargs)
        except Exception as exc:  # noqa: BLE001 — one failed tool must not abort the process
            result = {"ok": False, "error": {"message": type(exc).__name__}}
        if not isinstance(result, dict):
            result = {"ok": False, "error": {"message": "telemetry result was not an object"}}
        self.trace.append(
            {
                "sequence": len(self.trace) + 1,
                "tool": name,
                "arguments": kwargs,
                "ok": bool(result.get("ok")),
                "elapsed_sec": round(self.clock() - started, 3),
            }
        )
        return result

    def data(self, name: str, **kwargs: Any) -> dict[str, Any] | None:
        result = self.call(name, **kwargs)
        if not result.get("ok") or not isinstance(result.get("data"), dict):
            self.evidence.append(f"{name} failed")
            return None
        return result["data"]

    def flows(self, switch: str) -> list[dict[str, Any]] | None:
        if switch not in self._flows:
            payload = self.data("get_flow_table", sw=switch)
            self._flows[switch] = payload or {}
        if not self._flows[switch]:
            return None
        rows = self._flows[switch].get("flows")
        return rows if isinstance(rows, list) else None

    def conclude(self, family: str | None, location: str | None, text: str) -> None:
        if family is not None and family not in FAMILIES:
            raise ValueError(f"unknown family {family}")
        self.family = family
        self.location = location
        self.text = text

    def result(self) -> dict[str, Any]:
        return {
            "diagnosis_family": self.family,
            "diagnosis_location": self.location,
            "diagnosis_text": self.text,
            "evidence": list(self.evidence),
            "tool_calls": list(self.trace),
            "tool_call_count": len(self.trace),
            "elapsed_sec": round(self.clock() - self.started, 3),
            "error": self.error,
        }


def diagnose(
    prompt: str,
    gateway: Any,
    *,
    max_calls: int = MAX_TOOL_CALLS,
    timeout_sec: float = TIMEOUT_SEC,
    clock: Callable[[], float] | None = None,
) -> dict[str, Any]:
    """Return one structured diagnosis. Tool calls stop at max_calls or timeout_sec."""
    session = _Session(gateway, max_calls, timeout_sec, clock or time.perf_counter)
    try:
        _investigate(session, prompt)
    except BudgetExceeded:
        session.error = "tool budget reached"
        if session.family is None:
            session.text = "Tool budget was exhausted before a single conclusion."
    except DiagnosisTimeout:
        session.error = "diagnosis timeout"
        if session.family is None:
            session.text = "Diagnosis time was exhausted before a single conclusion."
    return session.result()


def _investigate(session: _Session, prompt: str) -> None:
    symptom = parse_symptom(prompt)
    if symptom is None:
        session.conclude(None, None, "The symptom does not name two project hosts.")
        return
    topo = session.data("get_topology")
    if topo is None:
        session.error = "telemetry failed: get_topology"
        session.conclude(None, None, "Topology could not be read.")
        return
    _maybe_nmap(session, prompt, symptom)
    if symptom.kind == "performance":
        _performance(session, symptom, topo)
        return
    failed = _failed_sources(session, symptom)
    if symptom.kind == "unspecified" and not failed:
        _performance(session, symptom, topo)
        return
    if not failed:
        session.conclude(
            None,
            None,
            f"{symptom.sources[0]} can still reach {symptom.dest}. No reachability fault was measured.",
        )
        return
    _reachability(session, symptom, topo, failed)


def _maybe_nmap(session: _Session, prompt: str, symptom: _Symptom) -> None:
    match = _PORT_WORD.search(prompt or "")
    if not match:
        return
    proto = match.group(1).lower()
    port = int(match.group(2))
    if port > 65535:
        return
    payload = session.data("nmap", src=symptom.sources[0], dst=symptom.dest, proto=proto, port=port)
    if payload is not None:
        session.evidence.append(
            f"nmap {proto}/{port} {symptom.sources[0]}->{symptom.dest} state {payload.get('state')}"
        )


def _performance(session: _Session, symptom: _Symptom, topo: dict[str, Any]) -> None:
    src, dst = symptom.sources[0], symptom.dest
    ping = session.data("ping", src=src, dst=dst, count=2)
    if ping is None:
        session.error = session.error or "telemetry failed: ping"
        return
    if _ping_failed(ping):
        _reachability(session, symptom, topo, [src])
        return
    rtt = ping.get("rtt_avg_ms")
    symptom_rate = _iperf_bps(session, src, dst)
    control = _control_pair(topo, src, dst)
    control_rate = None
    if control is not None:
        control_rate = _iperf_bps(session, control[0], control[1])
    slow = symptom_rate is not None and symptom_rate < _SLOW_BPS
    fast_control = control_rate is not None and control_rate > _FAST_BPS
    high_rtt = isinstance(rtt, (int, float)) and rtt >= _HIGH_RTT_MS
    session.evidence.append(
        f"iperf {src}->{dst} sender_bps={symptom_rate} control_bps={control_rate} rtt_ms={rtt}"
    )
    if not slow and not high_rtt:
        session.conclude(
            None,
            None,
            f"{src} to {dst} did not show a measured throughput or delay constraint.",
        )
        return
    path = _shortest(topo.get("configured_inter_switch_links") or [], _switch_of(topo, src), _switch_of(topo, dst))
    best_port = None
    best_score = 0.0
    switches = _path_switches(path, _switch_of(topo, src))
    for index, switch in enumerate(switches[:-1] if len(switches) > 1 else []):
        link = path[index]
        port = _end_port(link, switch)
        metrics = session.data("get_link_metrics", sw=switch, port=port)
        if metrics is None:
            continue
        score = _queue_score(metrics)
        session.evidence.append(
            f"link metrics {switch} port {port} backlog={metrics.get('queue_backlog_bytes')} "
            f"overlimits={metrics.get('queue_overlimits_delta')}"
        )
        if score > best_score:
            best_score = score
            best_port = f"{switch} port {port}"
    if best_port is not None and (slow or high_rtt):
        session.conclude(
            "congestion",
            best_port,
            f"Congestion on {best_port}. The path is up and that egress shows queue buildup.",
        )
        return
    if slow and fast_control:
        session.conclude(
            "congestion",
            None,
            f"Congestion toward {dst} from {src}, but no single egress queue stood out.",
        )
        return
    session.conclude(None, None, f"No single constrained egress was measured for {src} to {dst}.")


def _reachability(
    session: _Session,
    symptom: _Symptom,
    topo: dict[str, Any],
    failed: list[str],
) -> None:
    src = failed[0]
    dst = symptom.dest
    _control_pings(session, topo, src, dst, set(failed))
    configured = topo.get("configured_inter_switch_links") or []
    observed = topo.get("links") or []
    src_sw = _switch_of(topo, src)
    dst_sw = _switch_of(topo, dst)
    path = _shortest(configured, src_sw, dst_sw)
    down = _first_down_hop(session, path, observed, src_sw)
    if down is not None:
        link, near, port, enabled = down
        session.evidence.append(f"down hop at {near} port {port} enabled={enabled}")
        other = _other_end(link, near)
        location = f"{near} port {port}"
        if other is not None:
            location = f"{near} port {port} to {other[0]} port {other[1]}"
        session.conclude(
            "link_failure",
            location,
            f"Link failure on {location}. The hop is missing, not ACTIVE, or the port is disabled.",
        )
        return
    cycle_or_rule = _walk_forwarding(session, topo, src, dst)
    if cycle_or_rule is not None:
        return
    session.conclude(
        None,
        None,
        f"{src} cannot reach {dst}, and neither a down link nor a flow-table cause was isolated.",
    )



def _first_down_hop(session, path, observed, src_sw):
    """A hop is down when ONOS no longer lists it as ACTIVE or its egress port is disabled.

    Flow rules can still point across a disabled port, so port state is checked
    before any flow walk.
    """
    cache: dict[str, dict | None] = {}
    switches = _path_switches(path, src_sw)
    for index, switch in enumerate(switches[:-1]):
        link = path[index]
        state = _observed_state(observed, link)
        port = _end_port(link, switch)
        enabled = _cached_enabled(session, cache, switch, port)
        if state != "ACTIVE" or enabled is False:
            return link, switch, port, enabled
    return None


def _observed_state(observed, link):
    key = _link_key(link)
    for item in observed:
        try:
            if _link_key(item) == key:
                return item.get("state") or "ACTIVE"
        except (KeyError, TypeError, ValueError):
            continue
    return None


def _cached_enabled(session, cache, switch, port):
    if switch not in cache:
        cache[switch] = session.data("get_port_status", sw=switch)
    return _port_enabled(cache[switch], port)


def _failed_sources(session: _Session, symptom: _Symptom) -> list[str]:
    failed: list[str] = []
    for src in symptom.sources:
        payload = session.data("ping", src=src, dst=symptom.dest, count=2)
        if payload is None:
            session.evidence.append(f"ping {src}->{symptom.dest} failed to run")
            continue
        if _ping_failed(payload):
            failed.append(src)
            session.evidence.append(f"ping {src}->{symptom.dest} loss")
        else:
            session.evidence.append(
                f"ping {src}->{symptom.dest} up rtt_ms={payload.get('rtt_avg_ms')}"
            )
    return failed


def _control_pings(
    session: _Session,
    topo: dict[str, Any],
    src: str,
    dst: str,
    failed: set[str],
) -> None:
    src_sw = _switch_of(topo, src)
    local = _host_on(topo, src_sw, exclude=failed | {src, dst})
    if local is not None:
        payload = session.data("ping", src=src, dst=local, count=2)
        session.evidence.append(f"control ping {src}->{local} up={payload is not None and not _ping_failed(payload)}")
    remote = _host_off(topo, src_sw, exclude=failed | {src, dst})
    if remote is not None and remote != dst:
        payload = session.data("ping", src=remote, dst=dst, count=2)
        session.evidence.append(
            f"control ping {remote}->{dst} up={payload is not None and not _ping_failed(payload)}"
        )


def _walk_forwarding(session: _Session, topo: dict[str, Any], src: str, dst: str) -> bool | None:
    src_mac = _mac(topo, src)
    dst_mac = _mac(topo, dst)
    if not src_mac or not dst_mac:
        return None
    links = list(topo.get("links") or []) + list(topo.get("configured_inter_switch_links") or [])
    current = _switch_of(topo, src)
    if current is None:
        return None
    visited: list[str] = []
    while current is not None and len(visited) <= 6:
        if current in visited:
            cycle = visited[visited.index(current) :] + [current]
            location = f"{' -> '.join(cycle)} for {src} to {dst}"
            session.conclude(
                "forwarding_loop",
                location,
                f"Forwarding loop {location}.",
            )
            return True
        visited.append(current)
        rows = session.flows(current)
        if rows is None:
            session.error = session.error or f"telemetry failed: get_flow_table {current}"
            return True
        rule = _best_rule(rows, src_mac, dst_mac)
        if rule is None:
            if _destination_forwarded_elsewhere(session, topo, current, dst_mac):
                session.conclude(
                    "missing_flow",
                    f"missing forwarding rule for {dst} on {current}",
                    f"Missing forwarding rule for {dst} on {current}.",
                )
            else:
                session.conclude(
                    "missing_flow",
                    f"missing forwarding rule for {dst} on {current}",
                    f"Missing forwarding rule for {dst} on {current}. No output rule for that destination was found there.",
                )
            return True
        ports = _output_ports(rule)
        if not ports:
            session.conclude(
                "policy_drop",
                f"drop rule on {current} for {src} toward {dst}",
                f"Policy drop on {current} for {src} toward {dst}. The highest matching rule has no output.",
            )
            return True
        peer = _peer_switch(links, current, ports[0])
        if peer is None:
            session.conclude(
                None,
                None,
                f"Forwarding for {src} to {dst} leaves {current} toward a host port, but delivery still fails.",
            )
            return True
        current = peer
    return None


def _destination_forwarded_elsewhere(
    session: _Session,
    topo: dict[str, Any],
    origin: str,
    dst_mac: str,
) -> bool:
    """One extra table: the switch that attaches this destination MAC."""
    dest_switch = None
    for row in topo.get("host_attachments") or []:
        mac = str(row.get("mac") or "").lower()
        if mac == dst_mac.lower() and row.get("role", "primary") == "primary":
            dest_switch = row.get("switch")
            break
    if not dest_switch or dest_switch == origin:
        return False
    rows = session.flows(str(dest_switch))
    return bool(rows and _rule_for_destination(rows, dst_mac))


def _best_rule(rows: list[dict[str, Any]], src_mac: str, dst_mac: str) -> dict[str, Any] | None:
    ranked = [row for row in rows if _matches(row, src_mac, dst_mac)]
    if not ranked:
        return None
    ranked.sort(key=lambda row: (-(row.get("priority") or 0), str(row.get("id") or "")))
    return ranked[0]


def _rule_for_destination(rows: list[dict[str, Any]], dst_mac: str) -> dict[str, Any] | None:
    found = []
    for row in rows:
        crit = _criteria(row)
        if crit.get("eth_dst") == dst_mac.lower() and _output_ports(row):
            found.append(row)
    if not found:
        return None
    found.sort(key=lambda row: -(row.get("priority") or 0))
    return found[0]


def _matches(row: dict[str, Any], src_mac: str, dst_mac: str) -> bool:
    crit = _criteria(row)
    if crit.get("eth_dst") != dst_mac.lower():
        return False
    eth_src = crit.get("eth_src")
    return eth_src is None or eth_src == src_mac.lower()


def _criteria(row: dict[str, Any]) -> dict[str, str]:
    found: dict[str, str] = {}
    for item in row.get("selector") or []:
        kind = str(item.get("type") or "")
        if kind == "ETH_DST" and item.get("mac"):
            found["eth_dst"] = str(item["mac"]).lower()
        elif kind == "ETH_SRC" and item.get("mac"):
            found["eth_src"] = str(item["mac"]).lower()
    return found


def _output_ports(row: dict[str, Any]) -> list[int]:
    ports: list[int] = []
    for item in row.get("treatment") or []:
        if str(item.get("type") or "").upper() != "OUTPUT":
            continue
        port = item.get("port")
        if isinstance(port, int) and not isinstance(port, bool):
            ports.append(port)
        elif isinstance(port, str) and port.isdigit():
            ports.append(int(port))
    return ports


def _peer_switch(links: list[dict[str, Any]], switch: str, port: int) -> str | None:
    for link in links:
        if _end_port(link, switch) == port and _has_end(link, switch):
            other = _other_end(link, switch)
            if other is not None:
                return other[0]
    return None


def _iperf_bps(session: _Session, src: str, dst: str) -> float | None:
    payload = session.data("iperf", src=src, dst=dst, duration=2)
    if payload is None:
        return None
    if payload.get("sender_bits_per_sec") is not None:
        return float(payload["sender_bits_per_sec"])
    if payload.get("mbit_per_sec") is not None:
        return float(payload["mbit_per_sec"]) * 1_000_000.0
    return None


def _ping_failed(payload: dict[str, Any]) -> bool:
    received = payload.get("received")
    loss = payload.get("loss_pct")
    if received == 0:
        return True
    return isinstance(loss, (int, float)) and loss >= 100.0


def _queue_score(metrics: dict[str, Any]) -> float:
    score = 0.0
    backlog = metrics.get("queue_backlog_bytes")
    over = metrics.get("queue_overlimits_delta")
    if isinstance(backlog, (int, float)) and backlog >= 1000:
        score += float(backlog)
    if isinstance(over, (int, float)) and over >= 5:
        score += float(over) * 1000.0
    return score


def _switch_of(topo: dict[str, Any], host: str) -> str | None:
    for row in topo.get("host_attachments") or []:
        if row.get("host") == host and row.get("role", "primary") == "primary":
            return str(row.get("switch"))
    return None


def _mac(topo: dict[str, Any], host: str) -> str | None:
    for row in topo.get("host_attachments") or []:
        if row.get("host") == host and row.get("role", "primary") == "primary" and row.get("mac"):
            return str(row["mac"]).lower()
    return None


def _host_on(topo: dict[str, Any], switch: str | None, exclude: set[str]) -> str | None:
    if switch is None:
        return None
    for row in topo.get("host_attachments") or []:
        host = row.get("host")
        if row.get("switch") == switch and row.get("role", "primary") == "primary" and host not in exclude:
            return str(host)
    return None


def _host_off(topo: dict[str, Any], switch: str | None, exclude: set[str]) -> str | None:
    for row in topo.get("host_attachments") or []:
        host = row.get("host")
        if row.get("switch") != switch and row.get("role", "primary") == "primary" and host not in exclude:
            return str(host)
    return None


def _control_pair(topo: dict[str, Any], src: str, dst: str) -> tuple[str, str] | None:
    src_sw = _switch_of(topo, src)
    other = _host_on(topo, src_sw, exclude={src, dst})
    if other is not None:
        return src, other
    return None


def _link_key(link: dict[str, Any]) -> tuple[tuple[str, int], tuple[str, int]]:
    ends = (
        (str(link["a"]["switch"]), int(link["a"]["port"])),
        (str(link["b"]["switch"]), int(link["b"]["port"])),
    )
    return tuple(sorted(ends))


def _link_keys(links: list[dict[str, Any]]) -> set[tuple[tuple[str, int], tuple[str, int]]]:
    return {_link_key(link) for link in links if link.get("a") and link.get("b")}


def _has_end(link: dict[str, Any], switch: str) -> bool:
    return link["a"]["switch"] == switch or link["b"]["switch"] == switch


def _end_port(link: dict[str, Any], switch: str) -> int:
    if link["a"]["switch"] == switch:
        return int(link["a"]["port"])
    return int(link["b"]["port"])


def _other_end(link: dict[str, Any], switch: str) -> tuple[str, int] | None:
    if link["a"]["switch"] == switch:
        return str(link["b"]["switch"]), int(link["b"]["port"])
    if link["b"]["switch"] == switch:
        return str(link["a"]["switch"]), int(link["a"]["port"])
    return None


def _shortest(links: list[dict[str, Any]], start: str | None, goal: str | None) -> list[dict[str, Any]]:
    if not start or not goal or start == goal:
        return []
    graph: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for link in links:
        if not link.get("a") or not link.get("b"):
            continue
        left, right = str(link["a"]["switch"]), str(link["b"]["switch"])
        graph.setdefault(left, []).append((right, link))
        graph.setdefault(right, []).append((left, link))
    parent: dict[str, str | None] = {start: None}
    via: dict[str, dict[str, Any]] = {}
    queue = [start]
    while queue:
        node = queue.pop(0)
        if node == goal:
            break
        for nxt, link in graph.get(node, []):
            if nxt not in parent:
                parent[nxt] = node
                via[nxt] = link
                queue.append(nxt)
    if goal not in parent:
        return []
    path: list[dict[str, Any]] = []
    node = goal
    while parent[node] is not None:
        path.append(via[node])
        node = parent[node]
    path.reverse()
    return path


def _path_switches(path: list[dict[str, Any]], start: str | None) -> list[str]:
    if not start:
        return []
    switches = [start]
    for link in path:
        other = _other_end(link, switches[-1])
        if other is None:
            break
        switches.append(other[0])
    return switches


def _port_enabled(status: dict[str, Any] | None, port: int) -> bool | None:
    if not status:
        return None
    for row in status.get("ports") or []:
        if row.get("port") == port:
            enabled = row.get("enabled")
            return enabled if isinstance(enabled, bool) else None
    return None
