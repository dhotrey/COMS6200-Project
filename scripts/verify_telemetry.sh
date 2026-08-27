#!/usr/bin/env bash
# Live M4 telemetry verification against ONOS 2.7.0 + main6s8h + M3 baseline.
#
# Prerequisites (already running):
#   - ONOS 2.7.0 on 127.0.0.1:8181 / :6653
#   - sudo mn --custom topologies/main_topology.py --topo main6s8h ...
#   - python3 forwarding/baseline_forwarding.py install
#
# Credentials (not printed). Reference lab REST/GUI: onos / rocks
#   export ONOS_USER=onos
#   export ONOS_PASSWORD=rocks
#
# ONOS REST itself does not need root. This script also inspects OVS and
# enters Mininet host namespaces (ping/iperf via mnexec), which typically
# do. It re-executes with sudo only when OVS is not usable as the current user.
#
#   ./scripts/verify_telemetry.sh
#   # or, if OVS/mnexec require privilege:
#   sudo --preserve-env=ONOS_USER,ONOS_PASSWORD,ONOS_URL,PATH ./scripts/verify_telemetry.sh
#
# This script does not inject faults and does not modify flows or links.

set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"

if [[ "${EUID}" -ne 0 ]]; then
  if ovs-vsctl show >/dev/null 2>&1; then
    echo "OVS is usable without sudo; continuing as $(whoami)."
    echo "ping/iperf still need privilege to enter Mininet namespaces if mnexec is denied."
  else
    echo "Re-executing with sudo so OVS inspection and Mininet host namespaces work."
    echo "(This is not a Docker requirement.)"
    exec sudo --preserve-env=ONOS_USER,ONOS_PASSWORD,ONOS_URL,PATH,PYTHONPATH "${ROOT}/scripts/verify_telemetry.sh" "$@"
  fi
fi

export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

ONOS_USER="${ONOS_USER:-}"
ONOS_PASSWORD="${ONOS_PASSWORD:-}"
ONOS_HOST="${ONOS_HOST:-127.0.0.1}"
ONOS_REST_PORT="${ONOS_REST_PORT:-8181}"
ONOS_API="http://${ONOS_HOST}:${ONOS_REST_PORT}/onos/v1"
FAIL=0
WORKDIR="$(mktemp -d /tmp/coms6200-telemetry.XXXXXX)"

pass() { echo "PASS  $*"; }
fail() { echo "FAIL  $*"; FAIL=1; }

if [[ -z "${ONOS_USER}" || -z "${ONOS_PASSWORD}" ]]; then
  echo "ERROR: ONOS_USER and ONOS_PASSWORD must be set (values are not printed)."
  echo "Example: export ONOS_USER=onos; export ONOS_PASSWORD=rocks"
  exit 1
fi

CLI=(python3 -m telemetry.cli)

rest_get() {
  curl -sS -f -u "${ONOS_USER}:${ONOS_PASSWORD}" "${ONOS_API}/$1"
}

echo "===== 1. ONOS reachable ====="
if rest_get "devices" >/dev/null; then
  pass "ONOS REST /devices"
else
  fail "ONOS REST /devices unreachable or unauthorized"
  echo "Aborting; start ONOS and set REST credentials."
  exit 1
fi

echo
echo "===== 2. main6s8h bridges present ====="
for sw in s1 s2 s3 s4 s5 s6; do
  if ovs-vsctl br-exists "${sw}"; then
    pass "bridge ${sw}"
  else
    fail "bridge ${sw} missing (is main6s8h running?)"
  fi
done
if [[ "${FAIL}" -ne 0 ]]; then
  echo "Aborting; launch the main topology first."
  exit 1
fi

echo
echo "===== 3. M3 baseline flows ====="
BEFORE_JSON="${WORKDIR}/flows_before.json"
if ! rest_get "flows" >"${BEFORE_JSON}"; then
  fail "could not read /flows"
  exit 1
fi
python3 - "${BEFORE_JSON}" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1]))
flows = payload.get("flows") or []
baseline = [f for f in flows if str(f.get("appId")) == "org.coms6200.baseline"]
added = [f for f in baseline if f.get("state") == "ADDED"]
print(f"baseline_added={len(added)} total_flows={len(flows)}")
raise SystemExit(0 if len(added) == 56 else 1)
PY
if [[ $? -eq 0 ]]; then
  pass "56 baseline ADDED flows before telemetry"
else
  fail "expected 56 ADDED org.coms6200.baseline flows before telemetry"
  echo "Run: python3 forwarding/baseline_forwarding.py install"
  exit 1
fi

echo
echo "===== 4-5. get_topology ====="
"${CLI[@]}" get-topology >"${WORKDIR}/get_topology.json"
python3 - "${WORKDIR}/get_topology.json" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
assert doc.get("ok") is True, doc.get("error")
data = doc["data"]
summary = data["summary"]
checks = {
    "switches": summary.get("switches") == 6,
    "observed_switches": summary.get("observed_switches") == 6,
    "physical_inter_switch_links": summary.get("physical_inter_switch_links") == 10,
    "configured_host_attachments": summary.get("configured_host_attachments") == 9,
    "logical_hosts": summary.get("logical_hosts") == 8,
    "total_physical_links": summary.get("total_physical_links") == 19,
    "onos_host_discovery": summary.get("onos_host_discovery") == "not_used",
}
h6 = [row for row in data["host_attachments"] if row["host"] == "h6"]
roles = {row["role"] for row in h6}
checks["h6_primary"] = any(row["role"] == "primary" and row["switch"] == "s5" for row in h6)
checks["h6_secondary"] = any(row["role"] == "secondary" and row["switch"] == "s6" and row["ipv4"] is None for row in h6)
failed = [name for name, ok in checks.items() if not ok]
print(json.dumps(summary, indent=2))
print("h6_roles=" + ",".join(sorted(roles)))
raise SystemExit(0 if not failed else 1)
PY
if [[ $? -eq 0 ]]; then
  pass "get_topology counts and h6 attachments"
else
  fail "get_topology did not match healthy main6s8h"
fi

echo
echo "===== 6. get_port_status(s3) ====="
"${CLI[@]}" get-port-status --switch s3 >"${WORKDIR}/get_port_status_s3.json"
python3 - "${WORKDIR}/get_port_status_s3.json" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
assert doc.get("ok") is True, doc.get("error")
ports = doc["data"]["ports"]
assert ports, "no ports"
assert all("enabled" in p and "port" in p for p in ports)
print(f"port_count={len(ports)}")
raise SystemExit(0)
PY
if [[ $? -eq 0 ]]; then
  pass "get_port_status s3"
else
  fail "get_port_status s3"
fi

echo
echo "===== 7. get_port_stats(s3) ====="
"${CLI[@]}" get-port-stats --switch s3 >"${WORKDIR}/get_port_stats_s3.json"
python3 - "${WORKDIR}/get_port_stats_s3.json" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
assert doc.get("ok") is True, doc.get("error")
data = doc["data"]
assert data.get("utilization_note")
assert all(p.get("utilization_pct") is None for p in data["ports"])
print(f"port_count={len(data['ports'])} rate_method={data.get('rate_method')}")
raise SystemExit(0)
PY
if [[ $? -eq 0 ]]; then
  pass "get_port_stats s3"
else
  fail "get_port_stats s3"
fi

echo
echo "===== 8. get_flow_table(s3) ====="
"${CLI[@]}" get-flow-table --switch s3 >"${WORKDIR}/get_flow_table_s3.json"
python3 - "${WORKDIR}/get_flow_table_s3.json" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
assert doc.get("ok") is True, doc.get("error")
flows = doc["data"]["flows"]
assert flows, "no flows on s3"
prios = [row.get("priority") or 0 for row in flows]
assert prios == sorted(prios, reverse=True)
print(f"flow_count={len(flows)} first_priority={flows[0].get('priority')}")
raise SystemExit(0)
PY
if [[ $? -eq 0 ]]; then
  pass "get_flow_table s3"
else
  fail "get_flow_table s3"
fi

echo
echo "===== 9-10. ping(h1,h5) ====="
"${CLI[@]}" ping --src h1 --dst h5 --count 3 >"${WORKDIR}/ping_h1_h5.json"
python3 - "${WORKDIR}/ping_h1_h5.json" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
assert doc.get("ok") is True, doc.get("error")
data = doc["data"]
assert data["received"] > 0, data
assert data["loss_pct"] < 100, data
print(json.dumps({k: data[k] for k in ("src","dst","sent","received","loss_pct","rtt_avg_ms")}, indent=2))
raise SystemExit(0)
PY
if [[ $? -eq 0 ]]; then
  pass "ping h1->h5 received > 0"
else
  fail "ping h1->h5"
fi

echo
echo "===== 11-12. iperf(h1,h5) ====="
IPERF_BEFORE="$(pgrep -af '[i]perf3' || true)"
"${CLI[@]}" iperf --src h1 --dst h5 --duration 2 >"${WORKDIR}/iperf_h1_h5.json"
python3 - "${WORKDIR}/iperf_h1_h5.json" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
assert doc.get("ok") is True, doc.get("error")
data = doc["data"]
rate = data.get("mbit_per_sec")
assert rate is not None and float(rate) > 0, data
print(json.dumps({k: data[k] for k in ("src","dst","duration_sec","bytes_transferred","mbit_per_sec","retransmissions")}, indent=2))
raise SystemExit(0)
PY
if [[ $? -eq 0 ]]; then
  pass "iperf h1->h5 throughput > 0"
else
  fail "iperf h1->h5"
fi

echo
echo "===== 13. no lingering iperf ====="
sleep 1
IPERF_AFTER="$(pgrep -af '[i]perf3' || true)"
if [[ -n "${IPERF_AFTER}" ]]; then
  fail "iperf3 still running: ${IPERF_AFTER}"
else
  pass "no iperf3 process after test"
fi

echo
echo "===== 14. M3 flows unchanged ====="
AFTER_JSON="${WORKDIR}/flows_after.json"
rest_get "flows" >"${AFTER_JSON}"
python3 - "${BEFORE_JSON}" "${AFTER_JSON}" <<'PY'
import json, sys

def baseline(path):
    flows = json.load(open(path)).get("flows") or []
    ours = [f for f in flows if str(f.get("appId")) == "org.coms6200.baseline"]
    added = [f for f in ours if f.get("state") == "ADDED"]
    keys = sorted(
        (
            str(f.get("deviceId")),
            int(f.get("priority") or 0),
            json.dumps(f.get("selector") or {}, sort_keys=True),
        )
        for f in added
    )
    return len(added), keys

before_n, before_keys = baseline(sys.argv[1])
after_n, after_keys = baseline(sys.argv[2])
print(f"before={before_n} after={after_n}")
raise SystemExit(0 if before_n == 56 and after_n == 56 and before_keys == after_keys else 1)
PY
if [[ $? -eq 0 ]]; then
  pass "56 baseline ADDED flows unchanged"
else
  fail "baseline flows changed during telemetry"
fi

echo
echo "===== 15-16. all-pairs ping (56) ====="
python3 - <<'PY'
from telemetry.gateway import TelemetryGateway
from topologies.spec import HOSTS
gw = TelemetryGateway()
ok_pairs = 0
failed = []
for src in HOSTS:
    for dst in HOSTS:
        if src == dst:
            continue
        result = gw.ping(src, dst, count=1)
        data = result.get("data") or {}
        if result.get("ok") and data.get("received", 0) > 0:
            ok_pairs += 1
        else:
            failed.append((src, dst, result.get("error") or data))
print(f"pairs_ok={ok_pairs}/56")
if failed:
    print("first_failures=" + repr(failed[:3]))
raise SystemExit(0 if ok_pairs == 56 else 1)
PY
if [[ $? -eq 0 ]]; then
  pass "all-pairs ping 56/56"
else
  fail "all-pairs ping was not 56/56"
fi

echo
echo "===== 17. baseline ADDED still 56 ====="
python3 forwarding/baseline_forwarding.py verify
if [[ $? -eq 0 ]]; then
  pass "baseline_forwarding.py verify"
else
  fail "baseline_forwarding.py verify"
fi

echo
echo "===== 18. org.onosproject.fwd inactive ====="
rest_get "applications" >"${WORKDIR}/apps.json"
python3 - "${WORKDIR}/apps.json" <<'PY'
import json, sys
apps = json.load(open(sys.argv[1])).get("applications") or []
fwd = [a for a in apps if a.get("name") == "org.onosproject.fwd"]
state = (fwd[0].get("state") if fwd else "MISSING")
print(f"fwd_state={state}")
raise SystemExit(0 if state != "ACTIVE" else 1)
PY
if [[ $? -eq 0 ]]; then
  pass "org.onosproject.fwd not ACTIVE"
else
  fail "org.onosproject.fwd is ACTIVE"
fi

echo
echo "===== 19. no NORMAL/STP/FLOOD ====="
FLOOD_HIT=0
for sw in s1 s2 s3 s4 s5 s6; do
  dump="$(ovs-ofctl -O OpenFlow13 dump-flows "${sw}" 2>/dev/null || true)"
  if echo "${dump}" | grep -E 'actions=NORMAL|actions=FLOOD|stp_enable' >/dev/null; then
    echo "UNEXPECTED on ${sw}:"
    echo "${dump}" | grep -E 'NORMAL|FLOOD|stp_enable' || true
    FLOOD_HIT=1
  fi
done
if [[ "${FLOOD_HIT}" -eq 0 ]]; then
  pass "no NORMAL/STP/FLOOD in OVS dumps"
else
  fail "NORMAL/STP/FLOOD present"
fi

echo
echo "===== samples written to ${WORKDIR} ====="
echo "get_topology:       ${WORKDIR}/get_topology.json"
echo "get_port_status s3: ${WORKDIR}/get_port_status_s3.json"
echo "get_port_stats s3:  ${WORKDIR}/get_port_stats_s3.json"
echo "get_flow_table s3:  ${WORKDIR}/get_flow_table_s3.json"
echo "ping h1-h5:         ${WORKDIR}/ping_h1_h5.json"
echo "iperf h1-h5:        ${WORKDIR}/iperf_h1_h5.json"

echo
if [[ "${FAIL}" -eq 0 ]]; then
  echo "M4 telemetry verification: ALL CHECKS PASSED"
  exit 0
fi
echo "M4 telemetry verification: FAILED"
exit 1
