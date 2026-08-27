#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

REFERENCE_OS_NAME="Ubuntu"
REFERENCE_OS_VERSION="24.04"
REFERENCE_PYTHON="3.12.3"

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

unit_exists() {
  local unit="$1"
  command -v systemctl >/dev/null 2>&1 || return 1
  systemctl list-unit-files --type=service 2>/dev/null | grep -q "^${unit}\.service"
}

echo "========================================"
echo "COMS6200 environment verification"
echo "Repository root: ${ROOT}"
echo "========================================"
echo
echo "This script does not install or modify packages."
echo "It checks whether this Linux host has the capabilities required"
echo "for the M0 Mininet/Open vSwitch workload."
echo "Passing this script is NOT evidence that Ryu, OS-Ken, OpenFlow 1.3,"
echo "telemetry, fault injection, or the LLM agent are working."
echo
info "Verified reference environment: ${REFERENCE_OS_NAME} ${REFERENCE_OS_VERSION}.4 LTS, Python ${REFERENCE_PYTHON}"
echo

kernel="$(uname -s)"
info "Kernel: ${kernel} $(uname -r)"

os_id="unknown"
os_version="unknown"
os_pretty="unknown"

if [[ -f /etc/os-release ]]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  os_id="${ID:-unknown}"
  os_version="${VERSION_ID:-unknown}"
  os_pretty="${PRETTY_NAME:-unknown}"
  info "Distribution: ${os_pretty}"
  info "Distribution ID: ${os_id}  Version: ${os_version}"
else
  info "Distribution: unknown (/etc/os-release not found)"
fi

if [[ "$kernel" != "Linux" ]]; then
  fail "Linux kernel is required (detected: ${kernel})"
else
  pass "Linux kernel is present"
fi

case "${os_id}" in
  ubuntu)
    if [[ "${os_pretty}" == *"${REFERENCE_OS_VERSION}.4"* ]] || [[ "${os_version}" == "${REFERENCE_OS_VERSION}" ]]; then
      info "Distribution matches the verified Ubuntu ${REFERENCE_OS_VERSION}.x reference"
    else
      warn "Ubuntu ${os_version} differs from the verified reference Ubuntu ${REFERENCE_OS_VERSION}.4 LTS"
    fi
    ;;
  debian|kali)
    if [[ "${os_id}" == "kali" ]]; then
      info "UQ Kali VM is a supported course compatibility target. Milestone evidence is still Ubuntu-based unless separately recorded."
    else
      info "Debian-family distribution detected (${os_pretty}). Compatibility is determined by capability checks, not distribution name."
    fi
    ;;
  unknown)
    if [[ "$kernel" == "Linux" ]]; then
      warn "Linux distribution could not be identified. Compatibility is determined by capability checks."
    fi
    ;;
  *)
    if [[ "$kernel" == "Linux" ]]; then
      warn "Distribution is ${os_pretty}; verified reference is Ubuntu ${REFERENCE_OS_VERSION}.4 LTS. Compatibility is determined by capability checks."
    fi
    ;;
esac

if python3_version="$(command_version python3 --version)"; then
  if python3 -c "import sys; raise SystemExit(0 if sys.version_info[0] == 3 else 1)" 2>/dev/null; then
    pass "python3 is available (${python3_version})"
    if python3 -c "import sys; raise SystemExit(0 if sys.version_info[:3] == (3, 12, 3) else 1)" 2>/dev/null; then
      info "Python version matches the verified reference (${REFERENCE_PYTHON})"
    else
      warn "Python version is ${python3_version}; verified reference is Python ${REFERENCE_PYTHON}. This is not an automatic failure. Controller compatibility has not been verified."
    fi
  else
    fail "python3 is present but is not Python 3 (${python3_version})"
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
  pass "Open vSwitch tools are available (${ovs_version})"
else
  fail "Open vSwitch (ovs-vsctl) is not installed or not on PATH"
fi

if iperf_version="$(command_version iperf3 --version)"; then
  pass "iperf3 is available (${iperf_version})"
else
  fail "iperf3 is not installed or not on PATH"
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

ovs_runtime_ok=0
if command -v ovs-vsctl >/dev/null 2>&1; then
  if ovs-vsctl show >/dev/null 2>&1 || $SUDO ovs-vsctl show >/dev/null 2>&1; then
    ovs_runtime_ok=1
    pass "Open vSwitch runtime is operational (ovs-vsctl can contact the database)"
  fi
fi

if command -v systemctl >/dev/null 2>&1 && unit_exists "openvswitch-switch"; then
  ovs_active="$(systemctl is-active openvswitch-switch 2>/dev/null || true)"
  if [[ "$ovs_active" == "active" ]]; then
    info "systemd unit openvswitch-switch is active"
  elif [[ "$ovs_runtime_ok" -eq 1 ]]; then
    warn "systemd unit openvswitch-switch is ${ovs_active:-unknown}, but Open vSwitch runtime is operational"
  else
    fail "Open vSwitch runtime is not operational (systemctl is-active openvswitch-switch => ${ovs_active:-unknown})"
  fi
else
  info "Ubuntu-style systemd unit openvswitch-switch was not found; using Open vSwitch runtime capability instead"
  if [[ "$ovs_runtime_ok" -ne 1 ]]; then
    fail "Open vSwitch runtime is not operational (ovs-vsctl cannot contact the database)"
  fi
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
echo "- This is a capability-based M0 Mininet/OVS check, not a distribution-name check."
echo "- Ubuntu ${REFERENCE_OS_VERSION}.4 LTS is the verified reference environment."
echo "- The UQ-provided Kali VM is a supported course compatibility target."
echo "- Other Linux distributions may PASS if required capabilities work."
echo "- This is not evidence that Ryu, OS-Ken, or OpenFlow 1.3 controller integration works."
echo "- Ryu, OS-Ken, telemetry, faults, the LLM agent, and the baseline"
echo "  have not been installed or tested by this script."
echo

if [[ $overall_ok -eq 1 ]]; then
  echo "Overall: SUCCESS — required Mininet/Open vSwitch capability checks passed."
  if [[ $warn_count -gt 0 ]]; then
    echo "Review the WARNING items above. Warnings mean this host differs from the"
    echo "verified reference environment; they do not by themselves mean failure."
  fi
  exit 0
fi

echo "Overall: FAILURE — one or more required capability checks did not succeed."
echo "Do not treat this host as a usable M0 Mininet/OVS environment until the FAIL items are resolved."
exit 1
