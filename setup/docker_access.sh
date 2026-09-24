# shellcheck shell=bash
# Shared Docker access detection for COMS6200 setup/verify scripts.
#
# Sets the bash array DOCKER to either (docker) or (sudo docker).
# Does not add users to the docker group, chmod the Docker socket,
# reconfigure the daemon, or install rootless Docker.

detect_docker() {
  local mode="${1:-optional}"
  DOCKER=()

  if ! command -v docker >/dev/null 2>&1; then
    if [[ "${mode}" == "required" ]]; then
      echo "ERROR: docker is not installed.
This script does not install a container runtime automatically.
Install Docker on the server first, then re-run this script.
Alternative: install the ONOS tar.gz under /opt/onos, which additionally
requires a Java 11 JDK on the host." >&2
    fi
    return 1
  fi

  if docker info >/dev/null 2>&1; then
    DOCKER=(docker)
    echo "==> Docker access: current user (no sudo)"
    return 0
  fi

  if command -v sudo >/dev/null 2>&1 && sudo docker info >/dev/null 2>&1; then
    DOCKER=(sudo docker)
    echo "==> Docker access: sudo fallback (direct 'docker info' failed)"
    return 0
  fi

  if [[ "${mode}" == "required" ]]; then
    echo "ERROR: docker is installed but the daemon is not usable.
Tried: docker info
Tried: sudo docker info (when sudo is available)
This script does not add users to the docker group or change socket
permissions. Ask the host administrator for Docker access, then re-run." >&2
  else
    echo "NOTE: docker is installed but the daemon is not usable as this user."
  fi
  return 1
}
