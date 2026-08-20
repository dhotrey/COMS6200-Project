#!/usr/bin/env bash
set -euo pipefail

# Reproducible ONOS controller setup for the COMS6200 project.
#
# This script deploys ONOS 2.7.0 from the official pre-built Docker image.
# It is idempotent: re-running it will not reinstall or recreate a healthy
# container.
#
# It NEVER touches Mininet, Open vSwitch, the system Python, or the project
# .venv. It installs no Java on the host. It embeds no passwords.
#
# See docs/setup/onos-setup.md for the tested environment and verification
# procedure.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ONOS_VERSION="2.7.0"
ONOS_IMAGE="onosproject/onos:${ONOS_VERSION}"
ONOS_CONTAINER="onos"

# Bind to loopback only. ONOS must not be exposed publicly.
BIND_ADDR="127.0.0.1"
OF_PORT="6653"
REST_PORT="8181"
CLI_PORT="8101"

# Conservative limits for a small (~1 GiB) server. Raise on larger hosts.
CONTAINER_MEMORY="640m"
CONTAINER_MEMORY_SWAP="1280m"
JVM_OPTS="-Xms64m -Xmx256m -XX:+UseSerialGC"

# Minimum apps for OpenFlow southbound, device/link/host discovery and GUI.
# Reactive forwarding (fwd) is intentionally excluded: the project topology is
# physically cyclic and needs deterministic forwarding, designed separately.
ONOS_APPS="drivers,openflow,gui2"

info()  { echo "==> $1"; }
fail()  { echo "ERROR: $1" >&2; exit 1; }

if [[ "$(uname -s)" != "Linux" ]]; then
  fail "This script must run on the Linux server that hosts Mininet/OVS. Detected: $(uname -s)"
fi

if [[ -r /etc/os-release ]]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  info "Detected OS: ${PRETTY_NAME:-unknown}"
  if [[ "${ID:-}" != "ubuntu" ]]; then
    echo "    Note: Ubuntu 24.04 is the verified reference. Continuing anyway."
  fi
fi

if [[ "${EUID}" -eq 0 ]]; then
  SUDO=""
  info "Running as root; not using sudo"
else
  command -v sudo >/dev/null 2>&1 || fail "sudo is required for non-root users."
  SUDO="sudo"
  info "Running as $(whoami); privileged commands will use sudo"
fi

if ! command -v docker >/dev/null 2>&1; then
  fail "docker is not installed.
This script does not install a container runtime automatically.
Install Docker on the server first, then re-run this script.
Alternative: install the ONOS ${ONOS_VERSION} tar.gz under /opt/onos, which
additionally requires a Java 11 JDK on the host."
fi

if ! ${SUDO} docker info >/dev/null 2>&1; then
  fail "docker is installed but not usable (daemon not running, or permission denied)."
fi

info "Docker: $(${SUDO} docker --version)"

# --- Image ------------------------------------------------------------------

if ${SUDO} docker image inspect "${ONOS_IMAGE}" >/dev/null 2>&1; then
  info "Image ${ONOS_IMAGE} already present; skipping pull"
else
  info "Pulling ${ONOS_IMAGE} (about 1.5 GB unpacked)"
  ${SUDO} docker pull "${ONOS_IMAGE}"
fi

# --- Container --------------------------------------------------------------

container_state="$(${SUDO} docker inspect -f '{{.State.Status}}' "${ONOS_CONTAINER}" 2>/dev/null || true)"

case "${container_state}" in
  running)
    info "Container '${ONOS_CONTAINER}' is already running; leaving it untouched"
    ;;
  "")
    info "Creating container '${ONOS_CONTAINER}'"
    ${SUDO} docker run -d \
      --name "${ONOS_CONTAINER}" \
      --memory="${CONTAINER_MEMORY}" \
      --memory-swap="${CONTAINER_MEMORY_SWAP}" \
      -p "${BIND_ADDR}:${OF_PORT}:${OF_PORT}" \
      -p "${BIND_ADDR}:${REST_PORT}:${REST_PORT}" \
      -p "${BIND_ADDR}:${CLI_PORT}:${CLI_PORT}" \
      -e ONOS_APPS="${ONOS_APPS}" \
      -e JAVA_OPTS="${JVM_OPTS}" \
      -e JAVA_TOOL_OPTIONS="${JVM_OPTS}" \
      "${ONOS_IMAGE}" >/dev/null
    ;;
  *)
    info "Container '${ONOS_CONTAINER}' exists in state '${container_state}'; starting it"
    ${SUDO} docker start "${ONOS_CONTAINER}" >/dev/null
    ;;
esac

# --- Wait for the OpenFlow listener ----------------------------------------

info "Waiting for the ONOS OpenFlow listener on ${BIND_ADDR}:${OF_PORT} (up to 180s)"
ready=0
for _ in $(seq 1 36); do
  if ${SUDO} docker logs "${ONOS_CONTAINER}" 2>&1 |
       grep -q "Listening for OF switch connections on ${OF_PORT}"; then
    ready=1
    break
  fi
  sleep 5
done

if [[ "${ready}" -eq 1 ]]; then
  info "ONOS is listening for OpenFlow connections on ${OF_PORT}"
else
  echo "WARNING: did not observe the OpenFlow listener log line within 180s." >&2
  echo "         Inspect: docker logs ${ONOS_CONTAINER}" >&2
fi

${SUDO} docker ps --filter "name=${ONOS_CONTAINER}" \
  --format '    {{.ID}}  {{.Image}}  {{.Status}}  {{.Ports}}'

# --- Next steps -------------------------------------------------------------

cat <<EOF

ONOS ${ONOS_VERSION} setup complete.

Ports (loopback only):
  ${BIND_ADDR}:${OF_PORT}   OpenFlow
  ${BIND_ADDR}:${REST_PORT}   REST API and GUI
  ${BIND_ADDR}:${CLI_PORT}   Karaf CLI over SSH

Next steps:

  1. Verify the controller:
       ./scripts/verify_onos.sh

  2. Set REST credentials in your shell (never commit them):
       export ONOS_USER=onos
       export ONOS_PASSWORD='<your ONOS REST password>'

  3. Launch the main project topology:
       sudo mn -c
       sudo mn --custom topologies/main_topology.py \\
         --topo main6s8h \\
         --controller=remote,ip=127.0.0.1,port=${OF_PORT} \\
         --switch=ovsk

  4. Collect OVS-side evidence from another shell:
       sudo ./scripts/verify_main_openflow.sh

  5. Clean up Mininet after exiting:
       sudo mn -c

Stop ONOS with:  docker stop ${ONOS_CONTAINER}
Start it again:  docker start ${ONOS_CONTAINER}

Reactive forwarding (org.onosproject.fwd) is intentionally NOT activated.
Host pingall is expected to fail until deterministic forwarding is implemented.
EOF
