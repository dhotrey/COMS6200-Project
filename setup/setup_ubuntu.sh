#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> COMS6200 Ubuntu environment setup"
echo "==> Repository root: ${ROOT}"

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
  echo "ERROR: apt is not available. This script targets Ubuntu/Debian."
  exit 1
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

echo "==> Enabling Open vSwitch service"
$SUDO systemctl enable openvswitch-switch

echo "==> Starting Open vSwitch service"
$SUDO systemctl start openvswitch-switch

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
