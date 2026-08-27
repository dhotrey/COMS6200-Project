#!/usr/bin/env bash
# Read-only verification for the project's ONOS controller.
#
# Collects controller-side evidence only. It does not start, stop or
# reconfigure ONOS, and it does not modify flows or switches.
#
# REST credentials are read from the environment so they are never stored in
# this repository:
#
#   export ONOS_USER=onos
#   export ONOS_PASSWORD=rocks
#   ./scripts/verify_onos.sh
#
# See docs/setup/onos-setup.md.

set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

ONOS_CONTAINER="${ONOS_CONTAINER:-onos}"
ONOS_HOST="${ONOS_HOST:-127.0.0.1}"
ONOS_REST_PORT="${ONOS_REST_PORT:-8181}"
ONOS_OF_PORT="${ONOS_OF_PORT:-6653}"
ONOS_CLI_PORT="${ONOS_CLI_PORT:-8101}"
ONOS_API="http://${ONOS_HOST}:${ONOS_REST_PORT}/onos/v1"

# ss process names often need privilege; Docker uses a separate capability check.
if [[ "${EUID}" -eq 0 ]]; then
  SS_SUDO=""
else
  SS_SUDO="sudo"
fi

# shellcheck source=../setup/docker_access.sh
. "${ROOT}/setup/docker_access.sh"

echo "===== ONOS container ====="
if detect_docker optional; then
  "${DOCKER[@]}" ps -a --filter "name=${ONOS_CONTAINER}" \
    --format '{{.ID}}  {{.Image}}  {{.Status}}  {{.Ports}}' ||
    echo "ERROR: could not query docker"
  "${DOCKER[@]}" inspect "${ONOS_CONTAINER}" \
    --format 'Memory={{.HostConfig.Memory}} RestartPolicy={{.HostConfig.RestartPolicy.Name}}' 2>/dev/null ||
    echo "NOTE: container '${ONOS_CONTAINER}' not found"
else
  echo "NOTE: docker not usable; if ONOS runs natively, check its service instead"
fi
echo

echo "===== Listening ports ====="
if command -v ss >/dev/null 2>&1; then
  ${SS_SUDO} ss -lntp |
    grep -E ":${ONOS_OF_PORT}|:${ONOS_REST_PORT}|:${ONOS_CLI_PORT}" ||
    echo "NOTE: none of ${ONOS_OF_PORT}/${ONOS_REST_PORT}/${ONOS_CLI_PORT} are listening"
else
  echo "NOTE: ss not available"
fi
echo

echo "===== OpenFlow listener in ONOS log ====="
if [[ "${#DOCKER[@]}" -gt 0 ]]; then
  "${DOCKER[@]}" logs "${ONOS_CONTAINER}" 2>&1 |
    grep "Listening for OF switch connections" | tail -5 ||
    echo "NOTE: no OpenFlow listener log line found"
fi
echo

if [[ -z "${ONOS_PASSWORD:-}" ]]; then
  cat <<'EOF'
===== REST checks skipped =====
ONOS_PASSWORD is not set, so no REST queries were attempted.
Set credentials in your shell (do not commit them):

  export ONOS_USER=onos
  export ONOS_PASSWORD=rocks
EOF
  exit 0
fi

ONOS_USER="${ONOS_USER:-onos}"
CREDS="${ONOS_USER}:${ONOS_PASSWORD}"

rest_get() {
  # $1 = endpoint, $2 = label
  local body status
  body="$(mktemp)"
  status="$(curl -sS -o "${body}" -w '%{http_code}' -u "${CREDS}" "${ONOS_API}/$1" 2>/dev/null)"
  echo "--- $2 (/onos/v1/$1) HTTP ${status} ---"
  if [[ "${status}" == "200" ]]; then
    if command -v python3 >/dev/null 2>&1; then
      python3 - "${body}" "$1" <<'PY'
import json, sys
path, kind = sys.argv[1], sys.argv[2]
try:
    data = json.load(open(path))
except Exception as exc:
    print("could not parse response:", exc)
    raise SystemExit(0)
if kind == "devices":
    d = data.get("devices", [])
    print("device_count", len(d))
    for x in sorted(d, key=lambda y: y.get("id", "")):
        a = x.get("annotations", {})
        print(" ", x.get("id"), a.get("datapathDescription"),
              a.get("protocol"), "available=%s" % x.get("available"))
elif kind == "links":
    links = data.get("links", [])
    pairs = {tuple(sorted([l["src"]["device"], l["dst"]["device"]])) for l in links}
    print("directed_link_count", len(links))
    print("undirected_pair_count", len(pairs))
    for l in sorted(links, key=lambda x: (x["src"]["device"], int(x["src"]["port"]))):
        print(" ", l["src"]["device"], "port", l["src"]["port"], "->",
              l["dst"]["device"], "port", l["dst"]["port"], l.get("state"))
elif kind == "hosts":
    h = data.get("hosts", [])
    print("host_count", len(h))
    for x in h:
        loc = (x.get("locations") or [{}])[0]
        print(" ", x.get("mac"), x.get("ipAddresses"),
              loc.get("elementId"), "port", loc.get("port"))
elif kind == "flows":
    f = data.get("flows", [])
    print("flow_count", len(f))
    per = {}
    for x in f:
        per[x.get("deviceId")] = per.get(x.get("deviceId"), 0) + 1
    for k in sorted(per, key=lambda v: str(v)):
        print(" ", k, per[k])
elif kind == "applications":
    apps = data.get("applications", [])
    active = [a for a in apps if a.get("state") == "ACTIVE"]
    print("active_app_count", len(active), "of", len(apps))
    for a in sorted(active, key=lambda x: x.get("name", "")):
        print(" ", a.get("name"), a.get("version"))
else:
    print(json.dumps(data)[:400])
PY
    else
      head -c 400 "${body}"; echo
    fi
  else
    head -c 200 "${body}"; echo
  fi
  rm -f "${body}"
  echo
}

echo "===== REST API (read-only) ====="
rest_get "topology"     "topology summary"
rest_get "applications" "active applications"
rest_get "devices"      "devices"
rest_get "links"        "links"
rest_get "hosts"        "hosts"
rest_get "flows"        "flows"

echo "===== GUI ====="
curl -sS -o /dev/null -w "GUI /onos/ui HTTP %{http_code}\n" \
  "http://${ONOS_HOST}:${ONOS_REST_PORT}/onos/ui" || echo "ERROR: GUI request failed"
echo

echo "Reminder: the Karaf CLI is available at:"
echo "  ssh -p ${ONOS_CLI_PORT} karaf@${ONOS_HOST}"
