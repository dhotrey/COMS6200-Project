#!/usr/bin/env bash
set -euo pipefail

# COMS6200 M0 environment setup.
#
# Historical filename. This script is not Ubuntu-only.
# Ubuntu 24.04 is the verified reference environment.
# The UQ-provided Kali VM is a supported course compatibility target.
# Other apt-based Debian-family distributions may work; package names can
# differ. This is not universal Linux installation support.
#
# Always run ./setup/verify_environment.sh after this script. Capability
# checks, not distribution name, determine whether the environment is usable.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> COMS6200 environment setup"
echo "==> Repository root: ${ROOT}"
echo "==> Verified reference: Ubuntu 24.04.4 LTS"
echo "==> Course compatibility target: UQ-provided Kali VM"
echo "==> Automatic installation currently supports apt-based systems only"

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "ERROR: This setup script must be run on Linux."
  echo "Detected kernel: $(uname -s)"
  echo "Cursor, Git, documentation, and Python editing may be done on macOS or Windows,"
  echo "but Mininet and Open vSwitch must be installed in a Linux environment."
  exit 1
fi

if [[ -f /etc/os-release ]]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  echo "==> Detected operating system: ${PRETTY_NAME:-unknown}"
  echo "==> Distribution ID: ${ID:-unknown}"
  echo "==> Version: ${VERSION:-unknown}"
else
  echo "==> Detected operating system: Linux"
  echo "WARNING: /etc/os-release not found; cannot report a precise distribution name."
  uname -a
fi

if ! command -v apt >/dev/null 2>&1; then
  echo "ERROR: apt is not available."
  echo "Automatic installation currently supports apt-based systems only."
  echo "You may install equivalent dependencies manually, then run:"
  echo "  ./setup/verify_environment.sh"
  exit 1
fi

echo "==> Package manager: apt"

if [[ "${ID:-}" == "ubuntu" ]]; then
  echo "==> Ubuntu detected; this matches the project's installation reference family"
elif [[ "${ID:-}" == "debian" || "${ID:-}" == "kali" ]]; then
  echo "==> Debian-family distribution detected (${PRETTY_NAME:-${ID}})."
  if [[ "${ID:-}" == "kali" ]]; then
    echo "==> UQ Kali VM: supported course compatibility target, not a fully"
    echo "==> milestone-verified substitute for Ubuntu 24.04."
  fi
  echo "==> The script will continue, but package availability can differ from Ubuntu 24.04."
elif [[ -n "${ID:-}" ]]; then
  echo "==> WARNING: detected distribution is ${PRETTY_NAME:-${ID}}, not the Ubuntu 24.04 reference."
  echo "==> Continuing because apt is available. Run verify_environment.sh afterwards."
fi

if [[ "${EUID}" -eq 0 ]]; then
  SUDO=""
  echo "==> Running as root; privileged commands will not use sudo"
else
  if ! command -v sudo >/dev/null 2>&1; then
    echo "ERROR: sudo is required for non-root users."
    exit 1
  fi
  SUDO="sudo"
  echo "==> Running as a non-root user; privileged commands will use sudo"
fi

echo "==> Updating apt package index"
$SUDO apt update

echo "==> Installing required packages"
$SUDO apt install -y \
  git \
  mininet \
  openvswitch-switch \
  iperf3 \
  python3 \
  python3-pip \
  python3-venv \
  jq \
  curl

if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files --type=service 2>/dev/null | grep -q '^openvswitch-switch\.service'; then
  echo "==> Enabling Open vSwitch service"
  $SUDO systemctl enable openvswitch-switch
  echo "==> Starting Open vSwitch service"
  $SUDO systemctl start openvswitch-switch
else
  echo "WARNING: systemd unit openvswitch-switch was not found."
  echo "The Open vSwitch package may still have been installed."
  echo "Start Open vSwitch using this distribution's service name if needed,"
  echo "then run ./setup/verify_environment.sh"
fi

if [[ -d "${ROOT}/.venv" ]]; then
  echo "==> Python virtual environment .venv already exists; skipping creation"
else
  echo "==> Creating Python virtual environment .venv"
  python3 -m venv "${ROOT}/.venv"
fi

echo
echo "==> Setup script finished."
echo
echo "Ryu, OS-Ken, the OpenAI SDK, and other LLM libraries were not installed."
echo "Controller and agent dependencies are deferred to later milestones."
echo
echo "This script does not activate the virtual environment in your current shell."
echo "Activation in a child process would not persist. To activate it, run:"
echo
echo "  source .venv/bin/activate"
echo
echo "Next, verify the environment:"
echo
echo "  ./setup/verify_environment.sh"
echo
