#!/usr/bin/env bash
# Shared helpers for M5/M5B fault verification scripts.
# Sourced by verify_fault_f*.sh — not executed directly.

pass() { echo "PASS  $*"; }
fail() { echo "FAIL  $*"; FAIL=1; }

rest_get() {
  curl -sS -f -u "${ONOS_USER}:${ONOS_PASSWORD}" "${ONOS_API}/$1"
}

directed_link_count() {
  rest_get "links" | python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("links") or []))'
}

baseline_added() {
  rest_get "flows" | python3 -c 'import json,sys; flows=json.load(sys.stdin).get("flows") or []; print(sum(1 for f in flows if f.get("appId")=="org.coms6200.baseline" and f.get("state")=="ADDED"))'
}

experiment_flow_count() {
  rest_get "flows" | python3 -c 'import json,sys; flows=json.load(sys.stdin).get("flows") or []; print(sum(1 for f in flows if f.get("appId")=="org.coms6200.experiment"))'
}

require_root_and_onos_env() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "ERROR: ROOT_REQUIRED — run as root (scripts do not invoke sudo)."
    exit 1
  fi
  if [[ -z "${ONOS_USER:-}" || -z "${ONOS_PASSWORD:-}" ]]; then
    echo "ERROR: ONOS_USER and ONOS_PASSWORD must be set (values not printed)."
    exit 1
  fi
}

healthy_gate() {
  local label="$1"
  echo "===== HEALTHY GATE: ${label} ====="
  local links added
  links="$(directed_link_count)"
  added="$(baseline_added)"
  echo "directed_links=${links} baseline_added=${added}"
  if [[ "${links}" != "20" ]]; then fail "${label}: expected 20 directed links"; return 1; fi
  if [[ "${added}" != "56" ]]; then fail "${label}: expected 56 ADDED"; return 1; fi
  python3 - <<'PY'
from telemetry.gateway import TelemetryGateway
from topologies.spec import HOSTS
gw = TelemetryGateway()
ok = 0
for src in HOSTS:
    for dst in HOSTS:
        if src == dst:
            continue
        r = gw.ping(src, dst, count=1)
        d = r.get("data") or {}
        if r.get("ok") and d.get("received", 0) > 0:
            ok += 1
print(f"pairs_ok={ok}/56")
raise SystemExit(0 if ok == 56 else 1)
PY
  if [[ $? -ne 0 ]]; then fail "${label}: pingall"; return 1; fi
  local exp
  exp="$(experiment_flow_count)"
  if [[ "${exp}" != "0" ]]; then fail "${label}: experiment flows remain (${exp})"; return 1; fi
  python3 -m faults.cli status >"${WORKDIR}/status_${label}.json"
  python3 - <<PY
import json
doc=json.load(open("${WORKDIR}/status_${label}.json"))
assert doc.get("ok") is True
assert doc["data"].get("active") is False
print("active=false")
PY
  if [[ $? -ne 0 ]]; then fail "${label}: fault still active"; return 1; fi
  pass "${label}: healthy"
  return 0
}

check_fwd_and_flood() {
  rest_get "applications" >"${WORKDIR}/apps.json"
  python3 - <<PY
import json
apps=json.load(open("${WORKDIR}/apps.json")).get("applications") or []
fwd=[a for a in apps if a.get("name")=="org.onosproject.fwd"]
state=fwd[0].get("state") if fwd else "MISSING"
print("fwd_state="+str(state))
raise SystemExit(0 if state!="ACTIVE" else 1)
PY
  if [[ $? -eq 0 ]]; then pass "fwd not ACTIVE"; else fail "fwd ACTIVE"; fi
  local hit=0 sw dump
  for sw in s1 s2 s3 s4 s5 s6; do
    dump="$(ovs-ofctl -O OpenFlow13 dump-flows "${sw}" 2>/dev/null || true)"
    if echo "${dump}" | grep -E 'actions=NORMAL|actions=FLOOD|stp_enable' >/dev/null; then
      hit=1
    fi
  done
  if [[ "${hit}" -eq 0 ]]; then pass "no NORMAL/STP/FLOOD"; else fail "NORMAL/STP/FLOOD present"; fi
}

generic_cleanup() {
  local rc=$?
  if [[ "${INJECTED:-0}" -eq 1 ]]; then
    echo
    echo "===== CLEANUP: faults.cli reset ====="
    python3 -m faults.cli reset >/tmp/fault-cleanup.json 2>&1 || \
      python3 -m faults.cli reset --force-scenario "${SCENARIO:-F1}" >/tmp/fault-cleanup-force.json 2>&1 || true
  fi
  if [[ "${rc}" -ne 0 && "${FAIL:-0}" -ne 0 ]]; then
    echo
    echo "Manual recovery if needed:"
    echo "  python3 -m faults.cli reset --force-scenario ${SCENARIO:-F1}"
    echo "  python3 -m faults.cli reset --force-f1"
    echo "  tc qdisc del dev s1-eth4 root 2>/dev/null || true"
    echo "  tc qdisc del dev s3-eth5 root 2>/dev/null || true"
    echo "  python3 forwarding/baseline_forwarding.py install"
  fi
}
