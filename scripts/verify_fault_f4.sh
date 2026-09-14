#!/usr/bin/env bash
# Live F4 bounded forwarding-loop verification.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
# shellcheck source=fault_verify_lib.sh
source "${ROOT}/scripts/fault_verify_lib.sh"

ONOS_API="http://127.0.0.1:8181/onos/v1"
FAIL=0
INJECTED=0
SCENARIO=F4
WORKDIR="$(mktemp -d /tmp/coms6200-f4.XXXXXX)"

require_root_and_onos_env
trap generic_cleanup EXIT INT TERM

echo "===== PRECHECK ====="
healthy_gate pre || exit 1

echo
echo "===== INJECT F4 ====="
python3 -m faults.cli inject --scenario F4 | tee "${WORKDIR}/inject.json"
python3 - <<PY
import json
doc=json.load(open("${WORKDIR}/inject.json"))
assert doc.get("ok") is True, doc
assert doc["data"]["status"]=="ACTIVE"
assert doc["data"]["flow_count"]==3
assert doc["data"]["safety_interface"]=="s3-eth5"
PY
if [[ $? -ne 0 ]]; then fail "inject"; exit 1; fi
INJECTED=1
pass "F4 injected"

if tc qdisc show dev s3-eth5 | grep -qi tbf; then pass "safety tbf present"; else fail "safety tbf missing"; fi
EXP="$(experiment_flow_count)"
if [[ "${EXP}" == "3" ]]; then pass "3 experiment flows"; else fail "expected 3 experiment flows got ${EXP}"; fi
ADDED="$(baseline_added)"
if [[ "${ADDED}" == "56" ]]; then pass "56 baseline ADDED"; else fail "baseline count"; fi

# Sample counters before small traffic burst
python3 -m telemetry.cli get-port-stats --switch s3 >"${WORKDIR}/stats_before.json"
# Bounded test traffic only (few pings) — no persistent generator
python3 -m telemetry.cli ping --src h1 --dst h5 --count 5 >"${WORKDIR}/p_h1_h5.json" || true
python3 - <<PY
import json
d=json.load(open("${WORKDIR}/p_h1_h5.json"))
print(d.get("data") or d)
# Expect failure / 100% loss
data=d.get("data") or {}
assert d.get("ok") is True
assert data.get("received", 1)==0
PY
if [[ $? -eq 0 ]]; then pass "h1->h5 failed under loop"; else fail "h1->h5 unexpectedly ok"; fi

python3 -m telemetry.cli ping --src h1 --dst h2 --count 2 >"${WORKDIR}/p_h1_h2.json"
python3 - <<PY
import json
assert json.load(open("${WORKDIR}/p_h1_h2.json"))["data"]["received"]>0
PY
if [[ $? -eq 0 ]]; then pass "h1->h2 local ok"; else fail "h1->h2"; fi

python3 -m telemetry.cli ping --src h3 --dst h5 --count 2 >"${WORKDIR}/p_h3_h5.json"
python3 - <<PY
import json
assert json.load(open("${WORKDIR}/p_h3_h5.json"))["data"]["received"]>0
PY
if [[ $? -eq 0 ]]; then pass "h3->h5 unaffected ok"; else fail "h3->h5"; fi

python3 -m telemetry.cli get-port-stats --switch s3 >"${WORKDIR}/stats_after.json"
python3 - <<PY
import json
b=json.load(open("${WORKDIR}/stats_before.json"))["data"]["ports"]
a=json.load(open("${WORKDIR}/stats_after.json"))["data"]["ports"]
bp={p["port"]:p for p in b}
ap={p["port"]:p for p in a}
# Port 5 is s3-s4 loop edge
before=bp.get(5) or bp.get("5") or {}
after=ap.get(5) or ap.get("5") or {}
print("s3-eth5 before", before)
print("s3-eth5 after", after)
# Soft: counters should not all be identical if traffic hit the loop; do not hard-fail if ONOS sampling is coarse.
growth=False
for k in after:
    try:
        if float(after.get(k) or 0) > float(before.get(k) or 0):
            growth=True
            break
    except (TypeError, ValueError):
        pass
print("counter_growth_observed", growth)
PY
pass "sampled loop-path counters"

# No uncontrolled storm: ensure we did not spawn background iperf
python3 - <<'PY'
from telemetry.host_exec import run_in_host, HostExecError
for host in ("h1","h5","h3"):
    try:
        r=run_in_host(host, ["pgrep", "-x", "iperf3"], timeout_s=2.0)
        if r.returncode==0 and (r.stdout or "").strip():
            raise SystemExit("unexpected iperf3")
    except HostExecError:
        pass
print("no_storm_generator")
PY
if [[ $? -eq 0 ]]; then pass "no uncontrolled generator"; else fail "unexpected generator"; fi

echo
echo "===== RESET F4 ====="
python3 -m faults.cli reset | tee "${WORKDIR}/reset.json"
python3 - <<PY
import json
assert json.load(open("${WORKDIR}/reset.json")).get("ok") is True
PY
INJECTED=0
if tc qdisc show dev s3-eth5 2>/dev/null | grep -qi tbf; then fail "safety tbf remains"; else pass "safety tbf removed"; fi
EXP="$(experiment_flow_count)"
if [[ "${EXP}" == "0" ]]; then pass "loop flows removed"; else fail "loop flows remain"; fi

healthy_gate post || exit 1
check_fwd_and_flood

if [[ "${FAIL}" -eq 0 ]]; then
  echo "M5B F4 verification: ALL CHECKS PASSED"
  exit 0
fi
echo "M5B F4 verification: FAILED"
exit 1
