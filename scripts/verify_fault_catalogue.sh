#!/usr/bin/env bash
# Sequentially verify Fault Catalogue v1: F1→F2→F3→F4→F5 with healthy gates.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
# shellcheck source=fault_verify_lib.sh
source "${ROOT}/scripts/fault_verify_lib.sh"

ONOS_API="http://127.0.0.1:8181/onos/v1"
FAIL=0
INJECTED=0
WORKDIR="$(mktemp -d /tmp/coms6200-catalogue.XXXXXX)"

require_root_and_onos_env
trap generic_cleanup EXIT INT TERM

run_one() {
  local script="$1"
  local name="$2"
  echo
  echo "########## CATALOGUE: ${name} ##########"
  if bash "${script}"; then
    pass "${name}"
  else
    fail "${name}"
    return 1
  fi
  healthy_gate "after_${name}" || return 1
  return 0
}

echo "===== CATALOGUE PRECHECK ====="
healthy_gate start || exit 1

run_one "${ROOT}/scripts/verify_fault_f1.sh" F1 || exit 1
run_one "${ROOT}/scripts/verify_fault_f2.sh" F2 || exit 1
run_one "${ROOT}/scripts/verify_fault_f3.sh" F3 || exit 1
run_one "${ROOT}/scripts/verify_fault_f4.sh" F4 || exit 1
run_one "${ROOT}/scripts/verify_fault_f5.sh" F5 || exit 1

check_fwd_and_flood
# Residual sweep
for iface in s1-eth4 s3-eth5; do
  if tc qdisc show dev "${iface}" 2>/dev/null | grep -qi tbf; then
    fail "residual tbf on ${iface}"
  else
    pass "no residual tbf on ${iface}"
  fi
done
EXP="$(experiment_flow_count)"
if [[ "${EXP}" == "0" ]]; then pass "no experiment flows"; else fail "experiment flows=${EXP}"; fi

if [[ "${FAIL}" -eq 0 ]]; then
  echo "Fault Catalogue v1 verification: ALL FIVE SCENARIOS PASSED"
  exit 0
fi
echo "Fault Catalogue v1 verification: FAILED"
exit 1
