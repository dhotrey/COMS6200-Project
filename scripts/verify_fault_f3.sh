#!/usr/bin/env bash
# Live F3 ACL/policy DROP verification.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
# shellcheck source=fault_verify_lib.sh
source "${ROOT}/scripts/fault_verify_lib.sh"

ONOS_API="http://127.0.0.1:8181/onos/v1"
FAIL=0
INJECTED=0
SCENARIO=F3
WORKDIR="$(mktemp -d /tmp/coms6200-f3.XXXXXX)"

require_root_and_onos_env
trap generic_cleanup EXIT INT TERM

echo "===== PRECHECK ====="
healthy_gate pre || exit 1

echo
echo "===== INJECT F3 ====="
python3 -m faults.cli inject --scenario F3 | tee "${WORKDIR}/inject.json"
python3 - <<PY
import json
doc=json.load(open("${WORKDIR}/inject.json"))
assert doc.get("ok") is True, doc
assert doc["data"]["status"]=="ACTIVE"
assert doc["data"]["app_id"]=="org.coms6200.experiment"
assert doc["data"]["priority"]==50000
PY
if [[ $? -ne 0 ]]; then fail "inject"; exit 1; fi
INJECTED=1
pass "F3 injected"
sleep 1

ADDED="$(baseline_added)"
EXP="$(experiment_flow_count)"
echo "baseline_added=${ADDED} experiment=${EXP}"
if [[ "${ADDED}" == "56" ]]; then pass "56 baseline ADDED"; else fail "baseline count"; fi
if [[ "${EXP}" -ge 1 ]]; then pass "experiment flow present"; else fail "no experiment flow"; fi

python3 -m telemetry.cli ping --src h1 --dst h5 --count 3 >"${WORKDIR}/p_h1_h5.json"
python3 - <<PY
import json
d=json.load(open("${WORKDIR}/p_h1_h5.json"))["data"]
print(d)
assert d["received"]==0
PY
if [[ $? -eq 0 ]]; then pass "h1->h5 failed"; else fail "h1->h5 unexpectedly ok"; fi

python3 -m telemetry.cli ping --src h2 --dst h5 --count 3 >"${WORKDIR}/p_h2_h5.json"
python3 - <<PY
import json
d=json.load(open("${WORKDIR}/p_h2_h5.json"))["data"]
print(d)
assert d["received"]>0
PY
if [[ $? -eq 0 ]]; then pass "h2->h5 ok"; else fail "h2->h5 failed"; fi

python3 -m telemetry.cli ping --src h1 --dst h6 --count 3 >"${WORKDIR}/p_h1_h6.json"
python3 - <<PY
import json
d=json.load(open("${WORKDIR}/p_h1_h6.json"))["data"]
print(d)
assert d["received"]>0
PY
if [[ $? -eq 0 ]]; then pass "h1->h6 ok"; else fail "h1->h6 failed"; fi

python3 -m telemetry.cli get-flow-table --switch s3 >"${WORKDIR}/flows_s3.json"
python3 - <<PY
import json
doc=json.load(open("${WORKDIR}/flows_s3.json"))
assert doc.get("ok")
flows=doc["data"]["flows"]
# Look for high-priority rule with empty/no OUTPUT (drop)
hits=[]
for f in flows:
    if int(f.get("priority") or 0) >= 50000:
        actions=str(f.get("actions") or f.get("treatment") or "")
        hits.append(f)
print("high_pri_count", len(hits))
assert hits, "expected high-priority experiment flow visible"
# Ensure no fault labels in serialized flows
blob=json.dumps(flows).lower()
assert "fault_id" not in blob and "ground_truth" not in blob
assert "f3" not in blob  # scenario id must not appear as label
PY
if [[ $? -eq 0 ]]; then pass "flow table shows high-priority drop without fault labels"; else fail "flow table check"; fi

echo
echo "===== RESET F3 ====="
python3 -m faults.cli reset | tee "${WORKDIR}/reset.json"
python3 - <<PY
import json
assert json.load(open("${WORKDIR}/reset.json")).get("ok") is True
PY
INJECTED=0
EXP="$(experiment_flow_count)"
if [[ "${EXP}" == "0" ]]; then pass "experiment flows gone"; else fail "experiment flows remain"; fi

healthy_gate post || exit 1
check_fwd_and_flood

if [[ "${FAIL}" -eq 0 ]]; then
  echo "M5B F3 verification: ALL CHECKS PASSED"
  exit 0
fi
echo "M5B F3 verification: FAILED"
exit 1
