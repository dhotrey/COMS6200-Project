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
  case "${ID:-}" in
    ubuntu)
      echo "    Ubuntu is the verified reference environment."
      ;;
    kali)
      echo "    UQ Kali VM is a supported course compatibility target."
      echo "    It is not a substitute for Ubuntu 24.04 milestone evidence."
      ;;
    *)
      echo "    Note: Ubuntu 24.04 is the verified reference. Continuing anyway."
      ;;
  esac
fi

# Docker access is capability-based. Mininet is not started here and still
# typically requires root (sudo mn ...). This script does not add the user to
# the docker group or change socket permissions.
# shellcheck source=docker_access.sh
. "${ROOT}/setup/docker_access.sh"
detect_docker required || exit 1

info "Docker: $("${DOCKER[@]}" --version)"

# --- Image ------------------------------------------------------------------

if "${DOCKER[@]}" image inspect "${ONOS_IMAGE}" >/dev/null 2>&1; then
  info "Image ${ONOS_IMAGE} already present; skipping pull"
else
  info "Pulling ${ONOS_IMAGE} (about 1.5 GB unpacked)"
  "${DOCKER[@]}" pull "${ONOS_IMAGE}"
fi

# --- Container --------------------------------------------------------------

container_state="$("${DOCKER[@]}" inspect -f '{{.State.Status}}' "${ONOS_CONTAINER}" 2>/dev/null || true)"

case "${container_state}" in
  running)
    info "Container '${ONOS_CONTAINER}' is already running; leaving it untouched"
    ;;
  "")
    info "Creating container '${ONOS_CONTAINER}'"
    "${DOCKER[@]}" run -d \
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
    "${DOCKER[@]}" start "${ONOS_CONTAINER}" >/dev/null
    ;;
esac

# --- Wait for the OpenFlow listener ----------------------------------------

info "Waiting for the ONOS OpenFlow listener on ${BIND_ADDR}:${OF_PORT} (up to 180s)"
ready=0
for _ in $(seq 1 36); do
  if "${DOCKER[@]}" logs "${ONOS_CONTAINER}" 2>&1 |
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

"${DOCKER[@]}" ps --filter "name=${ONOS_CONTAINER}" \
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

  2. Set REST credentials in your shell (never commit them).
     Reference lab REST/GUI (127.0.0.1:8181):
       export ONOS_USER=onos
       export ONOS_PASSWORD=rocks

  3. Launch the main project topology (Mininet still needs root).
     Session helper:
       ./scripts/testbed.sh start
     Or interactive Mininet:
       sudo mn -c
       sudo mn --custom topologies/main_topology.py \\
         --topo main6s8h \\
         --controller=remote,ip=127.0.0.1,port=${OF_PORT} \\
         --switch=ovsk

  4. If you used interactive Mininet, install deterministic baseline forwarding:
       python3 forwarding/baseline_forwarding.py install
       sudo ./scripts/verify_main_openflow.sh
     ./scripts/testbed.sh start already installs baseline flows.

  5. Clean up:
       ./scripts/testbed.sh stop
     After an interactive Mininet CLI:
       sudo mn -c

Stop ONOS with the same Docker access this script selected:
  ${DOCKER[*]} stop ${ONOS_CONTAINER}
Start it again:
  ${DOCKER[*]} start ${ONOS_CONTAINER}

Reactive forwarding (org.onosproject.fwd) is intentionally NOT activated.
Host pingall succeeds only after org.coms6200.baseline flows are installed.
EOF
