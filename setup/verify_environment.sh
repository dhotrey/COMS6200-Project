#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

TARGET_OS_NAME="Ubuntu"
TARGET_OS_VERSION="24.04"
TARGET_PYTHON="3.12"

pass_count=0
fail_count=0
warn_count=0
overall_ok=1

pass() {
  echo "[PASS]    $1"
  pass_count=$((pass_count + 1))
}

fail() {
  echo "[FAIL]    $1"
  fail_count=$((fail_count + 1))
  overall_ok=0
}

warn() {
  echo "[WARNING] $1"
  warn_count=$((warn_count + 1))
}

info() {
  echo "[INFO]    $1"
}

command_version() {
  local cmd="$1"
  shift
  if ! command -v "$cmd" >/dev/null 2>&1; then
    return 1
  fi
  "$cmd" "$@" 2>&1 | head -n 1
}

echo "========================================"
echo "COMS6200 environment verification"
echo "Repository root: ${ROOT}"
echo "========================================"
echo
echo "This script does not install or modify packages."
echo "It checks the current host and runs one BASIC Mininet/OVS test."
echo "Passing this script is NOT evidence that Ryu, OpenFlow 1.3,"
echo "telemetry, fault injection, or the LLM agent are working."
echo

kernel="$(uname -s)"
info "Kernel: ${kernel} $(uname -r)"

os_name="unknown"
os_version="unknown"
os_pretty="unknown"

if [[ -f /etc/os-release ]]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  os_name="${ID:-unknown}"
  os_version="${VERSION_ID:-unknown}"
  os_pretty="${PRETTY_NAME:-unknown}"
fi

info "Detected OS: ${os_pretty}"

if [[ "$kernel" != "Linux" ]]; then
  fail "Operating system is not Linux (detected: ${kernel})"
else
  pass "Operating system is Linux"
fi

if [[ "$os_pretty" == Ubuntu* ]] || [[ "$os_name" == "ubuntu" ]]; then
  pass "Distribution is Ubuntu (${os_pretty})"
  case "$os_version" in
    "${TARGET_OS_VERSION}"*)
      pass "Ubuntu version is ${os_version} (target: ${TARGET_OS_VERSION}.x LTS)"
      ;;
    *)
      warn "Ubuntu version is ${os_version}; current target is ${TARGET_OS_NAME} ${TARGET_OS_VERSION}.4 LTS"
      ;;
  esac
else
  fail "Distribution is not Ubuntu (detected: ${os_pretty})"
fi

if python3_version="$(command_version python3 --version)"; then
  info "Python: ${python3_version}"
  if python3 -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)" 2>/dev/null; then
    pass "Python version is 3.12.x (${python3_version})"
  else
    warn "Python version is ${python3_version}; current target is Python ${TARGET_PYTHON}.3"
  fi
else
  fail "python3 is not installed or not on PATH"
fi

if git_version="$(command_version git --version)"; then
  pass "Git is available (${git_version})"
else
  fail "git is not installed or not on PATH"
fi

if mininet_version="$(command_version mn --version)"; then
  pass "Mininet is available (${mininet_version})"
else
  fail "Mininet (mn) is not installed or not on PATH"
fi

if ovs_version="$(command_version ovs-vsctl --version)"; then
  pass "Open vSwitch is available (${ovs_version})"
else
  fail "Open vSwitch (ovs-vsctl) is not installed or not on PATH"
fi

if iperf_version="$(command_version iperf3 --version)"; then
  pass "iperf3 is available (${iperf_version})"
else
  fail "iperf3 is not installed or not on PATH"
fi

if command -v systemctl >/dev/null 2>&1; then
  ovs_active="$(systemctl is-active openvswitch-switch 2>/dev/null || true)"
  if [[ "$ovs_active" == "active" ]]; then
    pass "Open vSwitch service is active (systemctl is-active openvswitch-switch)"
  else
    fail "Open vSwitch service is not active (systemctl is-active openvswitch-switch => ${ovs_active:-unknown})"
  fi
else
  fail "systemctl is not available; cannot check Open vSwitch service status"
fi

if [[ "${EUID}" -eq 0 ]]; then
  SUDO=""
  info "Running as root; privileged commands will not use sudo"
else
  if ! command -v sudo >/dev/null 2>&1; then
    echo "ERROR: sudo is required for non-root users."
    exit 1
  fi
  SUDO="sudo"
  info "Running as a non-root user; privileged commands will use sudo"
fi

if [[ -n "${SUDO}" ]]; then
  mn_cmd="${SUDO} mn --switch ovsbr --test pingall"
else
  mn_cmd="mn --switch ovsbr --test pingall"
fi

echo
echo "----------------------------------------"
echo "Basic Mininet / Open vSwitch test"
echo "Command: ${mn_cmd}"
echo "This only checks that Mininet can start an OVS bridge and ping hosts."
echo "It does NOT test Ryu, OpenFlow 1.3, or the planned project topology."
echo "----------------------------------------"

if [[ "$kernel" != "Linux" ]]; then
  fail "Skipping Mininet pingall test because this host is not Linux"
elif ! command -v mn >/dev/null 2>&1; then
  fail "Skipping Mininet pingall test because mn is not available"
else
  set +e
  $SUDO mn --switch ovsbr --test pingall
  mn_status=$?
  set -e
  if [[ $mn_status -eq 0 ]]; then
    pass "Basic Mininet pingall test succeeded"
  else
    fail "Basic Mininet pingall test failed (exit status ${mn_status})"
  fi
fi

echo
echo "========================================"
echo "Verification summary"
echo "========================================"
echo "PASS:     ${pass_count}"
echo "FAIL:     ${fail_count}"
echo "WARNING:  ${warn_count}"
echo
echo "Interpretation:"
echo "- This is a BASIC Mininet/OVS environment check only."
echo "- It is not evidence that the final Ryu/OpenFlow architecture works."
echo "- Ryu, OS-Ken, telemetry, faults, the LLM agent, and the baseline"
echo "  have not been installed or tested by this script."
echo

if [[ $overall_ok -eq 1 ]]; then
  echo "Overall: SUCCESS — required environment checks passed."
  if [[ $warn_count -gt 0 ]]; then
    echo "Review the WARNING items above before treating this as the target environment."
  fi
  exit 0
fi

echo "Overall: FAILURE — one or more required checks did not succeed."
echo "Do not treat this host as a verified project environment until the FAIL items are resolved."
exit 1
