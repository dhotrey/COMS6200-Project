#!/usr/bin/env bash
# Read-only OpenFlow/OVS evidence collector for the main project topology.
# Does not add, modify or delete flows. Run while Mininet is up:
#   sudo ./scripts/verify_main_openflow.sh

set -u

echo "===== ovs-vsctl show ====="
if ! ovs-vsctl show; then
  echo "ERROR: ovs-vsctl show failed"
fi
echo

for sw in s1 s2 s3 s4 s5 s6; do
  echo "===== ${sw} ====="
  if ! ovs-vsctl br-exists "${sw}"; then
    echo "MISSING: bridge ${sw}"
    echo
    continue
  fi

  echo "-- protocols --"
  ovs-vsctl get bridge "${sw}" protocols || echo "ERROR: could not read protocols for ${sw}"

  echo "-- fail-mode --"
  ovs-vsctl get-fail-mode "${sw}" || echo "ERROR: could not read fail-mode for ${sw}"

  echo "-- controller --"
  ovs-vsctl get-controller "${sw}" || echo "ERROR: could not read controller for ${sw}"

  echo "-- dump-flows (OpenFlow13) --"
  ovs-ofctl -O OpenFlow13 dump-flows "${sw}" || echo "ERROR: dump-flows failed for ${sw}"
  echo
done
