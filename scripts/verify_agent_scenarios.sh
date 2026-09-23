#!/usr/bin/env bash
# Live F1–F5 verification of the LLM harness fault path.
#
# For each scenario: load it through the harness UI backend
# (agent.fault_control.load_scenario — the "Load scenario" button), observe it
# through the model's tool adapter (agent.tools.execute_tool — the exact calls
# and observations the LLM receives), reset through the UI backend, then
# re-check the healthy baseline. No model requests are sent and no API
# credits are used.
#
# Prerequisites (already running):
#   ONOS 2.7.0 + main6s8h + M3 baseline (./scripts/testbed.sh start)
#   no chat turn in progress in the harness UI
#
#   export ONOS_USER=onos
#   export ONOS_PASSWORD=rocks
#   ./scripts/verify_agent_scenarios.sh          # F1–F5 in order
#   ./scripts/verify_agent_scenarios.sh F3 F5    # selected scenarios
#
# Requires root (does not call sudo itself). Cleans up the active fault on
# exit/failure via trap.

set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
# shellcheck source=fault_verify_lib.sh
source "${ROOT}/scripts/fault_verify_lib.sh"

ONOS_API="http://127.0.0.1:8181/onos/v1"
FAIL=0
INJECTED=0
SCENARIO=F1
WORKDIR="$(mktemp -d /tmp/coms6200-agent.XXXXXX)"
CONVERGE_TIMEOUT_S="${CONVERGE_TIMEOUT_S:-30}"
DEGRADE_MAX_RATIO="${DEGRADE_MAX_RATIO:-0.25}"
# Measure real tool behaviour: no artificial harness delay.
export TOOL_DELAY_MIN_SECONDS=0 TOOL_DELAY_MAX_SECONDS=0
export WORKDIR CONVERGE_TIMEOUT_S DEGRADE_MAX_RATIO

SCENARIOS=()
if [[ "$#" -eq 0 ]]; then
  SCENARIOS=(F1 F2 F3 F4 F5)
else
  for raw in "$@"; do
    s="$(printf '%s' "${raw}" | tr '[:lower:]' '[:upper:]')"
    s="F${s#F}"
    case "${s}" in
      F1|F2|F3|F4|F5) SCENARIOS+=("${s}") ;;
      *) echo "ERROR: unknown scenario '${raw}' (catalogue v1: F1–F5)"; exit 1 ;;
    esac
  done
fi

require_root_and_onos_env
trap generic_cleanup EXIT INT TERM

wait_links() {
  local want="$1" i count
  for i in $(seq 1 "${CONVERGE_TIMEOUT_S}"); do
    count="$(directed_link_count)"
    if [[ "${count}" == "${want}" ]]; then
      echo "  directed_links=${count} after ${i}s"
      return 0
    fi
    sleep 1
  done
  echo "  directed_links=${count} (want ${want})"
  return 1
}

echo "===== PRECHECK ====="
if ! rest_get "devices" >/dev/null; then fail "ONOS REST"; exit 1; fi
pass "ONOS REST"
echo "scenarios=${SCENARIOS[*]} samples=${WORKDIR}"

for S in "${SCENARIOS[@]}"; do
  SCENARIO="${S}"
  export SCENARIO
  echo
  healthy_gate "pre-${S}" || exit 1

  if [[ "${S}" == "F2" ]]; then
    echo "===== ${S}: HEALTHY IPERF h1->h5 (agent tool) ====="
    python3 - <<'PY'
import asyncio, json, os
from agent.tools import execute_tool
r = asyncio.run(execute_tool("iperf", json.dumps({"src": "h1", "dst": "h5", "duration": 3})))
assert r.get("ok") and not r.get("invalid"), r.get("error")
mbps = float(r["data"]["mbit_per_sec"])
print(f"healthy_mbps={mbps}")
assert mbps > 5.0, mbps
open(os.path.join(os.environ["WORKDIR"], "f2_healthy_mbps"), "w").write(str(mbps))
PY
    if [[ $? -eq 0 ]]; then pass "${S}: healthy iperf captured"; else fail "${S}: healthy iperf"; exit 1; fi
  fi

  echo "===== ${S}: LOAD (agent.fault_control.load_scenario) ====="
  python3 - <<'PY'
import json, os
from agent import fault_control
sid = os.environ["SCENARIO"]
result = fault_control.load_scenario(sid)
print(json.dumps(result, sort_keys=True))
assert result["ok"] is True, result.get("error")
assert result["active"] is True and result["scenario_id"] == sid, result
assert set(result) == {"ok", "active", "scenario_id", "runnable", "error"}, sorted(result)
PY
  if [[ $? -ne 0 ]]; then fail "${S}: load through harness"; exit 1; fi
  INJECTED=1
  pass "${S}: loaded through harness"
  if [[ "${S}" == "F1" ]]; then
    if wait_links 18; then pass "${S}: ONOS directed links = 18"; else fail "${S}: ONOS did not converge to 18"; fi
  else
    sleep 2
  fi

  echo "===== ${S}: OBSERVE (agent.tools.execute_tool) ====="
  python3 - <<'PY'
import asyncio, json, os, re

from agent.tools import execute_tool
from faults.scenarios import F2
from topologies.spec import HOST_MACS

sid = os.environ["SCENARIO"]
workdir = os.environ["WORKDIR"]
seen = []
failures = []


def tool(name, **args):
    result = asyncio.run(execute_tool(name, json.dumps(args)))
    # Exactly what agent/loop.py sends back to the model.
    observation = {k: result.get(k) for k in ("ok", "data", "error")}
    seen.append({"tool": name, "arguments": args, "observation": observation})
    assert not result.get("invalid"), f"{name} rejected arguments: {result.get('error')}"
    assert result.get("ok"), f"{name} failed: {result.get('error')}"
    return result["data"]


def check(label, fn):
    try:
        detail = fn()
    except Exception as exc:  # noqa: BLE001 — report and continue to reset
        failures.append(label)
        print(f"FAIL  {sid}: {label}: {exc}")
    else:
        print(f"PASS  {sid}: {label}" + (f" ({detail})" if detail else ""))


def received(src, dst):
    return tool("ping", src=src, dst=dst, count=3)["received"]


def expect_ping(src, dst, ok):
    def run():
        got = received(src, dst)
        assert (got > 0) == ok, f"received={got}"
        return f"received={got}"
    check(f"ping {src}->{dst} {'succeeds' if ok else 'fails'}", run)


def macs(flow):
    return {c.get("type"): str(c.get("mac", "")).lower() for c in flow["selector"] if "mac" in c}


def flows(sw):
    return tool("get_flow_table", sw=sw)["flows"]


def h1_to_h5(flow):
    m = macs(flow)
    return m.get("ETH_SRC") == HOST_MACS["h1"] and m.get("ETH_DST") == HOST_MACS["h5"]


def experiment(sw):
    return [f for f in flows(sw) if f["app_id"] == "org.coms6200.experiment" and h1_to_h5(f)]


def outputs(flow):
    return [str(i.get("port")) for i in flow["treatment"] if i.get("type") == "OUTPUT"]


def iperf3_clients(port):
    hits = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            raw = open(f"/proc/{entry}/cmdline", "rb").read()
        except OSError:
            continue
        argv = [t.decode(errors="replace") for t in raw.split(b"\0") if t]
        if argv and os.path.basename(argv[0]) == "iperf3" and "-c" in argv and str(port) in argv:
            hits.append(entry)
    return hits


if sid == "F1":
    def topo():
        s = tool("get_topology")["summary"]
        assert s["physical_inter_switch_links"] == 9, s
        assert s["configured_inter_switch_links"] == 10, s
        return "observed 9 of 10 configured links"
    check("get_topology shows one missing link", topo)

    def port(sw, number):
        def run():
            rows = {p["port"]: p for p in tool("get_port_status", sw=sw)["ports"]}
            row = rows.get(number) or rows.get(str(number))
            assert row is not None and row["enabled"] is False, row
            return f"{row['name']} enabled=False"
        return run
    check("get_port_status s3 port 1 disabled", port("s3", 1))
    check("get_port_status s1 port 2 disabled", port("s1", 2))
    expect_ping("h1", "h5", False)
    expect_ping("h1", "h2", True)
    expect_ping("h3", "h5", True)

elif sid == "F2":
    def stats():
        rows = {p["port"]: p for p in tool("get_port_stats", sw="s1")["ports"]}
        row = rows.get(4) or rows.get("4")
        assert row is not None, "s1 port 4 missing"
        return f"s1:4 tx_bits_per_sec={row.get('tx_bits_per_sec')}"
    check("get_port_stats s1 returns port 4 counters", stats)

    def rtt():
        data = tool("ping", src="h1", dst="h5", count=3)
        assert data["received"] > 0, data
        return f"received={data['received']} rtt_avg_ms={data['rtt_avg_ms']}"
    check("ping h1->h5 still reachable", rtt)

    def degraded():
        healthy = float(open(os.path.join(workdir, "f2_healthy_mbps")).read())
        mbps = float(tool("iperf", src="h1", dst="h5", duration=3)["mbit_per_sec"])
        limit = float(os.environ["DEGRADE_MAX_RATIO"])
        ratio = mbps / healthy
        assert ratio <= limit, f"fault={mbps} healthy={healthy} ratio={ratio:.4f}"
        return f"fault_mbps={mbps} healthy_mbps={healthy} ratio={ratio:.4f}"
    check("iperf h1->h5 degraded", degraded)

    def background():
        hits = iperf3_clients(F2.iperf_port)
        assert hits, f"no iperf3 client on port {F2.iperf_port}; agent iperf stopped the load"
        return f"pids={hits}"
    check("background load survives agent iperf", background)

elif sid == "F3":
    expect_ping("h1", "h5", False)
    expect_ping("h2", "h5", True)
    expect_ping("h1", "h6", True)

    def drop():
        rules = [f for f in experiment("s3") if (f["priority"] or 0) >= 50000]
        assert len(rules) == 1, rules
        # ONOS reports the empty (drop) treatment as [{"type": "NOACTION"}].
        assert outputs(rules[0]) == [], rules[0]["treatment"]
        return f"priority={rules[0]['priority']} treatment={rules[0]['treatment']}"
    check("get_flow_table s3 shows h1->h5 rule with no output", drop)

elif sid == "F4":
    expect_ping("h1", "h5", False)
    expect_ping("h1", "h2", True)
    expect_ping("h3", "h5", True)

    def cycle():
        hops = []
        for sw, port in (("s3", 5), ("s4", 1), ("s1", 2)):
            rules = experiment(sw)
            assert len(rules) == 1 and outputs(rules[0]) == [str(port)], (sw, rules)
            hops.append(f"{sw}->{port} packets={rules[0]['packets']}")
        return "; ".join(hops)
    check("get_flow_table s3/s4/s1 show h1->h5 cycle", cycle)

elif sid == "F5":
    expect_ping("h1", "h5", False)
    expect_ping("h2", "h5", False)
    expect_ping("h1", "h6", True)
    expect_ping("h3", "h5", True)

    def missing():
        def to_h5(sw):
            return [
                f for f in flows(sw)
                if f["app_id"] == "org.coms6200.baseline"
                and f["priority"] == 41000
                and macs(f).get("ETH_DST") == HOST_MACS["h5"]
            ]
        assert to_h5("s3") == [], "s3 still has an h5 unicast rule"
        assert len(to_h5("s4")) == 1, "reference switch s4 lacks its h5 rule"
        return "s3 has no h5 rule; s4 has one"
    check("get_flow_table s3 lacks the h5 baseline rule", missing)


def no_labels():
    blob = json.dumps([item["observation"] for item in seen])
    assert not re.search(r"\bF[1-5]\b", blob), "scenario id in tool observation"
    for key in ("ground_truth", "scenario_id", "fault_family", "expected_correction"):
        assert key not in blob, f"{key} in tool observation"
    return f"{len(seen)} observations"
check("tool observations carry no fault labels", no_labels)

with open(os.path.join(workdir, f"observations_{sid}.json"), "w") as handle:
    json.dump(seen, handle, indent=2, sort_keys=True)
raise SystemExit(1 if failures else 0)
PY
  if [[ $? -eq 0 ]]; then pass "${S}: evidence visible through agent tools"; else fail "${S}: agent-tool observation"; fi

  echo "===== ${S}: RESET (agent.fault_control.reset_scenario) ====="
  python3 - <<'PY'
import json
from agent import fault_control
result = fault_control.reset_scenario()
print(json.dumps(result, sort_keys=True))
assert result["ok"] is True, result.get("error")
assert result["active"] is False, result
PY
  if [[ $? -ne 0 ]]; then fail "${S}: reset through harness"; exit 1; fi
  INJECTED=0
  pass "${S}: reset through harness"

  for iface in s1-eth4 s3-eth5; do
    if tc qdisc show dev "${iface}" 2>/dev/null | grep -qi tbf; then
      fail "${S}: tbf remains on ${iface}"
    fi
  done
  if ! wait_links 20; then fail "${S}: ONOS did not restore 20 directed links"; fi
  healthy_gate "post-${S}" || exit 1
done

echo
check_fwd_and_flood
python3 forwarding/baseline_forwarding.py verify || fail "baseline verify"

echo
echo "samples: ${WORKDIR}"
if [[ "${FAIL}" -eq 0 ]]; then
  echo "Agent scenario verification (${SCENARIOS[*]}): ALL CHECKS PASSED"
  exit 0
fi
echo "Agent scenario verification (${SCENARIOS[*]}): FAILED"
exit 1
