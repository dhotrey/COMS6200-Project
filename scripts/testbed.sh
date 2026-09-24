#!/usr/bin/env bash
# Session helper: start/stop main6s8h + ONOS, and inject/reset F1–F5.
#
# Does not replace setup_ubuntu.sh / setup_onos.sh. Those still install the
# environment. This script only brings a previously installed testbed up and
# down. It is not an LLM tool and does not send scenario IDs to the agent.
#
#   ./scripts/testbed.sh start
#   ./scripts/testbed.sh inject F1
#   ./scripts/testbed.sh reset
#   ./scripts/testbed.sh stop

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

usage() {
  cat <<'EOF'
Usage:
  ./scripts/testbed.sh start
  ./scripts/testbed.sh stop
  ./scripts/testbed.sh inject F1|F2|F3|F4|F5
  ./scripts/testbed.sh reset
  ./scripts/testbed.sh status

start  Open vSwitch, ONOS, background main6s8h, then install baseline flows.
stop   Reset any active fault, stop Mininet, clear OVS Mininet state, stop ONOS.
inject Reset an active catalogue fault if needed, then inject F1–F5.
reset  Clear the active catalogue fault only (Mininet/ONOS stay up).
status Show ONOS, Mininet, and fault-injector state.

ONOS REST defaults to onos/rocks. Override with ONOS_USER / ONOS_PASSWORD.
The ONOS container must already exist (./setup/setup_onos.sh).
EOF
}

die() { echo "ERROR: $*" >&2; exit 1; }

as_root() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  else
    sudo --preserve-env=ONOS_USER,ONOS_PASSWORD,ONOS_URL,ONOS_HOST,ONOS_OF_PORT,PYTHONPATH "$@"
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

start_onos() {
  detect_docker required || exit 1
  local state
  state="$("${DOCKER[@]}" inspect -f '{{.State.Status}}' "${ONOS_CONTAINER}" 2>/dev/null || true)"
  case "${state}" in
    running)
      echo "==> ONOS container '${ONOS_CONTAINER}' is already running"
      ;;
    "")
      die "ONOS container '${ONOS_CONTAINER}' was not found. Run ./setup/setup_onos.sh once, then re-run start."
      ;;
    *)
      echo "==> Starting ONOS container '${ONOS_CONTAINER}' (was ${state})"
      "${DOCKER[@]}" start "${ONOS_CONTAINER}" >/dev/null
      ;;
  esac
}

wait_onos_rest() {
  echo "==> Waiting for ONOS REST on ${ONOS_API} (up to 180s)"
  local i
  for i in $(seq 1 60); do
    if curl -sS -f -u "${ONOS_USER}:${ONOS_PASSWORD}" "${ONOS_API}/devices" >/dev/null 2>&1; then
      echo "==> ONOS REST is up"
      return 0
    fi
    sleep 3
  done
  die "ONOS REST did not become ready. Check: ${DOCKER[*]} logs ${ONOS_CONTAINER}"
}

available_device_count() {
  python3 - <<'PY'
import json, os, sys, urllib.error, urllib.request, base64

url = os.environ.get("ONOS_API", "http://127.0.0.1:8181/onos/v1") + "/devices"
user = os.environ["ONOS_USER"]
password = os.environ["ONOS_PASSWORD"]
expected = {f"of:000000000000000{i}" for i in range(1, 7)}
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

wait_six_devices() {
  echo "==> Waiting for ONOS to see s1–s6 (up to 60s)"
  export ONOS_API
  local n i
  for i in $(seq 1 30); do
    n="$(available_device_count)"
    if [[ "${n}" == "6" ]]; then
      echo "==> ONOS has 6/6 main6s8h devices"
      return 0
    fi
    sleep 2
  done
  die "ONOS still does not have all six switches (last count ${n:-0}). Is Mininet up?"
}

mininet_started_by_us() {
  local pid
  pid="$(read_pid || true)"
  [[ -n "${pid}" ]] && pid_alive "${pid}"
}

start_mininet() {
  if mininet_started_by_us; then
    echo "==> main6s8h is already running (pid $(read_pid))"
    return 0
  fi
  if as_root ovs-vsctl br-exists s1 2>/dev/null; then
    die "OVS bridge s1 already exists, but this script did not start it. Exit the interactive mininet> prompt or run: ./scripts/testbed.sh stop"
  fi
  echo "==> Clearing leftover Mininet/OVS state"
  as_root mn -c >/dev/null
  as_root mkdir -p "${RUN_DIR}"
  as_root chmod 700 "${RUN_DIR}"
  echo "==> Starting background main6s8h"
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
      echo "==> main6s8h is up (pid ${pid:-unknown})"
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
    echo "==> Stopping background main6s8h (pid ${pid})"
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

cmd_start() {
  start_ovs
  start_onos
  wait_onos_rest
  start_mininet
  wait_six_devices
  install_baseline
  cat <<EOF

Testbed is up: OVS + ONOS + main6s8h + 56 baseline flows.

Next:
  ./scripts/testbed.sh inject F1    # or F2 F3 F4 F5
  # then ask the agent a symptom, not the fault name

Stop later with:
  ./scripts/testbed.sh stop
EOF
}

cmd_stop() {
  detect_docker optional || true
  reset_fault_best_effort
  stop_mininet
  if [[ "${#DOCKER[@]}" -gt 0 ]]; then
    echo "==> Stopping ONOS container '${ONOS_CONTAINER}'"
    "${DOCKER[@]}" stop "${ONOS_CONTAINER}" >/dev/null 2>&1 || true
  fi
  echo "==> Testbed stopped (Open vSwitch left running)"
}

cmd_inject() {
  local scenario
  scenario="$(normalize_scenario "${1:-}" || true)"
  [[ -n "${scenario}" ]] || die "scenario must be F1–F5 (also accepted: f1 or 1). Catalogue v1 has no F6+."
  mininet_started_by_us || as_root ovs-vsctl br-exists s1 2>/dev/null || \
    die "main6s8h is not running. Start it with: ./scripts/testbed.sh start"
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
    echo "ONOS devices available: $(available_device_count)/6"
  else
    echo "ONOS REST: not ready"
  fi
  echo "----- faults.cli status -----"
  as_root python3 -m faults.cli status || true
}

main() {
  local cmd="${1:-}"
  shift || true
  case "${cmd}" in
    start) cmd_start ;;
    stop) cmd_stop ;;
    inject)
      [[ "${#}" -ge 1 ]] || die "inject requires a scenario (F1–F5)"
      cmd_inject "$1"
      ;;
    reset) cmd_reset ;;
    status) cmd_status ;;
    -h|--help|help|"") usage ;;
    *)
      usage >&2
      die "unknown command '${cmd}'"
      ;;
  esac
}

main "$@"
