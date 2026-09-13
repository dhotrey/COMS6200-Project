# COMS6200 LLM-Based Network Troubleshooting Agent

## User Manual

Canonical operational guide for setup, testbed operation, healthy-state checks, planned diagnosis workflows, reset, and troubleshooting.

The [root README](../README.md) is the concise landing page. This file is the detailed operator/developer manual.

Architecture diagram (Part A Figure 2): [reports/part-a/figures/figure2.png](reports/part-a/figures/figure2.png). Topology diagram (Part A Figure 1): [reports/part-a/figures/figure1.png](reports/part-a/figures/figure1.png).

---

## Status legend

| Mark | Meaning |
| --- | --- |
| ✅ | Implemented and runtime verified |
| 🟡 | Planned / under development |
| 🔬 | Optional extension |

## Current implementation status

| Item | Status |
| --- | --- |
| M0 Reproducible Environment Bootstrap | ✅ |
| M1 Enhanced Main Mininet Topology | ✅ |
| M2 ONOS + OpenFlow 1.3 Integration | ✅ |
| M3 Deterministic Loop-Free Forwarding | ✅ |
| M4 Structured Telemetry Gateway | ✅ |
| M5 First Automated Fault + Reset | ✅ |
| M5B Fault Catalogue v1 (F1–F5) | ✅ Frozen |
| Automated fault injection | ✅ F1–F5 verified |
| Deterministic scripted troubleshooting baseline | 🟡 |
| LLM tool-calling integration | Harness implemented; live gateway/testbed verification pending |
| Repeated evaluation experiments | 🟡 |
| h6 multihoming / failover experiment | 🔬 |
| Constrained automatic link-failure repair | 🔬 |

Do not treat a 🟡 or 🔬 item as **runtime-verified complete**. Unimplemented
sections must not invent CLIs.

**Two different “baseline” terms**

- **Baseline forwarding** ✅ — ONOS application `org.coms6200.baseline`. Network datapath for healthy host connectivity.
- **Scripted troubleshooting baseline** 🟡 — future diagnostic comparator that will use the same telemetry as the LLM. Not implemented.

---

## Contents

1. [Audience and purpose](#audience-and-purpose)
2. [Architecture overview](#architecture-overview)
3. [Reference environment](#reference-environment) (includes [supported environments](#supported-environments))
4. [System requirements](#system-requirements)
5. [Installation and environment setup](#installation-and-environment-setup)
6. [ONOS controller](#onos-controller)
7. [Main experimental topology](#main-experimental-topology)
8. [Host addressing](#host-addressing)
9. [Starting the network](#starting-the-network)
10. [Verifying controller integration](#verifying-controller-integration)
11. [ONOS host discovery](#onos-host-discovery)
12. [Deterministic baseline forwarding](#deterministic-baseline-forwarding)
13. [Healthy network checklist](#healthy-network-checklist)
14. [Structured telemetry gateway](#structured-telemetry-gateway)
15. [Fault injection](#fault-injection)
16. [Operator vs diagnostic-agent view](#operator-vs-diagnostic-agent-view)
17. [Asking the LLM for a diagnosis](#asking-the-llm-for-a-diagnosis)
18. [Expected diagnostic output](#expected-diagnostic-output)
19. [Scripted troubleshooting baseline](#scripted-troubleshooting-baseline)
20. [Resetting the testbed](#resetting-the-testbed)
21. [Troubleshooting the testbed](#troubleshooting-the-testbed)
22. [Safety and experimental controls](#safety-and-experimental-controls)
23. [Optional extensions](#optional-extensions)
24. [End-to-end workflow](#end-to-end-workflow)
25. [Repository layout](#repository-layout)
26. [Development and Git workflow](#development-and-git-workflow)
27. [Keeping this manual current](#keeping-this-manual-current)

---

## Audience and purpose

This manual is for:

- project developers maintaining the testbed
- course markers / demonstrators reproducing verified behaviour
- users setting up the Linux experiment host
- experiment operators running later diagnosis episodes
- users who will later ask the LLM to diagnose a **symptom**

The project is a **controlled experimental/research testbed**, not a production network-management platform.

Primary purpose: compare a tool-using LLM troubleshooting agent with a deterministic **scripted troubleshooting baseline**, using the **same observable evidence**, in an OpenFlow-controlled Mininet network.

Research question: *How accurately and efficiently can a tool-using LLM agent diagnose and localise common faults in an OpenFlow-controlled Mininet network compared with a deterministic scripted troubleshooting baseline?*

---

## Architecture overview

Implemented through M5 (Ubuntu live evidence 27 August 2026; F1 operator injector only):

```
Mininet hosts
    ↓
Open vSwitch
    ↓ OpenFlow 1.3
ONOS 2.7.0
    ↓ read-only REST (internal to the gateway only)
    + configured Mininet host map (`topologies/spec.py`)
Structured Telemetry / Tool Gateway
```

Still planned:

```
Structured Telemetry / Tool Gateway
    ↓
    ├── OpenAI LLM Agent                    🟡
    └── Deterministic Scripted Troubleshooting Baseline  🟡
            ↓
    Structured Diagnosis
            ↓
    Evaluator / Logger
```

Ground truth path (planned injector; evaluator-only):

```
Fault Injector ── inject faults ──→ Mininet / OVS
Fault Injector ── ground truth only ──→ Evaluator / Logger
```

See [Part A Figure 2](reports/part-a/figures/figure2.png).

Experimental fairness (planned, but already a project constraint):

- neither diagnostic method receives hidden fault labels
- neither receives injector configuration
- the LLM does not receive unrestricted shell access
- the LLM does not receive ONOS credentials
- controller access for diagnosis is mediated by the telemetry gateway
- both methods receive equivalent evidence from that gateway

Raw ONOS REST used by the forwarding installer is **not** the telemetry gateway.

---

## Reference environment

Verified on the team Ubuntu Mininet server (20 August 2026). Other versions may work if capability checks pass; they are **not** the verified baseline.

| Component | Verified value | Evidence / source |
| --- | --- | --- |
| OS | Ubuntu 24.04.4 LTS, kernel 6.8.0-137-generic, x86_64 | `evidence/progress/onos/environment-2026-08-20.txt` |
| Python | 3.12.3 | same |
| Git | 2.43.0 | same |
| Mininet | 2.3.0 | same |
| Open vSwitch | 3.3.9 | same |
| iperf3 | 3.16 | same (`iperf 3.16`) |
| curl | 8.5.0 | same |
| Docker (host) | 29.1.3 | same |
| ONOS | 2.7.0 | `evidence/progress/onos/onos-startup-2026-08-20.txt` |
| ONOS image | `onosproject/onos:2.7.0` | same |
| ONOS Java | Zulu OpenJDK 11.0.8 **inside the container** (`JAVA_HOME=/usr/lib/jvm/zulu11-ca-amd64`) | same |
| Host Java | not installed, **not required** | same |
| OpenFlow | 1.3 (`OF_13`) | M2/M3 evidence |
| ONOS bindings | `127.0.0.1` only | setup scripts |

The reference server used during ONOS testing had 1 vCPU and about 955 MiB RAM. **No formal minimum hardware specification has been benchmarked**; use the reference server configuration when reproducibility matters.

---

## Supported environments

| Environment | Role | Status |
| --- | --- | --- |
| Ubuntu 24.04.4 | **Verified reference environment** | M0–M3 runtime-verified on the team Ubuntu server |
| UQ-provided Kali VM | **Supported course compatibility target** | `setup/setup_ubuntu.sh` is apt/Debian-family and continues on Kali; individual milestones are **not** claimed fully verified on Kali until evidence exists |
| Other apt-based Linux | Capability-based only | May work if `./setup/verify_environment.sh` passes; not officially verified |

Do **not** treat Kali as the primary target instead of Ubuntu. Ubuntu remains the reference because it is what M0–M3 evidence was collected on. Kali is supported so the UQ VM is a valid course machine, not because every milestone has been re-run there.

The historical filename `setup/setup_ubuntu.sh` installs Mininet/OVS via apt on both the Ubuntu reference and the Kali compatibility target. It is not Ubuntu-only.

---

## System requirements

Supported by current setup scripts:

- Linux (Ubuntu 24.04.4 is the verified reference; UQ Kali VM is a supported course compatibility target)
- Python 3
- Git
- Mininet
- Open vSwitch (`openvswitch-switch`)
- iperf3
- curl, jq
- python3-pip, python3-venv
- Docker (required for ONOS; **not** installed by `setup/setup_ubuntu.sh`)

`setup/setup_ubuntu.sh` installs the Mininet/OVS packages via apt. `setup/setup_onos.sh` requires Docker already usable on the host.

Do not store secrets in this repository. ONOS REST credentials and Cloudflare
tokens are environment variables loaded from the ignored root `.env` (see
`.env.example`). The OpenAI provider key stays in Cloudflare BYOK; never commit
`.env`.

---

## Installation and environment setup

Repository: `https://github.com/dhotrey/COMS6200-Project.git`

| Branch | Role |
| --- | --- |
| `develop` | Integration (normal working branch) |
| `master` | Stable / submission-ready |
| `feature/*` | Individual work |

Base Mininet/OVS and ONOS are **separate**. `setup_ubuntu.sh` does not install ONOS. `setup_onos.sh` does not install Mininet.

```bash
git clone https://github.com/dhotrey/COMS6200-Project.git
cd COMS6200-Project
git switch develop
chmod +x setup/*.sh scripts/*.sh
./setup/setup_ubuntu.sh
./setup/verify_environment.sh
```

After `setup_ubuntu.sh`:

```bash
source .venv/bin/activate
```

Then ONOS:

```bash
./setup/setup_onos.sh
./scripts/verify_onos.sh
```

`verify_environment.sh` is capability-based (Linux, Python 3, Git, Mininet, OVS tools, iperf3, OVS runtime, basic `mn --switch ovsbr --test pingall`). A pass is **not** evidence that ONOS, OpenFlow 1.3 on `main6s8h`, telemetry, faults, or the LLM work.

Cursor, Git, and documentation editing may be done on macOS or Windows. Mininet, OVS, and ONOS must run on Linux.

---

## ONOS controller

✅ Version-pinned Docker image `onosproject/onos:2.7.0`. Container name: `onos`.

### Ports (loopback only)

| Host binding | Role |
| --- | --- |
| `127.0.0.1:6653` | OpenFlow |
| `127.0.0.1:8181` | REST API and GUI |
| `127.0.0.1:8101` | Karaf CLI (SSH) |

ONOS also listens on 6633 **inside** the container. That port is not published. Use 6653 only.

### Start / stop

First run, or after the container was removed:

```bash
./setup/setup_onos.sh
```

If the container already exists:

```bash
docker start onos
```

Try `docker info` **without** sudo first. If it succeeds, run all Docker commands as the current user. `setup/setup_onos.sh` does the same: it uses `docker` directly when `docker info` works, and falls back to `sudo docker` only when direct access fails. It does **not** add users to the `docker` group or change socket permissions.

Mininet is separate: `sudo mn -c` and `sudo mn --custom ...` remain required on typical Linux hosts.

Wait until OpenFlow is listening on `127.0.0.1:6653` (typically 60–90 seconds on the small team server).

Stop (container kept):

```bash
docker stop onos
```

Remove container (image kept):

```bash
docker stop onos && docker rm onos
```

`RestartPolicy=no`: the container does not restart after reboot. Start it explicitly.

### Verify

```bash
./scripts/verify_onos.sh
```

REST checks run only if `ONOS_PASSWORD` is set:

```bash
# Reference ONOS 2.7.0 lab credentials
export ONOS_USER=onos
export ONOS_PASSWORD=rocks
./scripts/verify_onos.sh
```

`onos` / `rocks` are the credentials used by the project's verified local ONOS 2.7.0 reference deployment. ONOS REST/GUI is bound to localhost at `127.0.0.1:8181`. If a user changes the ONOS credentials, they should override `ONOS_USER` / `ONOS_PASSWORD` in their shell. Custom or replacement credentials must not be committed to Git.

`onos` / `rocks` are the documented credentials for the local reference lab deployment. If these defaults are replaced, keep the new credentials outside Git and pass them through `ONOS_USER` and `ONOS_PASSWORD`. The installer and verifier read REST credentials from the environment only.

Simple REST authentication test (port 8181 only):

```bash
curl -u "$ONOS_USER:$ONOS_PASSWORD" \
  http://127.0.0.1:8181/onos/v1/devices
```

HTTP 200 plus device JSON means REST authentication succeeded. HTTP 401 means the REST credentials are incorrect.

These environment variables apply to the ONOS REST/GUI API on port 8181. They are not a documented Karaf CLI password.

Karaf CLI authentication is separate from REST. This manual does not document a verified CLI password:

```bash
ssh -p 8101 karaf@127.0.0.1
```

### Applications

Started via `ONOS_APPS=drivers,openflow,gui2`. Observed **ACTIVE** apps:

- `org.onosproject.drivers`
- `org.onosproject.optical-model` (drivers dependency)
- `org.onosproject.hostprovider`
- `org.onosproject.lldpprovider`
- `org.onosproject.openflow-base`
- `org.onosproject.openflow`
- `org.onosproject.gui2`

`org.onosproject.openflow` pulls in `openflow-base`, `hostprovider`, and `lldpprovider`.

**`org.onosproject.fwd` must remain NOT ACTIVE.** The project uses explicit `org.coms6200.baseline` forwarding. Reactive forwarding would flood/learn across physical cycles.

---

## Main experimental topology

✅ File: `topologies/main_topology.py`  
Mininet name: `main6s8h`  
Layer 2, `10.0.0.0/24`, OpenFlow 1.3, `failMode=secure`. STP is not enabled.

| Role | Switch | Hosts |
| --- | --- | --- |
| Core A (active baseline core) | s1 | — |
| Core B (redundant / test) | s2 | — |
| User Access A | s3 | h1, h2 |
| User Access B | s4 | h3, h4 |
| Server Access | s5 | h5, h6 primary |
| Admin / Test Access | s6 | h7, h8, h6 secondary |

| Class | Count |
| --- | ---: |
| Switches | 6 |
| Hosts | 8 |
| Inter-switch physical links | 10 |
| Host-switch physical links | 9 |
| Total physical links | 19 |

Physically present but **excluded from baseline forwarding**:

- s1–s2 inter-core link
- s2 access uplinks (s2–s3, s2–s4, s2–s5, s2–s6)
- s3–s4 access-edge test link (controlled F4 / core-bypass)
- h6–s6 secondary attachment (optional later multihoming)

These remain available for later experiments. They must not carry normal host traffic.

### Verified port map

From `topologies/main_topology.py` / `topologies/README.md`:

| Switch | Port | Peer |
| --- | --- | --- |
| s1 | 1 | s2 p1 |
| s1 | 2 | s3 p1 |
| s1 | 3 | s4 p1 |
| s1 | 4 | s5 p1 |
| s1 | 5 | s6 p1 |
| s2 | 1 | s1 p1 |
| s2 | 2 | s3 p2 |
| s2 | 3 | s4 p2 |
| s2 | 4 | s5 p2 |
| s2 | 5 | s6 p2 |
| s3 | 1 | s1 p2 |
| s3 | 2 | s2 p2 |
| s3 | 3 | h1 |
| s3 | 4 | h2 |
| s3 | 5 | s4 p5 |
| s4 | 1 | s1 p3 |
| s4 | 2 | s2 p3 |
| s4 | 3 | h3 |
| s4 | 4 | h4 |
| s4 | 5 | s3 p5 |
| s5 | 1 | s1 p4 |
| s5 | 2 | s2 p4 |
| s5 | 3 | h5 |
| s5 | 4 | h6 primary |
| s6 | 1 | s1 p5 |
| s6 | 2 | s2 p5 |
| s6 | 3 | h7 |
| s6 | 4 | h8 |
| s6 | 5 | h6 secondary |

ONOS DPIDs: `of:0000000000000001` … `of:0000000000000006` for s1–s6.

---

## Host addressing

| Host | IPv4 | MAC | Attachment |
| --- | --- | --- | --- |
| h1 | 10.0.0.1/24 | 00:00:00:00:00:01 | s3:3 |
| h2 | 10.0.0.2/24 | 00:00:00:00:00:02 | s3:4 |
| h3 | 10.0.0.3/24 | 00:00:00:00:00:03 | s4:3 |
| h4 | 10.0.0.4/24 | 00:00:00:00:00:04 | s4:4 |
| h5 | 10.0.0.5/24 | 00:00:00:00:00:05 | s5:3 |
| h6 primary | 10.0.0.6/24 | 00:00:00:00:00:06 | s5:4 (`h6-eth0`) |
| h7 | 10.0.0.7/24 | 00:00:00:00:00:07 | s6:3 |
| h8 | 10.0.0.8/24 | 00:00:00:00:00:08 | s6:4 |
| h6 secondary | **no baseline IPv4** | 00:00:00:00:06:02 | s6:5 (`h6-eth1`) |

h6 secondary is unused by baseline forwarding. No bonding, LACP, MLAG, VRRP, or automatic failover is implemented.

---

## Starting the network

ONOS must be up first. Switches request OpenFlow 1.3 and secure fail mode in the topology. Do not use `--controller=none`, `--switch ovsbr`, NORMAL, STP, or `org.onosproject.fwd`.

```bash
./setup/setup_onos.sh          # or: docker start onos
./scripts/verify_onos.sh

sudo mn -c
sudo mn --custom topologies/main_topology.py \
  --topo main6s8h \
  --controller=remote,ip=127.0.0.1,port=6653 \
  --switch=ovsk
```

Inside Mininet, initial inspection:

```
nodes
net
links
```

Expected: 6 switches, 8 hosts, 19 links OK. `pingall` **fails** until baseline forwarding is installed.

From another shell while Mininet is running:

```bash
sudo ./scripts/verify_main_openflow.sh
```

Static topology checks (no Mininet required):

```bash
python3 tests/test_main_static.py
```

Cleanup after exiting Mininet:

```bash
sudo mn -c
```

---

## Verifying controller integration

✅ With `main6s8h` running against ONOS 2.7.0 (20 August 2026):

| Check | Expected |
| --- | --- |
| Devices | 6/6 available, `protocol=OF_13` |
| Directed ONOS links | 20 (= 10 physical inter-switch links) |
| s3:5 ↔ s4:5 | ACTIVE both ways |
| Fail mode | secure |
| REST | HTTP 200 for `/devices`, `/links`, `/hosts`, `/flows`, `/topology` |

```bash
export ONOS_USER=onos
export ONOS_PASSWORD=rocks
./scripts/verify_onos.sh
sudo ./scripts/verify_main_openflow.sh
```

`verify_onos.sh` reports device discovery, directed links, `host_count`, flow counts, and active applications. `verify_main_openflow.sh` reports OVS protocols, fail-mode, controller attachment, and OpenFlow 1.3 flow dumps.

ONOS topology links are **switch–switch only**. Host-facing attachments are not ONOS topology links. Do not compare Mininet’s 19 physical links with ONOS’s 20 directed inter-switch links as if they counted the same objects.

---

## ONOS host discovery

After healthy `pingall` (56/56), ONOS REST `/hosts` still returned HTTP 200 with **`host_count` 0**.

This is **expected**, not a forwarding failure.

Cause: baseline ARP is forwarded in the data plane (priority 42000/41000), so `hostprovider` does not necessarily receive Packet_In ARP and does not learn endpoint locations.

Do **not** activate `org.onosproject.fwd` to populate `/hosts`.

`get_topology()` combines:

- ONOS: devices, inter-switch links, ports/status
- Mininet topology specification (`topologies/spec.py`): configured host attachments and host-to-switch mappings (including h6 primary and secondary)

It does **not** call ONOS `/hosts`. See [Structured telemetry gateway](#structured-telemetry-gateway).

---

## Deterministic baseline forwarding

✅ This is the **network forwarding baseline**. It is **not** the scripted troubleshooting baseline.

Provisioner: `forwarding/baseline_forwarding.py`  
Application: `org.coms6200.baseline`  
Numeric ONOS application ID (runtime, 20 Aug 2026): **176**

| Role | Priority |
| --- | ---: |
| ONOS system / control (LLDP/BDDP/ARP punt) | 40000 |
| Baseline unicast (dest-MAC) | 41000 |
| Baseline ARP tree | 42000 |
| Future injected faults (reserved, not installed) | 50000 |

| Count | Expected |
| --- | ---: |
| Baseline flows | 56 (all **ADDED**) |
| Controller/system flows | 18 (3 per switch) |
| Total ONOS flows | 74 |
| s1 | 12 |
| s2 | 0 |
| s3 / s4 / s5 / s6 | 11 each |

### Commands

```bash
export ONOS_USER=onos
export ONOS_PASSWORD=rocks
# optional: export ONOS_URL=http://127.0.0.1:8181/onos/v1

python3 forwarding/baseline_forwarding.py install
python3 forwarding/baseline_forwarding.py status
python3 forwarding/baseline_forwarding.py verify
python3 forwarding/baseline_forwarding.py remove
```

`install` is idempotent: it removes stale `org.coms6200.baseline` flows, installs the canonical set, then verifies `ADDED`. `remove` deletes **only** this application’s flows.

Static tests (no ONOS):

```bash
python3 tests/test_baseline_forwarding.py
```

### Normal forwarding behaviour

Active core: **s1**. Remote paths: s3/s4/s5/s6 → s1.

Unicast: match destination MAC of the eight primary hosts. Access switches send remote destinations toward s1; s1 sends toward the correct access switch; local hosts use the access host port.

ARP requests: ingress-specific broadcast-tree rules on **active-tree ports only** (s1: 2,3,4,5; s3–s6: 1,3,4; s2: none). ARP replies use dest-MAC unicast.

Excluded from baseline OUTPUT:

- s1–s2
- s2–s3, s2–s4, s2–s5, s2–s6
- s3–s4
- h6–s6 secondary

Those links stay discovered for later faults, redundancy, and optional failover.

Do not enable OVS `NORMAL`, STP, `OFPP_FLOOD`, or `org.onosproject.fwd` to make ping succeed.

---

## Healthy network checklist

| Check | Expected | How |
| --- | --- | --- |
| ONOS running | container `Up`, ports 6653/8181/8101 on loopback | `./scripts/verify_onos.sh` |
| Six switches | 6/6 `OF_13`, available | same + `sudo ./scripts/verify_main_openflow.sh` |
| Directed inter-switch links | 20 | `verify_onos.sh` |
| Baseline flows | 56 ADDED, s1=12 s2=0 s3–s6=11 | `python3 forwarding/baseline_forwarding.py verify` |
| System flows | 18 | `verify_onos.sh` / status |
| `org.onosproject.fwd` | **not ACTIVE** | `verify_onos.sh` applications |
| NORMAL / STP / FLOOD | not used for baseline | OVS dump-flows |
| `pingall` | **0% dropped (56/56 received)** | Mininet CLI |

Inside Mininet after `install`:

```
pingall
```

Verified result (20 August 2026): `0% dropped (56/56 received)` on primary h1–h8 addresses. Evidence: `evidence/progress/forwarding/deterministic-baseline-2026-08-20.txt`.

`host_count` 0 after that `pingall` is expected ([ONOS host discovery](#onos-host-discovery)).

---

## Structured telemetry gateway

✅ **RUNTIME VERIFIED — Ubuntu 24.04.4 (`Aus`), 27 August 2026**

Evidence: `evidence/progress/telemetry/structured-telemetry-2026-08-27.txt`.

The package `telemetry/` is the bounded agent-facing diagnostic interface. The
OpenAI agent and the scripted troubleshooting baseline are **not** implemented;
both are expected to call this same `TelemetryGateway` later.

It does **not** expose arbitrary shell, arbitrary subprocess arguments,
unrestricted ONOS REST, ONOS credentials, fault labels, injector configuration,
or evaluator ground truth.

### Prerequisites

- ONOS 2.7.0 reachable at `127.0.0.1:8181`
- `main6s8h` running
- M3 baseline installed (`python3 forwarding/baseline_forwarding.py verify`)
- `ONOS_USER` / `ONOS_PASSWORD` in the environment (reference lab: `onos` / `rocks`)
- `ping` / `iperf` typically need root so `mnexec` can enter Mininet host namespaces
- ONOS-only tools (`get-topology`, `get-port-status`, `get-port-stats`, `get-flow-table`) do **not** need root

```bash
export ONOS_USER=onos
export ONOS_PASSWORD=rocks
cd /path/to/COMS6200-Project

# No sudo: controller-state tools
python3 -m telemetry.cli get-topology

# Typically needs sudo: host-namespace ping/iperf
sudo --preserve-env=ONOS_USER,ONOS_PASSWORD,PATH python3 -m telemetry.cli ping --src h1 --dst h5
```

Do not use plain `sudo python3 ...` if that drops `ONOS_*`. Passwords must not
appear in telemetry JSON. CLI writes JSON to stdout; diagnostics may go to
stderr. Docker access is unrelated: do not prefix these commands with
`sudo docker`.

### Python API

```python
from telemetry import TelemetryGateway

gw = TelemetryGateway()
gw.get_topology()
gw.get_port_status("s3")
gw.get_port_stats("s3")
gw.get_flow_table("s3")
gw.ping("h1", "h5")                 # count 1–10, default 3
gw.iperf("h1", "h5")                # duration 1–5 s, default 2
```

### CLI

| Command | Tool |
| --- | --- |
| `python3 -m telemetry.cli get-topology` | `get_topology()` |
| `python3 -m telemetry.cli get-port-status --switch s3` | `get_port_status(s3)` |
| `python3 -m telemetry.cli get-port-stats --switch s3` | `get_port_stats(s3)` |
| `python3 -m telemetry.cli get-flow-table --switch s3` | `get_flow_table(s3)` |
| `python3 -m telemetry.cli ping --src h1 --dst h5` | `ping(h1, h5)` |
| `python3 -m telemetry.cli ping --src h1 --dst h5 --count 3` | bounded extra count |
| `python3 -m telemetry.cli iperf --src h1 --dst h5` | `iperf(h1, h5)` |
| `python3 -m telemetry.cli iperf --src h1 --dst h5 --duration 2` | bounded extra duration |
| `python3 -m telemetry.cli schemas` | provider-neutral input schemas |

Allow-lists: hosts `h1`–`h8`; switches `s1`–`s6`. IPs, REST paths, PIDs, and
command strings are rejected.

### JSON envelope

Success:

```json
{"tool": "get_topology", "ok": true, "timestamp": "2026-08-27T00:00:00Z", "data": {}, "error": null}
```

Failure (tool/runtime problem, not “host unreachable”):

```json
{"tool": "ping", "ok": false, "timestamp": "2026-08-27T00:00:00Z", "data": null,
 "error": {"code": "INVALID_HOST", "message": "host must be one of [...]", "details": {}}}
```

A completed ping with `received=0` / `loss_pct=100` is `ok: true` (the diagnostic
ran). `ok: false` is reserved for invalid input, missing namespace, ONOS down,
timeout, or parse failure.

### Tools

| Tool | Sources | Compact `data` | Status |
| --- | --- | --- | --- |
| `get_topology()` | ONOS devices/links; configured host map | switches, physical inter-switch links, 9 host attachments, summary | ✅ |
| `ping(src, dst)` | `mnexec` + `ping` in src namespace | sent/received, loss %, RTT min/avg/max | ✅ |
| `get_port_status(sw)` | ONOS `/devices/{id}/ports` | port, name, `isEnabled`, type, speed, configured peer | ✅ |
| `get_port_stats(sw)` | two `/statistics/ports` samples (~1 s); optional delta | packets/bytes, drops/errors, bit rates; `utilization_pct` is always `null` | ✅ |
| `get_flow_table(sw)` | ONOS `/flows` | id, table, state, priority, app_id, selector, treatment, packets/bytes, life | ✅ |
| `iperf(src, dst)` | one-shot `iperf3 -s -1` in dst, client in src | duration, bytes, Mbit/s, retransmits | ✅ |

`get_topology()` does **not** use ONOS `/hosts`. Healthy summary targets:

- 6 switches
- 10 physical inter-switch links
- 9 configured host attachments
- 8 logical hosts
- 19 total physical links

h6 appears twice: primary `h6-eth0`→s5 with `10.0.0.6/24`; secondary
`h6-eth1`→s6 with MAC `00:00:00:00:06:02` and no IPv4.

Port rates use a two-sample byte delta. `utilization_pct` is `null` because
there is no trustworthy non-ground-truth link capacity (OVS advertised speed
and TC/injector limits are not used).

Ping destination is the configured primary IPv4 (never a caller-supplied IP).
iperf uses iperf3 JSON (`-J`), TCP only, duration 1–5 s. The gateway does not
install a pass/fail throughput threshold. After the test it terminates the
server process group and best-effort `pkill -x iperf3` in the destination
namespace.

### Host-namespace mechanism

Mininet host shells are discovered by the `/proc/<pid>/cmdline` token
`mininet:<host>`. The PID is re-checked immediately before use. The gateway then
runs `mnexec -a <pid> --` plus a **fixed** argv (`ping` or `iperf3` only).
Callers cannot supply a PID, executable, or flag list. Stale PIDs and a missing
topology return `HOST_NAMESPACE_NOT_FOUND` or `TOPOLOGY_NOT_RUNNING`.

### Live verification

Verified 27 August 2026 on Ubuntu 24.04.4 host `Aus` (root SSH).
Evidence: `evidence/progress/telemetry/structured-telemetry-2026-08-27.txt`.

Observed:

- `docker info` without sudo succeeded; `setup_onos.sh` used **current-user Docker** (no `sudo docker`)
- ONOS-only CLI tools needed **no sudo**
- ping/iperf needed **no extra sudo in this root session** (`mnexec` as root)
- `./scripts/verify_telemetry.sh` did **not** re-exec (already EUID=0)
- `get_topology` summary: 6 switches, 10 physical inter-switch links, 9 host attachments, 8 hosts, 19 physical links, `onos_host_discovery=not_used`
- ping h1→h5: received=3, loss=0.0%, dst_ip=10.0.0.5
- iperf h1→h5: ok, throughput > 0 (≈10–14 Gbit/s on this local OVS path; no pass threshold)
- `utilization_pct` null
- verify script: ALL CHECKS PASSED; all-pairs ping 56/56; 56 baseline ADDED unchanged; fwd not ACTIVE; no NORMAL/FLOOD/stp_enable; no leftover iperf3
- final Mininet `pingall`: 0% dropped (56/56)

Kali was **not** run in this session and is not claimed verified.

A non-root operator should still expect OVS/`mnexec` to need privilege. The script re-executes with sudo only if `ovs-vsctl show` fails as the current user:

```bash
export ONOS_USER=onos
export ONOS_PASSWORD=rocks
./scripts/verify_telemetry.sh
```

`mn --custom` must be able to import `topologies/spec.py` even when `__file__` is undefined. If launch fails with `NameError: name '__file__' is not defined`, the topology locator in `main_topology.py` is missing or stale.

Representative verified ping:

```json
{"tool": "ping", "ok": true, "data": {"sent": 3, "received": 3, "loss_pct": 0.0,
 "rtt_avg_ms": 0.244, "src": "h1", "dst": "h5", "dst_ip": "10.0.0.5"}, "error": null}
```



Static checks (no ONOS required):

```bash
python3 tests/test_telemetry.py
```

Developer notes: `telemetry/README.md`.

---

## Fault injection

✅ **Fault Catalogue v1 — Frozen** (Ubuntu `Aus`, 27 August 2026).

All five mandatory scenarios are runtime-verified. Future LLM and scripted
troubleshooting experiments **must** use this frozen catalogue. Changing
targets, selectors, workloads, or reset semantics requires a new catalogue
version.

Evidence:

- `evidence/progress/faults/fault-catalogue-v1-2026-08-27.txt`
- per-scenario files under `evidence/progress/faults/`

| ID | Status | Injected concept (verified) | Useful evidence |
| --- | --- | --- | --- |
| F1 Link failure | ✅ | Disable primary s3–s1 (`s3-eth1`/`s1-eth2`) | topology, port state, ping |
| F2 Congestion | ✅ | TBF on s1–s5 + background iperf h3→h6 | iperf, port stats, ping |
| F3 ACL / policy error | ✅ | High-priority DROP h1→h5 on s3 (`org.coms6200.experiment`) | flows, ping |
| F4 Forwarding loop | ✅ | Narrow h1→h5 cycle s3→s4→s1→s3 + safety TBF on s3–s4 | flows, counters, ping |
| F5 Missing baseline flow | ✅ | Delete s3 baseline unicast for dest h5 | flows, ping |

h6 dual-home is **not** a sixth mandatory fault ([Optional extensions](#optional-extensions)).

### Operator CLI ✅

The package `faults/` is an **operator/evaluator** injector. It is **not** an LLM
tool. Do not expose fault CLI output, status, scenario IDs, or ground truth to
the diagnostic agent. Telemetry must never import fault state.

Requires **root** for mutations. The injector does **not** call `sudo` internally.

```bash
export ONOS_USER=onos
export ONOS_PASSWORD=rocks
export PYTHONPATH="$(pwd)${PYTHONPATH:+:$PYTHONPATH}"

python3 -m faults.cli status
python3 -m faults.cli inject --scenario F1   # or F2 F3 F4 F5
python3 -m faults.cli reset
```

Only `--scenario Fn` is accepted. No `--interface`, `--cmd`, `--rate`, `--pid`,
or arbitrary flow IDs.

Runtime state: `/run/coms6200/fault-state.json` (dir `0700`, file `0600`).
One active fault at a time.

### Verified symptoms (catalogue v1)

**F1:** ONOS links 20→18; h1→h5 fails; h1→h2 and h3→h5 succeed; 56 baseline ADDED.

**F2:** h1→h5 remains reachable with high RTT; iperf throughput ≤ 25% of the
measured healthy baseline (observed near-zero under 1 Mbit TBF + background);
56 baseline ADDED; reset removes TBF and background iperf.

**F3:** h1→h5 fails; h2→h5 and h1→h6 succeed; 56 baseline + 1 experiment DROP;
appId `org.coms6200.experiment` (neutral, not a fault label).

**F4:** h1→h5 fails; h1→h2 and h3→h5 succeed; 3 experiment OUTPUT flows; safety
TBF on `s3-eth5`; loop-path counters grow under bounded test traffic; 56 baseline.

**F5:** baseline ADDED 55; h1→h5 and h2→h5 fail; h1→h6 and h3→h5 succeed; reset
restores the missing rule → 56.

### Live verification

```bash
./scripts/verify_fault_f1.sh
./scripts/verify_fault_f2.sh
./scripts/verify_fault_f3.sh
./scripts/verify_fault_f4.sh
./scripts/verify_fault_f5.sh
./scripts/verify_fault_catalogue.sh   # sequential F1–F5 + healthy gates
```

Each script traps cleanup. Manual recovery:

```bash
python3 -m faults.cli reset
python3 -m faults.cli reset --force-scenario F2   # or F1…F5
python3 forwarding/baseline_forwarding.py install
tc qdisc del dev s1-eth4 root 2>/dev/null || true
tc qdisc del dev s3-eth5 root 2>/dev/null || true
```

### Harness secrets

Use the repository-root `.env` with mode `600`; it is Git-ignored. It contains
the D1 account API token and AI Gateway authentication token, while the OpenAI
provider key remains in Cloudflare BYOK. See
`docs/decisions/llm-api-gateway.md`. Do not commit API keys.

Developer notes: `faults/README.md`.

---

## Operator vs diagnostic-agent view

The **experiment operator** may know which fault was injected and the hidden ground truth.

The **diagnostic method** (LLM or scripted troubleshooter) must **not**.

Give a **symptom**, not the answer.

Good:

- “Investigate why h1 can no longer reach h5.”
- “Diagnose the degraded throughput between h1 and h8.”
- “h3 can communicate with most hosts, but traffic to h6 is failing. Investigate the cause and localise it.”

Bad (leaks ground truth):

- “I injected a link failure on s3–s1. Diagnose the problem.”
- “I installed a high-priority drop rule on s4. Find it.”

Those prompts invalidate a fair comparison.

---

## Asking the LLM for a diagnosis

The conversational starter harness lives in `agent/`. From the repository root:

```sh
uv sync --project agent
uv run --project agent python -m agent
```

Open http://127.0.0.1:8000. A directly opened `agent/index.html` is preview-only;
its pickers work, but chat/history require the Python server. Copy `.env.example` to `.env` and populate
`CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`,
`CLOUDFLARE_D1_DATABASE_ID`, `CLOUDFLARE_AI_GATEWAY_ID`, and
`CLOUDFLARE_AI_GATEWAY_API_TOKEN`. `CLOUDFLARE_API_TOKEN` needs D1 Write
permission and is distinct from the AI Gateway authentication token. Store the
OpenAI provider key in Cloudflare BYOK. `CLOUDFLARE_BYOK_ALIAS` and
`LOGFIRE_TOKEN` are optional. Restart after changing credentials. No local
OpenAI key is required.

Create and verify the D1 schema before first launch:

```sh
uv run --project agent python -m agent.setup_d1
```

This idempotently creates the `conversations` and `messages` tables, the message
lookup index, and an `ON DELETE CASCADE` foreign key. No seed data is required.
The server repeats the schema check at startup and requires D1 even when the AI
Gateway is not configured. Existing local `agent/chat.sqlite3` conversations
are intentionally not read, migrated, or deleted.

Live D1 verification (13 September 2026): schema setup returned `ok: true`,
the create/save/read/delete smoke test passed, and cleanup restored
`conversation_count` to `0`.

Six existing telemetry tools are reused on the same machine; `nmap` is a
placeholder returning `NOT_IMPLEMENTED`. Host probes retain Mininet namespace
privilege requirements. Follow [agent setup](../agent/README.md) for launch,
privileges, limits, Logfire, and offline tests. Run one server worker.

The model picker offers Luna, Terra, Sol and Astra with supported thinking levels.
A separate fault picker previews F1–F5. Its **Load scenario** button is disabled;
fault injection/reset still uses the operator workflow above. The selection stays
in the browser and is not sent to the assistant or applied to the network.
Conversation history and turn measurements are stored in Cloudflare D1.
Tool delays default to a random 1–10 seconds for telemetry testing; set both
`TOOL_DELAY_MIN_SECONDS` and `TOOL_DELAY_MAX_SECONDS` to `0` for research runs.
Execution and artificial-delay timings are recorded separately. Stop cancels
model generation; an in-flight bounded probe must finish cleanup before another
turn. Start a new conversation after resetting/changing scenarios to avoid stale
context. This harness does not load fault labels or injector state.

Example symptom-only prompts:

- “Diagnose why h1 cannot communicate with h5. Use the available diagnostic tools, identify the most likely root cause and localise the fault.”
- “Investigate why TCP throughput between h1 and h8 has degraded. Determine whether the issue is physical, congestion-related or forwarding-related.”
- “Investigate the connectivity failure affecting h3 to h6. Use only the available diagnostic tools and return evidence for your conclusion.”
- “Determine why traffic between h1 and h3 is failing even though the switches appear connected.”

Describe observable symptoms. Do not name the injector.

---

## Expected diagnostic output

The starter produces ordinary conversational answers grounded in tool observations.
It does not enforce a diagnosis JSON schema. Tool arguments/results and turn
statistics are stored structurally and shown in the UI. Measurements include
per-tool latency, per-model-request latency, whole-turn time, tokens summed over
all model rounds, cached/reasoning tokens, estimated cost, and invalid calls.
Cancelled or failed turns flag potentially incomplete usage.

A compatible structured diagnosis contract for the future scripted baseline and
evaluator remains planned; no automated diagnosis scoring is implemented.

---

## Scripted troubleshooting baseline

🟡 Planned. **This is not `org.coms6200.baseline`.**

| Term | What it is | Status |
| --- | --- | --- |
| Baseline forwarding | Datapath flows installed by `forwarding/baseline_forwarding.py` | ✅ |
| Scripted troubleshooting baseline | Deterministic diagnostic comparator | 🟡 |

Intended order (planned):

1. Test endpoint reachability
2. Inspect link/port state
3. Inspect traffic performance / counters
4. Inspect flow rules
5. Classify and localise the fault
6. Return the same diagnosis format as the LLM

Both methods will call the same existing `TelemetryGateway` (M6 / scripted baseline still 🟡).

---

## Resetting the testbed

### Available today ✅

Remove baseline flows (ONOS stays up; `pingall` will fail until `install` again):

```bash
export ONOS_USER=onos
export ONOS_PASSWORD=rocks
python3 forwarding/baseline_forwarding.py remove
```

Stop Mininet and clear OVS/Mininet state:

```bash
sudo mn -c
```

Reinstall a clean datapath after a fresh topology:

```bash
python3 forwarding/baseline_forwarding.py install
python3 forwarding/baseline_forwarding.py verify
```

Stop ONOS if needed:

```bash
docker stop onos
```

### After an injected F1 fault ✅

```bash
python3 -m faults.cli reset
# crash recovery when state file is missing but F1 ifaces are down:
python3 -m faults.cli reset --force-f1
python3 forwarding/baseline_forwarding.py verify
# confirm directed links = 20 and pingall 56/56 (see verify_fault_f1.sh)
```

F1 does not modify M3 flows, so `install` is not required after a clean F1 reset.
For future F2–F5 (🟡), additional cleanup may be required.

---

## Troubleshooting the testbed

### ONOS container not running

**Symptoms:** no listener on 6653/8181; Mininet switches fail to connect.

**Checks:** `./scripts/verify_onos.sh`, `docker ps --filter name=onos` (no sudo if `docker info` works).

**Action:** `./setup/setup_onos.sh` or `docker start onos`. Wait for the OpenFlow listener.

### ONOS REST unavailable

**Check:** `127.0.0.1:8181`. For the reference lab, `export ONOS_USER=onos` and `export ONOS_PASSWORD=rocks`, then re-run `./scripts/verify_onos.sh`. HTTP 401 means incorrect REST credentials. If these defaults are replaced, keep the new credentials outside Git and pass them through `ONOS_USER` and `ONOS_PASSWORD`.

### OpenFlow switch not connected

**Checks:** ONOS up; `127.0.0.1:6653`; `sudo ./scripts/verify_main_openflow.sh` (controller `tcp:127.0.0.1:6653`, `is_connected`, `OF_13`, fail-mode `secure`). Confirm Mininet used `--controller=remote,ip=127.0.0.1,port=6653 --switch=ovsk`.

### Fewer than 6 devices

Confirm `main6s8h` is still running. Re-run `verify_onos.sh` and `verify_main_openflow.sh`. Restart Mininet with `sudo mn -c` then the launch command if OVS is stale.

### Wrong link count

Healthy controller topology: **20 directed links / 10 physical inter-switch links**, including s3:5 ↔ s4:5. Do not expect ONOS to count host-facing links.

### `pingall` fails

Confirm baseline `install` / `verify` (56 ADDED, s2=0). Confirm `fwd` inactive. Confirm no leftover NORMAL/STP/FLOOD. Confirm Mininet was not started with `ovsbr` or `--controller=none`. After `mn -c`, reinstall baseline. `host_count` 0 is **not** the explanation for ping failure.

### Unexpected ONOS `host_count` 0

Currently **expected** after data-plane ARP. See [ONOS host discovery](#onos-host-discovery).

### `org.onosproject.fwd` active

Disable it for baseline experiments. The project must not use reactive forwarding on this cyclic topology.

### Unexpected NORMAL / STP / FLOOD

Violates deterministic loop-free design. Do not enable them to “fix” ping. Use `org.coms6200.baseline` instead.

### Stale Mininet / OVS state

```bash
sudo mn -c
```

Then relaunch `main6s8h` and `python3 forwarding/baseline_forwarding.py install`.

### Telemetry `ONOS_UNAVAILABLE` / `ONOS_AUTH_FAILED`

**Symptoms:** `python3 -m telemetry.cli get-topology` returns `ok: false` with those codes.

**Checks:** ONOS listening on `127.0.0.1:8181`; `ONOS_USER`/`ONOS_PASSWORD` set in this shell. `get-topology` does not need sudo. HTTP 401 means incorrect REST credentials, not a topology fault. If a later command uses sudo, pass `--preserve-env=ONOS_USER,ONOS_PASSWORD,PATH`.

### Telemetry `TOPOLOGY_NOT_RUNNING` / `HOST_NAMESPACE_NOT_FOUND`

**Symptoms:** `ping` / `iperf` fail; `get_topology` may still work if ONOS is up.

**Checks:** `main6s8h` Mininet session still running; `pgrep -af 'mininet:h1'`; `which mnexec`; run the CLI as root. Do not pass a PID on the command line — the gateway discovers `mininet:<host>` itself.

### Telemetry `NameError: __file__ is not defined`

**Cause:** `mn --custom` execs `main_topology.py` without setting `__file__`.

**Action:** use the locator in `topologies/main_topology.py` (cwd / custom-path fallback to `spec.py`). Do not revert to a bare `__file__` dirname.

### Telemetry `INVALID_HOST` / `INVALID_SWITCH`

Only `h1`–`h8` and `s1`–`s6` are accepted. IPs such as `127.0.0.1` and extra flags such as `--cmd` are rejected.

### Telemetry `IPERF_SERVER_FAILED` / leftover iperf3

Confirm iperf3 is installed on the Ubuntu host (`iperf3 -v`). Re-run; the gateway uses one-shot `iperf3 -s -1` and then `pkill -x iperf3` in the destination namespace. If a process remains, `sudo pkill -x iperf3` and investigate, then re-verify baseline flows were not changed.

### Telemetry `COMMAND_TIMEOUT` / `PARSE_ERROR`

Bounded ping/iperf hit the hard timeout, or output was not parseable. This is a tool failure (`ok: false`), not a connectivity diagnosis. Check the host namespace is healthy with a Mininet CLI ping before retrying.

### Agent fails to start because D1 is unavailable

Run `uv run --project agent python -m agent.setup_d1`. Confirm the root `.env`
contains `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`, and
`CLOUDFLARE_D1_DATABASE_ID`, and that outbound HTTPS to the Cloudflare API is
available. HTTP 403 normally means the account token lacks D1 Write permission
or does not cover the selected account/database. The AI Gateway token cannot be
used in place of the account API token.

### Docker / container resource issue

The reference container is capped (`--memory=640m`, JVM `-Xmx256m`) for a small host. Inspect `docker logs onos` and `./scripts/verify_onos.sh`. Do not invent unrelated Docker “fixes”. Host Java is not required.

---

## Safety and experimental controls

- OVS **secure** fail mode (no uncontrolled bridge fallback when the controller is gone)
- No NORMAL forwarding for the project datapath
- No STP baseline
- No uncontrolled FLOOD baseline
- `org.onosproject.fwd` inactive
- Planned F4: narrow match, timeout/watchdog, low-rate loop traffic
- Reset between experiments
- No credentials or unrestricted shell to the LLM
- No injector ground truth to diagnostic methods
- No secrets committed to Git (`.env`; custom ONOS REST credentials if the reference `onos` / `rocks` pair is replaced)

These are both **dataplane safety** and **experiment integrity** controls.

---

## Optional extensions

🔬 Not mandatory. Not implemented.

### h6 multihoming

- `h6-eth0` → s5, `10.0.0.6/24` (primary, used by baseline)
- `h6-eth1` → s6, no baseline IPv4 (test/secondary)

Not one of the five required faults.

### Constrained automatic repair

Optional one-case link-failure reroute **after** the core diagnosis experiment is complete. Not implemented.

---

## End-to-end workflow

### A. Workflow available today ✅

1. `./setup/setup_ubuntu.sh` then `./setup/verify_environment.sh`
2. `./setup/setup_onos.sh` then `./scripts/verify_onos.sh`
3. Launch `main6s8h` (see [Starting the network](#starting-the-network))
4. `sudo ./scripts/verify_main_openflow.sh` and `./scripts/verify_onos.sh`
5. `python3 forwarding/baseline_forwarding.py install` then `verify`
6. Mininet `pingall` → 56/56, 0% dropped
7. Collect structured telemetry ✅ (`python3 -m telemetry.cli get-topology`; `./scripts/verify_telemetry.sh`)
8. Inject F1 ✅ (`python3 -m faults.cli inject --scenario F1`)
9. Observe with telemetry ✅ (targeted pings / topology / ports)
10. Reset F1 ✅ (`python3 -m faults.cli reset`; or `./scripts/verify_fault_f1.sh`)
11. Verify healthy baseline again ✅ (20 directed links; pingall 56/56)
12. `python3 forwarding/baseline_forwarding.py remove` and/or `sudo mn -c`; `docker stop onos` if shutting down the controller

### B. Full planned experiment workflow 🟡

Unfinished steps are marked.

1. Setup environment ✅
2. Start ONOS ✅
3. Start topology ✅
4. Install baseline forwarding ✅
5. Verify healthy baseline ✅
6. Inject one fault ✅ (Fault Catalogue v1: F1–F5)
7. Present **only a symptom** to the diagnostic method 🟡
8. Collect structured telemetry ✅
9. Obtain LLM or scripted diagnosis 🟡
10. Log result 🟡
11. Compare diagnosis to hidden ground truth 🟡
12. Reset network ✅ (`python3 -m faults.cli reset`)
13. Verify healthy state ✅
14. Repeat 🟡

---

## Repository layout

| Path | Role |
| --- | --- |
| `setup/` | `setup_ubuntu.sh`, `setup_onos.sh`, `verify_environment.sh` |
| `scripts/` | `verify_onos.sh`, `verify_main_openflow.sh`, `verify_telemetry.sh`, `verify_fault_f1.sh` |
| `topologies/` | `main_topology.py`, canonical `spec.py`, plus progress-only Mininet tests |
| `forwarding/` | ONOS baseline provisioner |
| `telemetry/` | Bounded structured diagnostic gateway (M4; Ubuntu live evidence 27 August 2026) |
| `faults/` | Operator F1 injector/reset (M5; Ubuntu live evidence 27 August 2026) — not an LLM tool |
| `controllers/` | Historical Ryu-era `main_controller.py` — **not** the runtime controller |
| `tests/` | Static topology, forwarding, telemetry, and fault tests |
| `evidence/progress/` | Runtime evidence (ONOS, forwarding, telemetry, faults) |
| `docs/` | This manual, ONOS setup, decisions, Part A report |
| `docs/reports/part-a/` | Canonical Part A source, figures, generated DOCX/PDF |
| `.cursor/rules/` | Always-on project constraints including this manual’s sync rule |

**Implemented starter:** `agent/` (chat harness, tools, Cloudflare D1, UI).

**Planned, not present:** `baseline/` (scripted troubleshooter), `experiments/`.

Do not run `ryu-manager controllers/main_controller.py`. Ryu is not installed.

Progress topologies (`progress5s2h`, `progressbw10`, `progressimpaired`) are early Mininet capability tests, not the project datapath.

---

## Development and Git workflow

| Branch | Purpose |
| --- | --- |
| `master` | Stable / submission-ready |
| `develop` | Integration |
| `feature/*` | Individual work |

```bash
git switch develop
git pull origin develop
git switch -c feature/<short-name>
```

No force pushes. Do not commit `.env`, credentials, `incoming/`, or Word lock files. Commit runtime evidence only when it was actually observed.

See `CONTRIBUTING.md` for collaboration details. This manual is an operator guide, not a full developer handbook.

---

## Keeping this manual current

This is a **living** document (`docs/user-guide.md`).

Update it in the **same task** when behaviour changes, including:

- install/setup scripts, dependencies, verification
- Docker/ONOS version, ports, endpoints, applications
- topology, addresses, MACs, port map
- forwarding rules, priorities, flow counts
- telemetry tools/schemas
- fault injection and reset commands
- LLM invocation, model, diagnosis schema
- scripted troubleshooter behaviour
- evaluation workflow and expected outputs
- troubleshooting steps and milestone status

When a feature moves from planned → implemented:

1. Change its status mark
2. Replace conceptual text with **actual** commands/API
3. Include only runtime-verified expected output
4. Update troubleshooting/reset if affected

Do not rewrite historical evidence to claim unobserved results.

Cursor must inspect this file on every relevant code/config change. See `.cursor/rules/coms6200-project.mdc`.
