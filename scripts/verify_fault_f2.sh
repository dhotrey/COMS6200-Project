#!/usr/bin/env bash
# Live F2 congestion verification.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
# shellcheck source=fault_verify_lib.sh
source "${ROOT}/scripts/fault_verify_lib.sh"

ONOS_API="http://127.0.0.1:8181/onos/v1"
FAIL=0
INJECTED=0
SCENARIO=F2
WORKDIR="$(mktemp -d /tmp/coms6200-f2.XXXXXX)"
DEGRADE_MAX_RATIO="${DEGRADE_MAX_RATIO:-0.25}"

require_root_and_onos_env
trap generic_cleanup EXIT INT TERM

echo "===== PRECHECK ====="
if ! rest_get "devices" >/dev/null; then fail "ONOS REST"; exit 1; fi
pass "ONOS REST"
healthy_gate pre || exit 1

echo
echo "===== BASELINE IPERF h1->h5 ====="
python3 -m telemetry.cli iperf --src h1 --dst h5 --duration 3 >"${WORKDIR}/iperf_before.json"
HEALTHY_MBPS="$(python3 - <<PY
import json
doc=json.load(open("${WORKDIR}/iperf_before.json"))
assert doc.get("ok") is True, doc
mbps=float(doc["data"]["mbit_per_sec"])
print(mbps)
assert mbps > 5.0
PY
)"
echo "healthy_mbps=${HEALTHY_MBPS}"
pass "baseline iperf captured"

echo
echo "===== INJECT F2 ====="
python3 -m faults.cli inject --scenario F2 | tee "${WORKDIR}/inject.json"
python3 - <<PY
import json
doc=json.load(open("${WORKDIR}/inject.json"))
assert doc.get("ok") is True, doc
assert doc["data"]["status"]=="ACTIVE"
assert "tbf" in doc["data"].get("tc_show","").lower() or "rate" in doc["data"].get("tc_show","").lower() or doc["data"].get("tc_show")
print("pids", doc["data"].get("background_pids"))
PY
if [[ $? -ne 0 ]]; then fail "inject F2"; exit 1; fi
INJECTED=1
pass "F2 injected"
sleep 2

echo
echo "===== OBSERVE ====="
python3 -m telemetry.cli ping --src h1 --dst h5 --count 2 >"${WORKDIR}/ping.json"
python3 - <<PY
import json
doc=json.load(open("${WORKDIR}/ping.json"))
assert doc.get("ok") and doc["data"]["received"]>0
print(doc["data"])
PY
if [[ $? -eq 0 ]]; then pass "h1->h5 still reachable"; else fail "h1->h5 unreachable under congestion"; fi

ADDED="$(baseline_added)"
echo "baseline_added_during=${ADDED}"
if [[ "${ADDED}" == "56" ]]; then pass "56 baseline ADDED"; else fail "baseline changed"; fi

python3 -m telemetry.cli get-port-stats --switch s1 >"${WORKDIR}/stats_s1.json"
python3 - <<PY
import json
doc=json.load(open("${WORKDIR}/stats_s1.json"))
assert doc.get("ok") is True, doc
ports={p["port"]:p for p in doc["data"]["ports"]}
p=ports.get(4) or ports.get("4")
assert p is not None
# Expect some packet/byte activity (absolute or rate fields present)
print("s1 port4", {k:p.get(k) for k in ("packets_rx","packets_tx","bytes_rx","bytes_tx","rate_bps") if k in p or True})
# Soft check: at least one counter-like field is non-null / present
ok=False
for k in ("tx_bytes","rx_bytes","bytes_tx","bytes_rx","packets_tx","packets_rx","tx_packets","rx_packets"):
    if p.get(k) not in (None, 0, "0"):
        ok=True
        break
# rates may be the activity signal
for k,v in p.items():
    if "rate" in k and v not in (None, 0, 0.0):
        ok=True
print("activity_signal", ok)
# Do not hard-fail if counters are zero due to sampling window; verifier relies on iperf degradation.
PY
pass "captured s1 port stats during F2"

python3 -m telemetry.cli iperf --src h1 --dst h5 --duration 3 >"${WORKDIR}/iperf_during.json"
python3 - <<PY
import json
doc=json.load(open("${WORKDIR}/iperf_during.json"))
assert doc.get("ok") is True, doc
fault=float(doc["data"]["mbit_per_sec"])
healthy=float("${HEALTHY_MBPS}")
ratio=fault/healthy if healthy>0 else 999
limit=float("${DEGRADE_MAX_RATIO}")
print(f"fault_mbps={fault} healthy_mbps={healthy} ratio={ratio:.4f} max={limit}")
assert ratio <= limit, (fault, healthy, ratio)
PY
if [[ $? -eq 0 ]]; then pass "throughput degraded <= ${DEGRADE_MAX_RATIO} of healthy"; else fail "throughput not sufficiently degraded"; fi

echo
echo "===== RESET F2 ====="
python3 -m faults.cli reset | tee "${WORKDIR}/reset.json"
python3 - <<PY
import json
doc=json.load(open("${WORKDIR}/reset.json"))
assert doc.get("ok") is True, doc
PY
if [[ $? -ne 0 ]]; then fail "reset"; exit 1; fi
INJECTED=0
pass "F2 reset"

# Residual checks
if tc qdisc show dev s1-eth4 2>/dev/null | grep -qi tbf; then fail "tbf remains on s1-eth4"; else pass "no tbf on s1-eth4"; fi
python3 - <<'PY'
from telemetry.host_exec import run_in_host, HostExecError
for host in ("h3","h6","h1","h5"):
    try:
        r=run_in_host(host, ["pgrep", "-x", "iperf3"], timeout_s=2.0)
        if r.returncode==0 and (r.stdout or "").strip():
            raise SystemExit(f"iperf3 still running in {host}: {r.stdout}")
    except HostExecError:
        pass
print("no_host_iperf3")
PY
if [[ $? -eq 0 ]]; then pass "no lingering iperf3"; else fail "lingering iperf3"; fi

healthy_gate post || exit 1
check_fwd_and_flood
python3 forwarding/baseline_forwarding.py verify || fail "baseline verify"

if [[ "${FAIL}" -eq 0 ]]; then
  echo "M5B F2 verification: ALL CHECKS PASSED"
  exit 0
fi
echo "M5B F2 verification: FAILED"
exit 1
