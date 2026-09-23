# Telemetry package (M4)

Bounded, structured diagnostics for `main6s8h`. This is the only agent-facing
interface. It is used later by both the LLM agent and the scripted
troubleshooting baseline.

This package is not a fault injector, not an LLM client, and not a
configuration API.

## Public Python API

```python
from telemetry import TelemetryGateway

gw = TelemetryGateway()
gw.get_topology()
gw.get_port_status("s3")
gw.get_port_stats("s3")
gw.get_flow_table("s3")
gw.ping("h1", "h5")          # optional count=1..10, default 3
gw.iperf("h1", "h5")         # optional duration=1..5, default 2
```

Every method returns the same envelope:

```json
{"tool": "ping", "ok": true, "timestamp": "2026-08-27T00:00:00Z", "data": {}, "error": null}
```

Provider-neutral input schemas: `from telemetry import TOOL_SCHEMAS, schema_list`.

## CLI

From the repository root, with ONOS credentials in the environment:

```bash
export ONOS_USER=onos
export ONOS_PASSWORD=rocks

# ONOS REST tools: no sudo
python3 -m telemetry.cli get-topology
python3 -m telemetry.cli get-port-status --switch s3
python3 -m telemetry.cli get-port-stats --switch s3
python3 -m telemetry.cli get-flow-table --switch s3
python3 -m telemetry.cli schemas

# Host-namespace tools: typically need sudo for mnexec
sudo --preserve-env=ONOS_USER,ONOS_PASSWORD,PATH python3 -m telemetry.cli ping --src h1 --dst h5
sudo --preserve-env=ONOS_USER,ONOS_PASSWORD,PATH python3 -m telemetry.cli iperf --src h1 --dst h5
```

`sudo` is for Mininet namespaces (`mnexec`), not Docker. JSON is written to
stdout. Do not use `sudo` without `--preserve-env=ONOS_*` or the REST client
will not see credentials.

## Data sources

| Tool | Observed (ONOS REST) | Configured (`topologies/spec.py`) |
| --- | --- | --- |
| `get_topology` | devices, availability, protocol, inter-switch links | host identities, IPs/MACs, 9 attachments including h6 primary/secondary |
| `get_port_status` | `/devices/{id}/ports` (`isEnabled`, `portName`, type, speed) | peer names |
| `get_port_stats` | `/statistics/ports` (two samples) plus optional delta | peer names |
| `get_flow_table` | `/flows` | switch → DPID |
| `ping` / `iperf` | none | host → primary IPv4; namespace via `mininet:<host>` + `mnexec` |

`get_topology()` does **not** call ONOS `/hosts`. `host_count=0` is expected
and is not treated as an error.

`utilization_pct` is always `null`. Observed bit rates are returned; no
nominal OVS speed or fault-injector TC config is used as capacity.

## Safety

- allow-listed hosts `h1`–`h8` and switches `s1`–`s6` only
- no `shell=True`
- no caller-supplied command strings, executables, PIDs, or REST paths
- ONOS client has no generic `get(path)`
- no credentials in tool JSON
- ping/iperf do not change flows, links, addresses, or ONOS applications
- iperf cleanup stops only the gateway's own port-5201 iperf3 (`pkill -f`);
  Mininet hosts share the root process table, so an unscoped `pkill -x iperf3`
  would also stop unrelated iperf3 such as the F2 background load

Host namespaces: discover `/proc/*/cmdline` token `mininet:<host>`, re-validate
the PID, then `mnexec -a <pid> -- <fixed argv>`.

## Tests

```bash
python3 tests/test_main_static.py
python3 tests/test_baseline_forwarding.py
python3 tests/test_telemetry.py
```

Live (Ubuntu Mininet server, topology + baseline already up):

```bash
export ONOS_USER=onos
export ONOS_PASSWORD=rocks
./scripts/verify_telemetry.sh
```

Ubuntu 24.04.4 host `Aus`, 27 August 2026: `verify_telemetry.sh` ALL CHECKS
PASSED. Session was already root, so ping/iperf needed no extra sudo and the
script did not re-exec. A non-root operator should still expect `mnexec`/OVS
privilege. Kali was not tested in that run. Evidence:
`evidence/progress/telemetry/structured-telemetry-2026-08-27.txt`.
