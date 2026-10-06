#!/usr/bin/env bash
# Session helper: start/stop a topology + ONOS, and inject/reset F1–F5.
#
# Does not replace setup_ubuntu.sh / setup_onos.sh. Those still install the
# environment. This script only brings a previously installed testbed up and
# down. It is not an LLM tool and does not send scenario IDs to the agent.
#
# COMS6200_TOPOLOGY selects the topology (default main6s8h; or ring5s5h) and
# with it the fault catalogue (main6s8h: frozen v1; ring5s5h: ring5s5h-v1).
#
#   ./scripts/testbed.sh start
#   COMS6200_TOPOLOGY=ring5s5h ./scripts/testbed.sh start
#   ./scripts/testbed.sh inject F1
#   ./scripts/testbed.sh reset
#   ./scripts/testbed.sh stop                 # Mininet down; ONOS stays up
#   ./scripts/testbed.sh stop --with-onos     # also stop the ONOS container

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"

# shellcheck source=../setup/docker_access.sh
. "${ROOT}/setup/docker_access.sh"

ONOS_CONTAINER="${ONOS_CONTAINER:-onos}"
ONOS_HOST="${ONOS_HOST:-127.0.0.1}"
ONOS_REST_PORT="${ONOS_REST_PORT:-8181}"
ONOS_OF_PORT="${ONOS_OF_PORT:-6653}"
ONOS_API="http://${ONOS_HOST}:${ONOS_REST_PORT}/onos/v1"
ONOS_USER="${ONOS_USER:-onos}"
ONOS_PASSWORD="${ONOS_PASSWORD:-rocks}"
export ONOS_USER ONOS_PASSWORD ONOS_HOST ONOS_OF_PORT ONOS_API
export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

RUN_DIR="${COMS6200_FAULT_STATE_DIR:-/run/coms6200}"
PID_FILE="${RUN_DIR}/mininet.pid"
READY_FILE="${RUN_DIR}/mininet.ready"
LOG_FILE="${RUN_DIR}/mininet.log"
ONOS_RECOVERY_USED=0

usage() {
  cat <<'EOF'
Usage:
  ./scripts/testbed.sh start
  ./scripts/testbed.sh stop
  ./scripts/testbed.sh stop --with-onos
  ./scripts/testbed.sh inject F1|F2|F3|F4|F5
  ./scripts/testbed.sh reset
  ./scripts/testbed.sh status

start  Open vSwitch, a healthy ONOS, the background topology, then baseline
       flows. Reuses an already-healthy ONOS. If REST is up but the switches
       do not attach, recreates only the ONOS container once and retries.
stop   Reset any active fault, stop Mininet, clear OVS Mininet state.
       Topologies other than main6s8h also remove their baseline flows first.
       Leaves the ONOS container running.
stop --with-onos
       Same as stop, then stop the ONOS container. Operator action, not the
       normal experiment reset.
inject Reset an active catalogue fault if needed, then inject F1–F5.
reset  Clear the active catalogue fault only (Mininet/ONOS stay up).
status Show ONOS, Mininet, and fault-injector state.

ONOS REST defaults to onos/rocks. Override with ONOS_USER / ONOS_PASSWORD.
A missing ONOS container is created with ./setup/setup_onos.sh.
COMS6200_TOPOLOGY selects main6s8h (default) or ring5s5h. Use the same
value for every command in a session. F1–F5 come from that topology's
fault catalogue.
Catalogue v1 has no F6+.
EOF
}

die() { echo "ERROR: $*" >&2; exit 1; }

TOPOLOGY="${COMS6200_TOPOLOGY:-main6s8h}"
export COMS6200_TOPOLOGY="${TOPOLOGY}"
# Expected ONOS view of the selected topology: "<switches> <directed links>".
TOPOLOGY_COUNTS="$(python3 -c 'from topologies.active import DEVICE_IDS, INTER_SWITCH_LINKS; print(len(DEVICE_IDS), 2 * len(INTER_SWITCH_LINKS))')" \
  || die "cannot load topology '${TOPOLOGY}'. COMS6200_TOPOLOGY must be main6s8h or ring5s5h."
read -r EXPECTED_SWITCHES EXPECTED_LINKS <<<"${TOPOLOGY_COUNTS}"

as_root() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  else
    sudo --preserve-env=ONOS_USER,ONOS_PASSWORD,ONOS_URL,ONOS_HOST,ONOS_OF_PORT,PYTHONPATH,COMS6200_TOPOLOGY "$@"
  fi
}

normalize_scenario() {
  local raw="${1:-}"
  raw="$(printf '%s' "${raw}" | tr '[:lower:]' '[:upper:]')"
  raw="${raw#F}"
  case "${raw}" in
    1|2|3|4|5) printf 'F%s\n' "${raw}" ;;
    *) return 1 ;;
  esac
}

pid_alive() {
  local pid="$1"
  [[ "${pid}" =~ ^[0-9]+$ ]] || return 1
  as_root kill -0 "${pid}" 2>/dev/null
}

read_pid() {
  as_root test -f "${PID_FILE}" || return 1
  as_root cat "${PID_FILE}" 2>/dev/null | tr -d '[:space:]'
}

show_log() {
  echo "----- ${LOG_FILE} (last 40 lines) -----"
  as_root tail -n 40 "${LOG_FILE}" 2>/dev/null || true
}

start_ovs() {
  if ovs-vsctl show >/dev/null 2>&1 || as_root ovs-vsctl show >/dev/null 2>&1; then
    echo "==> Open vSwitch is already running"
    return 0
  fi
  echo "==> Starting Open vSwitch"
  if systemctl list-unit-files --type=service 2>/dev/null | grep -q '^openvswitch-switch\.service'; then
    as_root systemctl start openvswitch-switch
  elif systemctl list-unit-files --type=service 2>/dev/null | grep -q '^openvswitch\.service'; then
    as_root systemctl start openvswitch
  else
    die "Open vSwitch is not running and no known systemd unit was found (openvswitch-switch or openvswitch)"
  fi
  for _ in $(seq 1 20); do
    if ovs-vsctl show >/dev/null 2>&1 || as_root ovs-vsctl show >/dev/null 2>&1; then
      echo "==> Open vSwitch is up"
      return 0
    fi
    sleep 0.5
  done
  die "started Open vSwitch but ovs-vsctl still cannot contact the database"
}

onos_container_state() {
  "${DOCKER[@]}" inspect -f '{{.State.Status}}' "${ONOS_CONTAINER}" 2>/dev/null || true
}

onos_openflow_listening() {
  ss -ltn 2>/dev/null | grep -q "${ONOS_HOST}:${ONOS_OF_PORT}"
}

ensure_onos_container() {
  detect_docker required || exit 1
  local state
  state="$(onos_container_state)"
  case "${state}" in
    running)
      echo "==> ONOS container '${ONOS_CONTAINER}' is already running; reusing it"
      ;;
    "")
      echo "==> ONOS container '${ONOS_CONTAINER}' is missing; running ./setup/setup_onos.sh"
      "${ROOT}/setup/setup_onos.sh"
      ;;
    *)
      echo "==> Starting ONOS container '${ONOS_CONTAINER}' (was ${state})"
      "${DOCKER[@]}" start "${ONOS_CONTAINER}" >/dev/null
      ;;
  esac
}

wait_onos_service() {
  echo "==> Waiting for ONOS REST and the OpenFlow listener (up to 180s)"
  local i
  for i in $(seq 1 60); do
    if curl -sS -f -u "${ONOS_USER}:${ONOS_PASSWORD}" "${ONOS_API}/devices" >/dev/null 2>&1 \
        && onos_openflow_listening; then
      echo "==> ONOS service is ready (REST and OpenFlow port ${ONOS_OF_PORT})"
      return 0
    fi
    sleep 3
  done
  die "ONOS service did not become ready (REST or OpenFlow listener). Recent logs: ${DOCKER[*]} logs --tail 100 ${ONOS_CONTAINER}"
}

available_device_count() {
  python3 - <<'PY'
import json, os, sys, urllib.request, base64
from topologies.active import DEVICE_IDS

url = os.environ.get("ONOS_API", "http://127.0.0.1:8181/onos/v1") + "/devices"
user = os.environ["ONOS_USER"]
password = os.environ["ONOS_PASSWORD"]
expected = set(DEVICE_IDS.values())
req = urllib.request.Request(url)
token = base64.b64encode(f"{user}:{password}".encode()).decode()
req.add_header("Authorization", f"Basic {token}")
try:
    with urllib.request.urlopen(req, timeout=5) as response:
        payload = json.load(response)
except Exception:
    print(0)
    raise SystemExit(0)
ids = {
    item.get("id")
    for item in (payload.get("devices") or [])
    if item.get("available")
}
print(len(ids & expected))
PY
}

integration_ready() {
  python3 - <<'PY'
import base64, json, os, urllib.request
from topologies.active import DEVICE_IDS, INTER_SWITCH_LINKS

api = os.environ.get("ONOS_API", "http://127.0.0.1:8181/onos/v1")
token = base64.b64encode(
    f"{os.environ['ONOS_USER']}:{os.environ['ONOS_PASSWORD']}".encode()
).decode()

def get(path):
    req = urllib.request.Request(api + path)
    req.add_header("Authorization", f"Basic {token}")
    with urllib.request.urlopen(req, timeout=5) as response:
        return json.load(response)

try:
    devices = get("/devices").get("devices") or []
    links = get("/links").get("links") or []
except Exception:
    raise SystemExit(1)
expected = set(DEVICE_IDS.values())
ready = {
    item.get("id")
    for item in devices
    if item.get("available")
    and item.get("id") in expected
    and (item.get("annotations") or {}).get("protocol") == "OF_13"
}
raise SystemExit(
    0 if len(ready) == len(expected) and len(links) == 2 * len(INTER_SWITCH_LINKS) else 1
)
PY
}

wait_integration() {
  echo "==> Waiting for ${EXPECTED_SWITCHES} OF_13 switches and ${EXPECTED_LINKS} directed links (up to 60s)"
  local i
  for i in $(seq 1 30); do
    if integration_ready; then
      echo "==> ONOS has ${EXPECTED_SWITCHES}/${EXPECTED_SWITCHES} OF_13 devices and ${EXPECTED_LINKS} directed links"
      return 0
    fi
    sleep 2
  done
  echo "ERROR: ONOS REST is up but the expected switches did not attach." >&2
  return 1
}

show_recent_onos_logs() {
  echo "==> Recent ONOS logs (bounded; not the full container history)"
  "${DOCKER[@]}" logs --tail 80 --since 15m "${ONOS_CONTAINER}" 2>&1 \
    | grep -E 'Leadership|not registered|Listening for OF|ERROR' \
    | tail -n 20 || true
}

recreate_onos_container() {
  detect_docker required || exit 1
  echo "==> Recreating only container '${ONOS_CONTAINER}'"
  "${DOCKER[@]}" rm -f "${ONOS_CONTAINER}" >/dev/null
  "${ROOT}/setup/setup_onos.sh"
}

recover_onos_once() {
  if [[ "${ONOS_RECOVERY_USED}" -eq 1 ]]; then
    die "ONOS still did not accept ${EXPECTED_SWITCHES} OF_13 switches and ${EXPECTED_LINKS} directed links after one container recreation."
  fi
  ONOS_RECOVERY_USED=1
  echo "==> Integration failed. Recreating the ONOS container once, then retrying Mininet."
  show_recent_onos_logs
  stop_mininet
  recreate_onos_container
  wait_onos_service
  start_mininet
  wait_integration || die "ONOS still did not accept ${EXPECTED_SWITCHES} OF_13 switches and ${EXPECTED_LINKS} directed links after one container recreation."
}

mininet_started_by_us() {
  local pid
  pid="$(read_pid || true)"
  [[ -n "${pid}" ]] && pid_alive "${pid}"
}

start_mininet() {
  if mininet_started_by_us; then
    echo "==> ${TOPOLOGY} is already running (pid $(read_pid))"
    return 0
  fi
  if as_root ovs-vsctl br-exists s1 2>/dev/null; then
    die "OVS bridge s1 already exists, but this script did not start it. Exit the interactive mininet> prompt or run: ./scripts/testbed.sh stop"
  fi
  echo "==> Clearing leftover Mininet/OVS state"
  as_root mn -c >/dev/null
  as_root mkdir -p "${RUN_DIR}"
  as_root chmod 700 "${RUN_DIR}"
  echo "==> Starting background ${TOPOLOGY}"
  as_root python3 "${ROOT}/scripts/run_main6s8h.py" \
    --pid-file "${PID_FILE}" \
    --ready-file "${READY_FILE}" \
    --log-file "${LOG_FILE}" \
    --controller-ip "${ONOS_HOST}" \
    --controller-port "${ONOS_OF_PORT}"
  local i pid
  for i in $(seq 1 60); do
    if as_root test -f "${READY_FILE}"; then
      pid="$(read_pid || true)"
      echo "==> ${TOPOLOGY} is up (pid ${pid:-unknown})"
      return 0
    fi
    pid="$(read_pid || true)"
    if [[ -n "${pid}" ]] && ! pid_alive "${pid}"; then
      show_log
      die "background Mininet exited before becoming ready"
    fi
    sleep 1
  done
  show_log
  die "timed out waiting for background Mininet"
}

install_baseline() {
  echo "==> Installing baseline forwarding"
  python3 "${ROOT}/forwarding/baseline_forwarding.py" install --timeout 40
}

stop_mininet() {
  local pid
  pid="$(read_pid || true)"
  if [[ -n "${pid}" ]] && pid_alive "${pid}"; then
    echo "==> Stopping background ${TOPOLOGY} (pid ${pid})"
    as_root kill -TERM "${pid}" 2>/dev/null || true
    local i
    for i in $(seq 1 20); do
      pid_alive "${pid}" || break
      sleep 0.5
    done
    if pid_alive "${pid}"; then
      echo "==> Mininet did not exit; sending KILL"
      as_root kill -KILL "${pid}" 2>/dev/null || true
    fi
  fi
  echo "==> Clearing Mininet/OVS datapath"
  as_root mn -c >/dev/null || true
  as_root rm -f "${PID_FILE}" "${READY_FILE}"
}

reset_fault_best_effort() {
  echo "==> Resetting any active catalogue fault"
  if as_root python3 -m faults.cli reset >/dev/null 2>&1; then
    return 0
  fi
  # Normal reset failed: try each catalogue scenario's canonical recovery.
  # Every forced reset is a no-op on resources that are already healthy.
  echo "==> Normal reset failed; recovering F1–F5 canonical resources"
  local scenario
  for scenario in F1 F2 F3 F4 F5; do
    as_root python3 -m faults.cli reset --force-scenario "${scenario}" >/dev/null 2>&1 || true
  done
}

remove_baseline_best_effort() {
  # main6s8h keeps its frozen protocol-v1 stop procedure. Other topologies
  # remove their rules while the switches are still connected: ONOS keeps
  # rules for disconnected DPIDs, and the main6s8h healthy gate counts every
  # org.coms6200.baseline flow, whichever device it is on.
  [[ "${TOPOLOGY}" != main6s8h ]] || return 0
  mininet_started_by_us || as_root ovs-vsctl br-exists s1 2>/dev/null || return 0
  echo "==> Removing ${TOPOLOGY} baseline flows"
  python3 "${ROOT}/forwarding/baseline_forwarding.py" remove >/dev/null 2>&1 \
    || echo "==> Baseline flow removal failed (is ONOS up?); continuing"
}

cmd_start() {
  start_ovs
  ensure_onos_container
  wait_onos_service
  start_mininet
  if ! wait_integration; then
    recover_onos_once
  fi
  install_baseline
  local flows stop_cmd="./scripts/testbed.sh stop"
  flows="$(python3 -c 'from forwarding.baseline_forwarding import expected_flow_count; print(expected_flow_count())')"
  [[ "${TOPOLOGY}" == main6s8h ]] || stop_cmd="COMS6200_TOPOLOGY=${TOPOLOGY} ${stop_cmd}"
  echo
  echo "Testbed is up: OVS + ONOS + ${TOPOLOGY} + ${flows} baseline flows."
  echo
  cat <<'EOF'
Next:
  ./scripts/testbed.sh inject F1    # or F2 F3 F4 F5
  # then ask the agent a symptom, not the fault name

EOF
  cat <<EOF
Stop later with:
  ${stop_cmd}
EOF
}

cmd_stop() {
  local with_onos="${1:-0}"
  detect_docker optional || true
  reset_fault_best_effort
  remove_baseline_best_effort
  stop_mininet
  if [[ "${with_onos}" -eq 1 ]]; then
    [[ "${#DOCKER[@]}" -gt 0 ]] || die "cannot stop ONOS: docker is not usable"
    echo "==> Stopping ONOS container '${ONOS_CONTAINER}' (--with-onos)"
    "${DOCKER[@]}" stop "${ONOS_CONTAINER}" >/dev/null 2>&1 || true
  else
    echo "==> Leaving ONOS container '${ONOS_CONTAINER}' running"
  fi
  echo "==> Testbed stopped (Open vSwitch left running)"
}

cmd_inject() {
  local scenario
  scenario="$(normalize_scenario "${1:-}" || true)"
  [[ -n "${scenario}" ]] || die "scenario must be F1–F5 (also accepted: f1 or 1). Catalogue v1 has no F6+."
  mininet_started_by_us || as_root ovs-vsctl br-exists s1 2>/dev/null || \
    die "${TOPOLOGY} is not running. Start it with: ./scripts/testbed.sh start"
  echo "==> Resetting any active fault before inject ${scenario}"
  as_root python3 -m faults.cli reset || true
  echo "==> Injecting ${scenario}"
  as_root python3 -m faults.cli inject --scenario "${scenario}"
  echo
  echo "Do not tell the agent the scenario id. Prompt with a symptom only."
}

cmd_reset() {
  as_root python3 -m faults.cli reset
}

cmd_status() {
  echo "===== testbed status ====="
  echo "Topology: ${TOPOLOGY}"
  if ovs-vsctl show >/dev/null 2>&1 || as_root ovs-vsctl show >/dev/null 2>&1; then
    echo "OVS: up"
  else
    echo "OVS: down"
  fi
  if detect_docker optional >/dev/null; then
    "${DOCKER[@]}" ps -a --filter "name=${ONOS_CONTAINER}" \
      --format 'ONOS: {{.Status}}' 2>/dev/null || echo "ONOS: unknown"
  else
    echo "ONOS: docker not usable"
  fi
  local pid
  pid="$(read_pid || true)"
  if [[ -n "${pid}" ]] && pid_alive "${pid}"; then
    echo "Mininet: running pid ${pid} (background helper)"
  elif as_root ovs-vsctl br-exists s1 2>/dev/null; then
    echo "Mininet: s1 present (likely an interactive mn CLI, not this helper)"
  else
    echo "Mininet: not running"
  fi
  if curl -sS -f -u "${ONOS_USER}:${ONOS_PASSWORD}" "${ONOS_API}/devices" >/dev/null 2>&1; then
    export ONOS_API
    echo "ONOS devices available: $(available_device_count)/${EXPECTED_SWITCHES}"
  else
    echo "ONOS REST: not ready"
  fi
  echo "----- faults.cli status -----"
  as_root python3 -m faults.cli status || true
}

reject_extra() {
  [[ "${#}" -eq 0 ]] || die "unexpected argument '${1}'"
}

main() {
  local cmd="${1:-}"
  shift || true
  case "${cmd}" in
    start)
      reject_extra "$@"
      cmd_start
      ;;
    stop)
      local with_onos=0
      while [[ "${#}" -gt 0 ]]; do
        case "$1" in
          --with-onos) with_onos=1 ;;
          *) die "unknown argument '$1'. Normal stop leaves ONOS running. Use: ./scripts/testbed.sh stop --with-onos" ;;
        esac
        shift
      done
      cmd_stop "${with_onos}"
      ;;
    inject)
      [[ "${#}" -ge 1 ]] || die "inject requires a scenario (F1–F5)"
      local scenario="$1"
      shift
      reject_extra "$@"
      cmd_inject "${scenario}"
      ;;
    reset)
      reject_extra "$@"
      cmd_reset
      ;;
    status)
      reject_extra "$@"
      cmd_status
      ;;
    -h|--help|help|"") usage ;;
    *)
      usage >&2
      die "unknown command '${cmd}'"
      ;;
  esac
}

main "$@"
