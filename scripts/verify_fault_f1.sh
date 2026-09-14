#!/usr/bin/env bash
# Live M5 F1 verification: inject primary s3-s1 link failure, observe with M4,
# then reset and restore healthy baseline.
#
# Prerequisites (already running):
#   ONOS 2.7.0 + main6s8h + M3 baseline
#
#   export ONOS_USER=onos
#   export ONOS_PASSWORD=rocks
#   ./scripts/verify_fault_f1.sh
#
# Requires root for link-state mutation (does not call sudo itself).
# Cleans up F1 on exit/failure via trap.

set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"

export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

ONOS_USER="${ONOS_USER:-}"
ONOS_PASSWORD="${ONOS_PASSWORD:-}"
ONOS_API="http://127.0.0.1:8181/onos/v1"
FAIL=0
INJECTED=0
WORKDIR="$(mktemp -d /tmp/coms6200-f1.XXXXXX)"
CONVERGE_TIMEOUT_S="${CONVERGE_TIMEOUT_S:-30}"

pass() { echo "PASS  $*"; }
fail() { echo "FAIL  $*"; FAIL=1; }

if [[ "${EUID}" -ne 0 ]]; then
  echo "ERROR: ROOT_REQUIRED — run as root (this script does not invoke sudo)."
  exit 1
fi

if [[ -z "${ONOS_USER}" || -z "${ONOS_PASSWORD}" ]]; then
  echo "ERROR: ONOS_USER and ONOS_PASSWORD must be set (values not printed)."
  exit 1
fi

cleanup() {
  local rc=$?
  if [[ "${INJECTED}" -eq 1 ]]; then
    echo
    echo "===== CLEANUP: resetting F1 ====="
    if ! python3 -m faults.cli reset >/tmp/f1-cleanup.json 2>&1; then
      echo "WARNING: faults.cli reset returned non-zero; trying --force-f1"
      python3 -m faults.cli reset --force-f1 >/tmp/f1-cleanup-force.json 2>&1 || true
    fi
    python3 -m faults.cli status || true
  fi
  if [[ "${rc}" -ne 0 && "${FAIL}" -ne 0 ]]; then
    echo
    echo "Manual recovery if needed:"
    echo "  python3 -m faults.cli reset --force-f1"
    echo "  ip link set dev s3-eth1 up; ip link set dev s1-eth2 up"
  fi
}
trap cleanup EXIT INT TERM

rest_get() {
  curl -sS -f -u "${ONOS_USER}:${ONOS_PASSWORD}" "${ONOS_API}/$1"
}

directed_link_count() {
  rest_get "links" | python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("links") or []))'
}

wait_links() {
  local want="$1"
  local label="$2"
  local i count
  for i in $(seq 1 "${CONVERGE_TIMEOUT_S}"); do
    count="$(directed_link_count)"
    echo "  poll ${i}/${CONVERGE_TIMEOUT_S}: directed_links=${count} (want ${want})"
    if [[ "${count}" == "${want}" ]]; then
      echo "${label}_seconds=${i}"
      return 0
    fi
    sleep 1
  done
  return 1
}

baseline_added() {
  rest_get "flows" | python3 -c 'import json,sys; flows=json.load(sys.stdin).get("flows") or []; print(sum(1 for f in flows if f.get("appId")=="org.coms6200.baseline" and f.get("state")=="ADDED"))'
}

echo "===== PRECHECK: ONOS / topology / baseline ====="
if ! rest_get "devices" >/dev/null; then
  fail "ONOS REST unavailable"
  exit 1
fi
pass "ONOS REST"

for sw in s1 s2 s3 s4 s5 s6; do
  if ovs-vsctl br-exists "${sw}"; then
    pass "bridge ${sw}"
  else
    fail "bridge ${sw} missing"
  fi
done
if [[ "${FAIL}" -ne 0 ]]; then exit 1; fi

LINKS_BEFORE="$(directed_link_count)"
echo "directed_links_before=${LINKS_BEFORE}"
if [[ "${LINKS_BEFORE}" != "20" ]]; then
  fail "expected 20 directed links before F1, got ${LINKS_BEFORE}"
  exit 1
fi
pass "20 directed links"

ADDED_BEFORE="$(baseline_added)"
echo "baseline_added_before=${ADDED_BEFORE}"
if [[ "${ADDED_BEFORE}" != "56" ]]; then
  fail "expected 56 ADDED baseline flows"
  exit 1
fi
pass "56 baseline ADDED"

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
if [[ $? -eq 0 ]]; then pass "healthy pingall 56/56"; else fail "precheck pingall"; exit 1; fi

python3 -m faults.cli status >"${WORKDIR}/status_before.json"
python3 - <<PY
import json
doc=json.load(open("${WORKDIR}/status_before.json"))
assert doc.get("ok") is True, doc
assert doc["data"].get("active") is False
print("active=false")
PY
if [[ $? -eq 0 ]]; then pass "no active fault"; else fail "fault already active"; exit 1; fi

echo
echo "===== INJECT F1 ====="
python3 -m faults.cli inject --scenario F1 | tee "${WORKDIR}/inject.json"
python3 - <<PY
import json
doc=json.load(open("${WORKDIR}/inject.json"))
assert doc.get("ok") is True, doc
assert doc["data"]["status"]=="ACTIVE"
assert set(doc["data"]["interfaces"])=={"s1-eth2","s3-eth1"}
for row in doc["data"]["endpoint_state"]:
    assert row["operstate"]!="up", row
print("injected", doc["data"]["interfaces"])
PY
if [[ $? -ne 0 ]]; then fail "inject F1"; exit 1; fi
INJECTED=1
pass "F1 injected; endpoints down"

echo
echo "===== WAIT ONOS CONVERGENCE (20 -> 18 directed links) ====="
if wait_links 18 "f1_converge"; then
  pass "ONOS directed links = 18"
else
  fail "ONOS did not converge to 18 directed links within ${CONVERGE_TIMEOUT_S}s"
fi

echo
echo "===== OBSERVE WITH M4 ====="
python3 -m telemetry.cli get-topology >"${WORKDIR}/topo_fault.json"
python3 - <<PY
import json
doc=json.load(open("${WORKDIR}/topo_fault.json"))
assert doc.get("ok") is True, doc
s=doc["data"]["summary"]
print(json.dumps(s, indent=2))
assert s["configured_inter_switch_links"]==10
assert s["physical_inter_switch_links"]==9
assert s["configured_host_attachments"]==9
PY
if [[ $? -eq 0 ]]; then pass "get_topology during F1 (configured 10, observed 9)"; else fail "get_topology during F1"; fi

python3 -m telemetry.cli get-port-status --switch s3 >"${WORKDIR}/ports_s3.json"
python3 -m telemetry.cli get-port-status --switch s1 >"${WORKDIR}/ports_s1.json"
python3 - <<PY
import json
for path, sw, port in (("${WORKDIR}/ports_s3.json","s3",1), ("${WORKDIR}/ports_s1.json","s1",2)):
    doc=json.load(open(path))
    assert doc.get("ok") is True, doc
    rows={p["port"]:p for p in doc["data"]["ports"]}
    row=rows.get(port) or rows.get(str(port))
    print(sw, "port", port, "enabled=", None if row is None else row.get("enabled"), "name=", None if row is None else row.get("name"))
PY
pass "captured port status for s3:1 and s1:2"

python3 -m telemetry.cli get-flow-table --switch s3 >"${WORKDIR}/flows_s3.json"
python3 -m telemetry.cli get-flow-table --switch s1 >"${WORKDIR}/flows_s1.json"
ADDED_DURING="$(baseline_added)"
echo "baseline_added_during=${ADDED_DURING}"
if [[ "${ADDED_DURING}" == "56" ]]; then pass "56 baseline ADDED during F1"; else fail "baseline flows changed during F1"; fi

python3 -m telemetry.cli ping --src h1 --dst h5 --count 3 >"${WORKDIR}/ping_h1_h5.json"
python3 - <<PY
import json
doc=json.load(open("${WORKDIR}/ping_h1_h5.json"))
assert doc.get("ok") is True, doc
d=doc["data"]
print(d)
assert d["received"]==0 and float(d["loss_pct"])==100.0
PY
if [[ $? -eq 0 ]]; then pass "h1->h5 failed as expected"; else fail "h1->h5 unexpectedly succeeded"; fi

python3 -m telemetry.cli ping --src h1 --dst h2 --count 3 >"${WORKDIR}/ping_h1_h2.json"
python3 - <<PY
import json
doc=json.load(open("${WORKDIR}/ping_h1_h2.json"))
assert doc.get("ok") is True, doc
d=doc["data"]
print(d)
assert d["received"]>0
PY
if [[ $? -eq 0 ]]; then pass "h1->h2 local path healthy"; else fail "h1->h2 local path failed"; fi

python3 -m telemetry.cli ping --src h3 --dst h5 --count 3 >"${WORKDIR}/ping_h3_h5.json"
python3 - <<PY
import json
doc=json.load(open("${WORKDIR}/ping_h3_h5.json"))
assert doc.get("ok") is True, doc
d=doc["data"]
print(d)
assert d["received"]>0
PY
if [[ $? -eq 0 ]]; then pass "h3->h5 unaffected path healthy"; else fail "h3->h5 failed"; fi

echo
echo "===== RESET F1 ====="
python3 -m faults.cli reset | tee "${WORKDIR}/reset.json"
python3 - <<PY
import json
doc=json.load(open("${WORKDIR}/reset.json"))
assert doc.get("ok") is True, doc
assert doc["data"]["status"] in ("IDLE","RECOVERED")
for row in doc["data"]["endpoint_state"]:
    assert row["operstate"]=="up", row
print("reset ok")
PY
if [[ $? -ne 0 ]]; then fail "reset F1"; exit 1; fi
INJECTED=0
pass "F1 reset; endpoints UP"

echo
echo "===== WAIT ONOS RECOVERY (18 -> 20 directed links) ====="
if wait_links 20 "f1_recover"; then
  pass "ONOS directed links restored to 20"
else
  fail "ONOS did not restore 20 directed links within ${CONVERGE_TIMEOUT_S}s"
fi

echo
echo "===== POSTCHECK ====="
python3 forwarding/baseline_forwarding.py verify
if [[ $? -eq 0 ]]; then pass "baseline verify"; else fail "baseline verify"; fi

ADDED_AFTER="$(baseline_added)"
echo "baseline_added_after=${ADDED_AFTER}"
if [[ "${ADDED_AFTER}" == "56" ]]; then pass "56 ADDED after reset"; else fail "baseline count after reset"; fi

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
if [[ $? -eq 0 ]]; then pass "final pingall 56/56"; else fail "final pingall"; fi

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

FLOOD_HIT=0
for sw in s1 s2 s3 s4 s5 s6; do
  dump="$(ovs-ofctl -O OpenFlow13 dump-flows "${sw}" 2>/dev/null || true)"
  if echo "${dump}" | grep -E 'actions=NORMAL|actions=FLOOD|stp_enable' >/dev/null; then
    FLOOD_HIT=1
  fi
done
if [[ "${FLOOD_HIT}" -eq 0 ]]; then pass "no NORMAL/STP/FLOOD"; else fail "NORMAL/STP/FLOOD present"; fi

python3 -m faults.cli status >"${WORKDIR}/status_after.json"
python3 - <<PY
import json
doc=json.load(open("${WORKDIR}/status_after.json"))
assert doc.get("ok") is True, doc
assert doc["data"].get("active") is False
print("active=false")
PY
if [[ $? -eq 0 ]]; then pass "no active fault state"; else fail "fault state still active"; fi

echo
echo "samples: ${WORKDIR}"
if [[ "${FAIL}" -eq 0 ]]; then
  echo "M5 F1 verification: ALL CHECKS PASSED"
  exit 0
fi
echo "M5 F1 verification: FAILED"
exit 1
