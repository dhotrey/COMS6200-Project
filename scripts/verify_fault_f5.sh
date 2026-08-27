#!/usr/bin/env bash
# Live F5 missing baseline flow verification.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
# shellcheck source=fault_verify_lib.sh
source "${ROOT}/scripts/fault_verify_lib.sh"

ONOS_API="http://127.0.0.1:8181/onos/v1"
FAIL=0
INJECTED=0
SCENARIO=F5
WORKDIR="$(mktemp -d /tmp/coms6200-f5.XXXXXX)"

require_root_and_onos_env
trap generic_cleanup EXIT INT TERM

echo "===== PRECHECK ====="
healthy_gate pre || exit 1
ADDED="$(baseline_added)"
if [[ "${ADDED}" != "56" ]]; then fail "pre 56"; exit 1; fi

echo
echo "===== INJECT F5 ====="
python3 -m faults.cli inject --scenario F5 | tee "${WORKDIR}/inject.json"
python3 - <<PY
import json
doc=json.load(open("${WORKDIR}/inject.json"))
assert doc.get("ok") is True, doc
assert doc["data"]["status"]=="ACTIVE"
assert doc["data"]["baseline_count"]==55
PY
if [[ $? -ne 0 ]]; then fail "inject"; exit 1; fi
INJECTED=1
pass "F5 injected"

ADDED="$(baseline_added)"
echo "baseline_added_during=${ADDED}"
if [[ "${ADDED}" == "55" ]]; then pass "55 baseline ADDED"; else fail "expected 55 got ${ADDED}"; fi

python3 -m telemetry.cli ping --src h1 --dst h5 --count 3 >"${WORKDIR}/p_h1_h5.json"
python3 - <<PY
import json
assert json.load(open("${WORKDIR}/p_h1_h5.json"))["data"]["received"]==0
PY
if [[ $? -eq 0 ]]; then pass "h1->h5 failed"; else fail "h1->h5"; fi

python3 -m telemetry.cli ping --src h2 --dst h5 --count 3 >"${WORKDIR}/p_h2_h5.json"
python3 - <<PY
import json
assert json.load(open("${WORKDIR}/p_h2_h5.json"))["data"]["received"]==0
PY
if [[ $? -eq 0 ]]; then pass "h2->h5 failed"; else fail "h2->h5"; fi

python3 -m telemetry.cli ping --src h1 --dst h6 --count 3 >"${WORKDIR}/p_h1_h6.json"
python3 - <<PY
import json
assert json.load(open("${WORKDIR}/p_h1_h6.json"))["data"]["received"]>0
PY
if [[ $? -eq 0 ]]; then pass "h1->h6 ok"; else fail "h1->h6"; fi

python3 -m telemetry.cli ping --src h3 --dst h5 --count 3 >"${WORKDIR}/p_h3_h5.json"
python3 - <<PY
import json
assert json.load(open("${WORKDIR}/p_h3_h5.json"))["data"]["received"]>0
PY
if [[ $? -eq 0 ]]; then pass "h3->h5 unaffected ok"; else fail "h3->h5"; fi

python3 -m telemetry.cli get-flow-table --switch s3 >"${WORKDIR}/flows_s3.json"
pass "captured s3 flow table during F5"

echo
echo "===== RESET F5 ====="
python3 -m faults.cli reset | tee "${WORKDIR}/reset.json"
python3 - <<PY
import json
doc=json.load(open("${WORKDIR}/reset.json"))
assert doc.get("ok") is True
assert doc["data"].get("baseline_count")==56
PY
INJECTED=0
ADDED="$(baseline_added)"
if [[ "${ADDED}" == "56" ]]; then pass "56 restored"; else fail "restore count ${ADDED}"; fi

healthy_gate post || exit 1
check_fwd_and_flood

if [[ "${FAIL}" -eq 0 ]]; then
  echo "M5B F5 verification: ALL CHECKS PASSED"
  exit 0
fi
echo "M5B F5 verification: FAILED"
exit 1
