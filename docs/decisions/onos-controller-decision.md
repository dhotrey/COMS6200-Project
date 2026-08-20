# Decision: ONOS as the project SDN controller

Date: 20 August 2026
Status: **Accepted** — ONOS 2.7.0 is selected as the project controller platform.

## Context

The Part A methodology named Ryu as the primary intended controller, with
os-ken as a possible fallback. Ryu was never installed on the team server. Its
upstream repository states that Ryu is not currently maintained, and its
compatibility with the server's Python 3.12.3 environment was unverified and
expected to be problematic. os-ken is not a guaranteed drop-in replacement for
the project's standalone OpenFlow workflow.

In Week 4 the course coordinator introduced ONOS and confirmed support for using
it.

## Observed environment

- Ubuntu 24.04.4 LTS, kernel 6.8.0-137-generic, x86_64
- Python 3.12.3 (system), project `.venv` also 3.12.3
- Mininet 2.3.0, Open vSwitch 3.3.9
- No Java installed on the host
- Docker 29.1.3 already installed
- 1 vCPU, 955 MiB RAM, 2.3 GiB swap, 23 GB disk

## Reasons for evaluating ONOS

- Alignment with COMS6200 course material and coordinator support.
- Mature OpenFlow 1.3 southbound support.
- Built-in topology, device, link, host and flow abstractions, which are exactly
  the diagnostic evidence the project's agent and baseline need.
- A documented REST API, giving a clean boundary between the controller and the
  Python tool layer that the LLM agent will call. This is a better separation
  than embedding the agent inside a Python controller application.
- Avoids the unmaintained-Ryu and Python-3.12 compatibility risk entirely,
  because ONOS runs on its own bundled Java 11 inside a container.

## Decision

ONOS 2.7.0 is selected, deployed from the official pre-built Docker image
`onosproject/onos:2.7.0`.

The decision is based on runtime tests performed on the team server on
20 August 2026, not on documentation review. Verified on the real server:

- ONOS 2.7.0 starts and stays running (Java 11.0.8, Zulu11.41+23-CA, inside the
  container).
- OpenFlow provider suite active: `org.onosproject.openflow`,
  `org.onosproject.openflow-base`, plus `drivers`, `lldpprovider`,
  `hostprovider`, `gui2`, `optical-model`.
- OpenFlow listening on `127.0.0.1:6653`; REST/GUI on `8181`; Karaf CLI on `8101`.
- A simple `h1 -- s1 -- h2` Mininet network connected: OVS reported
  `is_connected: true`, `protocols: [OpenFlow13]`, `fail-mode: secure`, and ONOS
  discovered `of:0000000000000001` with `protocol=OF_13`.
- The project topology `main6s8h` connected all six switches. ONOS discovered
  6 devices with the expected deterministic DPIDs `of:0000000000000001` through
  `of:0000000000000006`, and 18 directed links corresponding to the 9 physical
  switch-to-switch links.
- REST read-only queries for `/devices`, `/links`, `/hosts`, `/flows` and
  `/topology` all returned HTTP 200.
- The existing Mininet/OVS/Python environment was unaffected: a post-install
  `mn --switch ovsbr --test pingall` returned `0% dropped (2/2 received)`.

Evidence is recorded under `evidence/progress/onos/`. The reproducible procedure
is `docs/setup/onos-setup.md` and `setup/setup_onos.sh`.

## Consequences

- The controller runs as an isolated container. Mininet, Open vSwitch, the
  system Python and the project `.venv` are unchanged. No JDK was installed on
  the host.
- The planned architecture becomes:
  `Python tool layer -> ONOS REST -> ONOS -> OpenFlow 1.3 -> Mininet / OVS`.
- `controllers/main_controller.py` and `controllers/README.md`, written for the
  Ryu approach, are now **provisional and superseded as executable code**. They
  are retained deliberately, not deleted, because their deterministic
  active-tree forwarding design and explicit port map remain the specification
  for the next milestone. Refactoring or removal will be a separate, deliberate
  commit.
- Reactive forwarding (`org.onosproject.fwd`) is **not** activated. The topology
  is physically cyclic, and an uncontrolled reactive learning application is not
  an acceptable basis for controlled fault experiments. Deterministic loop-free
  forwarding must be implemented explicitly, most likely through ONOS flow
  objectives or intents driven from our own code.
- Host connectivity across `main6s8h` therefore does not work yet, and ONOS
  reports `hosts=0`. This is expected at this milestone.
- Ryu and os-ken were not installed and are no longer on the critical path.

## Report implications (not yet applied)

The Part A report still names Ryu and still records
"Ryu + OpenFlow 1.3 main topology — Not yet evidenced". That has deliberately
**not** been changed in this commit. Switching the documented controller is an
architectural change to the report and must be handled as a separate, reviewed
report-update step now that ONOS is proven.
