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
| Deterministic scripted troubleshooting baseline | ✅ Implemented ([baseline](../baseline/README.md)). Non-formal F1–F5 dry runs only. |
| Diagnosis evaluator | ✅ Protocol v1 rubric ([experiments](../experiments/README.md)). |
| Experiment runner | ✅ Dry-run mode only. Formal mode is refused. |
| LLM tool-calling integration | ✅ Harness implemented (UI loads F1–F5). WSL2 F1–F5 and Ubuntu F2 runs are pilots, not the formal dataset. See [results](results/llm-diagnosis.md), [F2 observability pilot](results/f2-observability-pilot.md), and [F2 link-metrics pilot](results/f2-link-metrics-pilot.md). |
| Experimental Protocol v1 | 🟡 Frozen candidate ([protocol](experiments/protocol-v1.md)). Primary model `gpt-5.6-sol` / `medium` is approved. Formal trials have not been collected. |
| Repeated evaluation experiments | 🟡 Not started. Formal collection is blocked. |
| Ring topology `ring5s5h` | 🟡 Topology, `COMS6200_TOPOLOGY` selection, ring baseline forwarding, and draft fault catalogue `ring5s5h-v1` (F1–F5) implemented with static tests ([ring topology](#ring-topology), [ring faults](#ring-fault-catalogue-ring5s5h-v1)). Not run against ONOS. Not part of protocol v1. |
| h6 multihoming / failover experiment | 🔬 |
| Constrained automatic link-failure repair | 🔬 |

Do not treat a 🟡 or 🔬 item as **runtime-verified complete**. Unimplemented
sections must not invent CLIs.

**Two different “baseline” terms**

- **Baseline forwarding** ✅ — ONOS application `org.coms6200.baseline`. Network datapath for healthy host connectivity.
- **Scripted troubleshooting baseline** ✅ — diagnostic comparator in `baseline/`. Uses the same telemetry as the LLM. Formal trials have not been run.

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
9. [Ring topology](#ring-topology)
10. [Starting the network](#starting-the-network) (includes [session start / stop / inject](#session-start--stop--inject))
11. [Verifying controller integration](#verifying-controller-integration)
12. [ONOS host discovery](#onos-host-discovery)
13. [Deterministic baseline forwarding](#deterministic-baseline-forwarding)
14. [Healthy network checklist](#healthy-network-checklist)
15. [Structured telemetry gateway](#structured-telemetry-gateway)
16. [Fault injection](#fault-injection)
17. [Operator vs diagnostic-agent view](#operator-vs-diagnostic-agent-view)
18. [Asking the LLM for a diagnosis](#asking-the-llm-for-a-diagnosis) (includes [diagnosis sessions per scenario](#diagnosis-sessions-per-scenario-f1f5))
19. [Expected diagnostic output](#expected-diagnostic-output)
20. [Scripted troubleshooting baseline](#scripted-troubleshooting-baseline)
21. [Resetting the testbed](#resetting-the-testbed)
22. [Troubleshooting the testbed](#troubleshooting-the-testbed)
23. [Safety and experimental controls](#safety-and-experimental-controls)
24. [Optional extensions](#optional-extensions)
25. [End-to-end workflow](#end-to-end-workflow)
26. [Repository layout](#repository-layout)
27. [Development and Git workflow](#development-and-git-workflow)
28. [Keeping this manual current](#keeping-this-manual-current)

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

Implemented through M5B (Ubuntu live evidence 27 August 2026; F1–F5 operator injector):

```
Mininet hosts
    ↓
Open vSwitch
    ↓ OpenFlow 1.3
ONOS 2.7.0
    ↓ read-only REST (internal to the gateway only)
    + configured Mininet host map (`topologies/spec.py`)
Structured Telemetry / Tool Gateway
    ↓
OpenAI LLM Agent (`agent/` chat harness) → conversational diagnosis
```

The LLM agent is implemented and loads F1–F5 from its UI. Test results:
[LLM diagnosis test results](results/llm-diagnosis.md). Runs on the Ubuntu
reference host are still pending (🟡).

Still planned:

```
Structured Telemetry / Tool Gateway
    ↓
    ├── OpenAI LLM Agent (implemented; free-text answers today)
    └── Deterministic Scripted Troubleshooting Baseline  🟡
            ↓
    Structured Diagnosis  🟡
            ↓
    Evaluator / Logger  🟡 (scoring is manual today)
```

Ground truth path (injector ✅ F1–F5; evaluator 🟡; evaluator-only):

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
| WSL2 Ubuntu 24.04.4 (Windows 11) | Capability-based only | Kernel 6.18 provides `openvswitch`, `sch_tbf`, namespaces and veth; testbed, F1–F5 and the chat harness ran on 23 September 2026 (`evidence/progress/llm/`). Enable systemd; run from a clone in the WSL filesystem, not `/mnt/c` (Windows CRLF checkouts break the bash scripts). Not milestone evidence |

Native Windows cannot run the testbed or fault controls. The harness UI can
open there, but **Load scenario** / **Reset** return HTTP 500 (`os.geteuid` is
Linux-only) and host tools cannot reach Mininet.

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

Mininet is separate: `sudo mn -c` and `sudo mn --custom ...` remain required on typical Linux hosts if you use the interactive CLI. `./scripts/testbed.sh start` starts the same topology in the background.

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

## Ring topology

🟡 File: `topologies/ring_topology.py` (built from `topologies/ring_spec.py`)  
Mininet name: `ring5s5h`  
Layer 2, `10.0.0.0/24`, OpenFlow 1.3, `failMode=secure`. STP is not enabled.

A second topology for running fault scenarios on a different shape. It does not replace `main6s8h`, and it is **not** part of Experimental Protocol v1.

Five switches in one physical ring `s1–s2–s3–s4–s5–s1`, one host per switch. 5 switches, 5 hosts, 5 inter-switch links, 5 host-switch links, 10 physical links.

**Implemented (static tests only):** topology and spec; topology selection with `COMS6200_TOPOLOGY=ring5s5h`, which switches the telemetry gateway, baseline forwarding, `scripts/testbed.sh`, and the fault catalogue; ring baseline forwarding (38 flows, s5–s1 link unused); draft fault catalogue `ring5s5h-v1` ([ring faults](#ring-fault-catalogue-ring5s5h-v1)).  
**Not yet done:** run against ONOS and verify the ring faults live (`scripts/verify_faults.py`). The protocol v1 experiment runner refuses the ring.

| Switch | Port 1 | Port 2 | Port 3 | ONOS device ID |
| --- | --- | --- | --- | --- |
| s1 | s2 p2 | s5 p1 | h1 | `of:0000000000000101` |
| s2 | s3 p2 | s1 p1 | h2 | `of:0000000000000102` |
| s3 | s4 p2 | s2 p1 | h3 | `of:0000000000000103` |
| s4 | s5 p2 | s3 p1 | h4 | `of:0000000000000104` |
| s5 | s1 p2 | s4 p1 | h5 | `of:0000000000000105` |

Hosts h1–h5 use `10.0.0.N/24` and MAC `00:00:00:00:00:0N`, all on `hN-eth0`.

The DPIDs deliberately differ from `main6s8h`'s `0x1`–`0x6`, so ONOS does not re-push stale `main6s8h` flow rules onto ring switches that share a device ID.

### Selecting the topology

`COMS6200_TOPOLOGY` picks the topology for every project tool that reads `topologies/active.py`: the telemetry gateway (and so the agent), baseline forwarding, and `scripts/testbed.sh`. Unset or `main6s8h` is the default and leaves all `main6s8h` behaviour unchanged. An unknown value is an error.

| | `main6s8h` (default) | `ring5s5h` |
| --- | --- | --- |
| Hosts / switches in tool schemas | h1–h8 / s1–s6 | h1–h5 / s1–s5 |
| `get_link_metrics` ports | 1–5 | 1–3 |
| ONOS devices / directed links expected by `testbed.sh` | 6 / 20 | 5 / 10 |
| Baseline flows | 56 | 38 |
| Fault catalogue | v1 (frozen) | `ring5s5h-v1` (draft) |

Export it once per shell and use the same value for every command in the session, including the agent server. `sudo` drops it unless passed through, so root commands need `sudo --preserve-env=COMS6200_TOPOLOGY,ONOS_USER,ONOS_PASSWORD ...`. `testbed.sh` already passes it through.

### Running the ring

Only one topology can run at a time (both use switch names `s1`–`s5`). Stop the running one with `./scripts/testbed.sh stop`, using the `COMS6200_TOPOLOGY` it was started with.

```bash
export COMS6200_TOPOLOGY=ring5s5h
./scripts/testbed.sh start    # OVS + ONOS + background ring5s5h + 38 baseline flows
./scripts/testbed.sh status
./scripts/testbed.sh stop     # removes the ring baseline flows, then stops Mininet
```

For `ring5s5h`, `stop` removes the ring's baseline flows while the switches are still connected. ONOS keeps rules for disconnected devices, and the `main6s8h` verification scripts count every `org.coms6200.baseline` flow. The `main6s8h` stop procedure is unchanged.

Manual path, with ONOS up:

```bash
sudo mn --custom topologies/ring_topology.py \
  --topo ring5s5h \
  --controller=remote,ip=127.0.0.1,port=6653 \
  --switch=ovsk
```

Then, from another shell with `COMS6200_TOPOLOGY=ring5s5h` exported, run `python3 forwarding/baseline_forwarding.py install` and `verify`. Run `remove` before exiting Mininet.

The ring is a physical loop. Do not run it with `--controller=none`, `--switch ovsbr`, NORMAL, or `org.onosproject.fwd`. `verify_main_openflow.sh` and `verify_telemetry.sh` check `main6s8h` and do not apply. Use `sudo ovs-vsctl show`, `./scripts/verify_onos.sh`, and `baseline_forwarding.py verify` instead.

Not yet runtime verified. The expected result is 5 OF_13 devices, 10 directed links, `verify` passing with 38 flows, and a working `pingall`.

Static checks (no Mininet required):

```bash
python3 tests/test_ring_static.py
python3 tests/test_ring_forwarding.py
python3 tests/test_topology_selector.py
python3 tests/test_ring_faults.py
```

Full port map and launch notes: `topologies/README.md`. Ring forwarding table: `forwarding/README.md`.

---

## Starting the network

ONOS must be up first. Switches request OpenFlow 1.3 and secure fail mode in the topology. Do not use `--controller=none`, `--switch ovsbr`, NORMAL, STP, or `org.onosproject.fwd`.

### Session start / stop / inject

Operator convenience for bringing a **previously installed** testbed up and down. It does not install Mininet, OVS, Docker, or the ONOS image — run `./setup/setup_ubuntu.sh` and `./setup/setup_onos.sh` once first. This helper has **not** been claimed as Ubuntu milestone evidence; the manual `mn` path below remains valid.

```bash
./scripts/testbed.sh start           # OVS + ONOS + background main6s8h + baseline flows
./scripts/testbed.sh inject F1       # or F2 F3 F4 F5 (also accepted: f1 or 1)
./scripts/testbed.sh reset           # clear the active catalogue fault
./scripts/testbed.sh status
./scripts/testbed.sh stop            # reset fault, stop Mininet; ONOS stays up
./scripts/testbed.sh stop --with-onos  # also stop the ONOS container
```

Normal experiment cycle is `start`, the run, `reset` or `stop`. `stop` does not stop a healthy ONOS container. `stop --with-onos` is the explicit operator shutdown. `start` reuses an ONOS that is already answering REST with its OpenFlow port listening. It does not treat REST alone as a finished testbed: after Mininet starts it waits for 6 OF_13 switches and 20 directed links (counts come from the selected topology; see [ring topology](#selecting-the-topology)). If that attach fails, it stops the temporary Mininet session, recreates only the `onos` container once, and retries. A second failure exits with an error.

`start` leaves Mininet running in the background (no `mininet>` prompt). Host `ping`/`iperf` through the telemetry gateway still work. `inject` resets any already-active catalogue fault first, then injects the requested scenario. Do not tell the LLM the scenario id.

If an interactive `mininet>` session already owns the switches, exit it or run `stop` before `start`. First-time ONOS install is still `./setup/setup_onos.sh`. REST defaults to `onos` / `rocks`; override with `ONOS_USER` / `ONOS_PASSWORD`.

The same steps, expanded by hand:

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

Do not use plain `sudo python3 ...` if that drops `ONOS_*`. For `ring5s5h`, also
export `COMS6200_TOPOLOGY=ring5s5h` and add it to `--preserve-env`; otherwise
the gateway validates against `main6s8h` ([selecting the topology](#selecting-the-topology)).
Passwords must not appear in telemetry JSON. CLI writes JSON to stdout; diagnostics may go to
stderr. Docker access is unrelated: do not prefix these commands with
`sudo docker`.

### Python API

```python
from telemetry import TelemetryGateway

gw = TelemetryGateway()
gw.get_topology()
gw.get_port_status("s3")
gw.get_port_stats("s3")
gw.get_link_metrics("s1", 4)       # fixed 2 s window; known switch port only
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
| `python3 -m telemetry.cli get-link-metrics --switch s1 --port 4` | `get_link_metrics(s1, 4)` |
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
| `get_link_metrics(sw, port)` | kernel interface counters and filtered queue counters over a fixed 2 s window | peer, enabled, packet/byte deltas, bit and packet rates, drop/error deltas, end-of-window queue backlog, overlimit and requeue deltas; unavailable counters are null | ✅ |
| `get_flow_table(sw)` | ONOS `/flows` | id, table, state, priority, app_id, selector, treatment, packets/bytes, life | ✅ |
| `iperf(src, dst)` | one-shot `iperf3 -s -1` in dst, client in src | sender and receiver bytes, bit rate, and duration, plus retransmits; legacy bytes/Mbit/s/duration follow the receiver when that side reports the field | ✅ |

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

`get_link_metrics(sw, port)` accepts only `s1`–`s6` and a port that exists on
that switch in the canonical topology. The gateway maps the pair to the switch
interface itself. The sample window is fixed at about 2 seconds and cannot be
chosen by the caller. Byte, packet, drop, and error deltas, plus the derived
rates, come from kernel interface counters. Queue backlog is the instantaneous
sample at the end of the window. Overlimit and requeue values are deltas across
the same window. If those queue counters cannot be read, the fields are null and
the rest of the measurement is still returned. The result does not include queue
configuration, a configured rate, latency, burst, or a fault label.

Ping destination is the configured primary IPv4 (never a caller-supplied IP).
iperf uses iperf3 JSON (`-J`), TCP only, duration 1–5 s. The result includes `sender_bytes`, `sender_bits_per_sec`, `sender_duration_sec`, `receiver_bytes`, `receiver_bits_per_sec`, `receiver_duration_sec`, and `retransmits`. Legacy `bytes_transferred`, `mbit_per_sec`, and `duration_sec` follow the receiver summary when that summary includes the field, including an explicit zero, and otherwise follow the sender summary. A receiver value of 0 with sender progress is a completed measurement. An iperf3 error string is `ok: false`, not a zero-throughput result. The gateway does not install a pass/fail throughput threshold and does not label a fault. After the test it terminates the
server process group and best-effort stops leftover **gateway** iperf3 only
(`pkill -f` matching its own port 5201). Mininet hosts share the root process
table, so the earlier unscoped `pkill -x iperf3` also stopped unrelated iperf3,
including the F2 background load on port 5202. The narrower cleanup is covered
by an offline test and was verified live on WSL2 (23 September 2026): the F2
background load survived an agent `iperf` call. Reference-host re-run pending.

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

Catalogue v1 is defined for `main6s8h`. `COMS6200_TOPOLOGY=ring5s5h` selects the ring's own catalogue instead ([below](#ring-fault-catalogue-ring5s5h-v1)). `inject` returns `TOPOLOGY_MISMATCH` unless the running switch ports are exactly the selected topology's, which covers a `sudo` that dropped the variable. `reset` returns `STATE_CATALOGUE_MISMATCH` for a fault injected under the other topology.

### Ring fault catalogue (`ring5s5h-v1`)

🟡 Draft, static tests only, **not runtime verified**. Not part of protocol v1. The experiment runner refuses non-`main6s8h` topologies.

Same IDs, families, mechanisms, rates and workloads as v1, at ring locations (`faults/ring_scenarios.py`). Every scenario breaks or slows h1→h5, so the v1 symptom prompts still apply. Baseline forwarding leaves s5–s1 unused, so h1→h5 crosses s1–s2–s3–s4–s5 even though s1 and s5 are directly connected.

| ID | Injected concept | Expected symptoms |
| --- | --- | --- |
| F1 Link failure | Disable s3–s4 (`s3-eth1`/`s4-eth2`) | {h1,h2,h3} ↔ {h4,h5} fail; ONOS 10 → 8 directed links |
| F2 Congestion | 1 Mbit/s TBF on `s2-eth1` (s2→s3) + background iperf h2→h4 | h1→h5 reachable, throughput ≤ 25% of healthy |
| F3 ACL / policy error | High-priority DROP h1→h5 on s4 | h1→h5 fails; h2→h5, h1→h4, h3→h5 work |
| F4 Forwarding loop | h1→h5 rules on all five switches, all clockwise, + 2 Mbit/s safety TBF on `s5-eth1` | h1→h5 fails; loop traffic on the unused s5–s1 link |
| F5 Missing baseline flow | Delete s2 baseline unicast for dest h5 | h1→h5, h2→h5 fail; h3→h5, h4→h5 work; 37 baseline flows |

```bash
export COMS6200_TOPOLOGY=ring5s5h
./scripts/testbed.sh start
./scripts/testbed.sh inject F1     # or F2 … F5
./scripts/testbed.sh reset
```

Live verification of every scenario (healthy gate, inject, expected symptoms, reset, healthy gate). Counts come from the selected topology:

```bash
sudo --preserve-env=COMS6200_TOPOLOGY,ONOS_USER,ONOS_PASSWORD python3 scripts/verify_faults.py   # or: ... F1 F3
```

`verify_faults.py` also runs on `main6s8h`, which cross-checks the verifier against the frozen catalogue. The frozen v1 record remains `verify_fault_catalogue.sh`.

### Operator CLI ✅

The package `faults/` is an **operator/evaluator** injector. It is **not** an LLM
tool. Do not expose fault CLI output, status, scenario IDs, or ground truth to
the diagnostic agent. Telemetry must never import fault state.

Requires **root** for mutations. The injector does **not** call `sudo` internally.

The harness UI **Load scenario** / **Reset** buttons call the same injector
(`POST /api/scenario/load` and `POST /api/scenario/reset`). They do not put the
scenario id in the chat prompt or tool schemas.

Session wrapper (resets an already-active catalogue fault before inject):

```bash
./scripts/testbed.sh inject F1   # or F2 F3 F4 F5
./scripts/testbed.sh reset
./scripts/testbed.sh status
```

Underlying operator CLI (same injector; `inject` here does **not** auto-reset):

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

The same five scenarios through the harness path (UI load → agent tools → UI
reset): `./scripts/verify_agent_scenarios.sh` ✅ (WSL2), see
[diagnosis sessions per scenario](#diagnosis-sessions-per-scenario-f1f5).

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

The conversational starter harness lives in `agent/`. Bring the testbed up first
(`./scripts/testbed.sh start` and `./scripts/testbed.sh inject Fn`, or the
manual Mininet path). From the repository root:

```sh
uv sync --project agent
uv run --project agent python -m agent
```

`python -m agent` asks for sudo so ping/iperf can enter Mininet namespaces, and
uses reference-lab ONOS REST `onos` / `rocks` unless `ONOS_USER` / `ONOS_PASSWORD`
are already set (shell or root `.env`). Stop any older non-root agent process
before restarting. Open http://127.0.0.1:8000. A directly opened `agent/index.html` is preview-only;
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

The telemetry tools are reused on the same machine. `nmap` runs one TCP-connect or UDP scan of a single port (0–65535) between two project hosts, using each destination's primary IPv4 address, with host discovery disabled, a 5 s host timeout, and a 20 s limit. It returns that port's protocol, state, and service name. Host probes retain Mininet namespace
privilege requirements. Follow [agent setup](../agent/README.md) for launch,
privileges, limits, Logfire, and offline tests. Run one server worker. Bring
the testbed up with `./scripts/testbed.sh start` (or interactive `mn`) before
sending diagnosis prompts.

The model picker offers Luna, Terra, Sol and Astra. The default selection is Sol
(`gpt-5.6-sol`) at thinking level `medium`.
A separate fault picker can **Load** or **Reset** F1–F5 on the live network.
That mutation is operator-only: the selected id is not sent in chat requests,
saved as assistant context, or written into the system prompt. Describe a
symptom; do not name F1–F5. Start a new conversation after changing the fault.
`./scripts/testbed.sh inject Fn` (F1–F5) remains valid.
Conversation history and turn measurements are stored in Cloudflare D1.
The chat window renders assistant Markdown (lists, emphasis, code). Tool calls
appear as faint one-line labels until hovered or clicked. The conversation
sidebar is drag-resizable; double-click a title or use the pencil control to
rename it (`PATCH /api/conversations/{id}`).
Tool delays default to 0. Protocol v1 keeps `TOOL_DELAY_MIN_SECONDS` and
`TOOL_DELAY_MAX_SECONDS` at 0, `MAX_TOOL_CALLS` at 14, and `MAX_TURN_SECONDS` at 300.
Execution and artificial-delay timings are recorded separately. Stop cancels
model generation; an in-flight bounded probe must finish cleanup before another
turn. Follow-up questions in the same conversation are supported: each send
appends to that conversation’s stored history. Start a new conversation after
resetting/changing scenarios to avoid stale context. The per-turn token stop is
off (`MAX_TURN_TOKENS=0`); tool-call and 300-second limits remain. This harness
does not load fault labels or injector state.

Example symptom-only prompts:

- “Diagnose why h1 cannot communicate with h5. Use the available diagnostic tools, identify the most likely root cause and localise the fault.”
- “Investigate why TCP throughput between h1 and h8 has degraded. Determine whether the issue is physical, congestion-related or forwarding-related.”
- “Investigate the connectivity failure affecting h3 to h6. Use only the available diagnostic tools and return evidence for your conclusion.”
- “Determine why traffic between h1 and h3 is failing even though the switches appear connected.”

Describe observable symptoms. Do not name the injector.

### Diagnosis sessions per scenario (F1–F5)

Formal prompts, repetition count, run order, and scoring are specified in
[Experimental Protocol v1](experiments/protocol-v1.md). That document is
pre-collection. The table below remains the operator reference for symptom
prompts. Do not paste the evidence or localisation columns into the chat.

✅ (WSL2) The harness loads all five catalogue faults through the same path
(**Load scenario** → `POST /api/scenario/load` → `agent/fault_control.py` →
`faults.injector`). The model receives the same prompt and tools for every
scenario; there is no per-scenario code path. Test results are kept in
[LLM diagnosis test results](results/llm-diagnosis.md). The evidence column below is the telemetry signature verified by
`verify_fault_fN.sh` on 27 August 2026 and by `verify_agent_scenarios.sh` on
WSL2, not a model answer.

Same procedure for every scenario:

1. `./scripts/testbed.sh start` (or the manual path) and confirm the [healthy network checklist](#healthy-network-checklist).
2. Set `TOOL_DELAY_MIN_SECONDS=0` and `TOOL_DELAY_MAX_SECONDS=0` in the root `.env` for real timings, then start the harness.
3. Load one fault: UI **Load scenario**, or `./scripts/testbed.sh inject Fn`.
4. Start a **new** conversation and send a symptom-only prompt.
5. Compare the answer with the operator-only localisation below.
6. UI **Reset** (or `./scripts/testbed.sh reset`); start a new conversation before the next fault.

Operator-only reference. Never paste the last two columns into the chat.

| Load | Symptom-only prompt (example) | Evidence reachable through the agent tools | Correct localisation |
| --- | --- | --- | --- |
| F1 | “h1 can no longer reach h5. Diagnose and localise the fault.” | `ping` h1→h5 fails; h1→h2 and h3→h5 succeed. `get_topology` observes 9 of 10 configured links. `get_port_status` shows s3 port 1 and s1 port 2 `enabled=false`. | Link failure s3:1 ↔ s1:2 |
| F2 | “Transfers from h1 to h5 are very slow. Investigate and localise the cause.” | `ping` h1→h5 succeeds with high RTT (~400 ms). `iperf` h1→h5 can show sender progress while `receiver_bytes` is 0; legacy bytes and Mbit/s follow the receiver. All ports enabled; flows unchanged. `get_port_stats(s1)` port 4 counters are available, but the ~1 s rate sample can read 0 (see F2 notes). `get_link_metrics(s1, 4)` adds a fixed 2 s port sample, end-of-window queue backlog, and overlimit/requeue deltas when the kernel provides them. | Congestion on s1:4 ↔ s5:1 |
| F3 | “h1 can no longer reach h5. Diagnose and localise the fault.” | `ping` h1→h5 fails; h2→h5 and h1→h6 succeed. Links/ports healthy. `get_flow_table(s3)` has a priority-50000 `org.coms6200.experiment` rule matching h1→h5 MACs with no output action (ONOS reports the treatment as `NOACTION`, i.e. drop). | Selective drop rule on s3 for h1→h5 |
| F4 | “h1 can no longer reach h5. Diagnose and localise the fault.” | `ping` h1→h5 fails; h1→h2 and h3→h5 succeed. `get_flow_table` on s3, s4 and s1 shows priority-50000 h1→h5 rules outputting s3:5 → s4:1 → s1:2, a cycle. | Forwarding loop s3 → s4 → s1 → s3 for h1→h5 |
| F5 | “h1 and h2 can no longer reach h5. Diagnose and localise the fault.” | `ping` h1→h5 and h2→h5 fail; h1→h6 and h3→h5 succeed. Links/ports healthy. `get_flow_table(s3)` has no priority-41000 rule for h5's MAC, while s4 does. | Missing baseline rule for h5 on s3 |

`get_topology` returns the host MAC map, so the model can relate flow-rule MACs
to h1–h8. F1, F3 and F4 intentionally share the same symptom; only the tool
evidence distinguishes them.

**F2 notes.** The 1 Mbit/s bottleneck is a Linux `tc` qdisc on `s1-eth4`; ONOS
does not report it, so the model must localise F2 by comparing `iperf`/`ping`
across paths (for example h1→h5 versus h1→h7) and port counters. The background
h3→h6 load stays up until F2 is reset (iperf3 `-t 0` on port 5202); the TBF
stays until the same reset. Tool delays for measurement runs are 0. The agent
tool cap default is 14. Agent `iperf` calls no longer stop that background
load (see [Tools](#tools)). In the WSL run on 23 September 2026,
`get_port_stats(s1)` reported `tx_bits_per_sec=0.0` on port 4 while the
background load was running; the two-sample rate is taken ~1 s apart and may
not see a fresh ONOS counter update (not investigated further), so the model
should not rely on that rate alone. The iperf tool now reports `sender_*` and
`receiver_*` separately. A completed test can have `receiver_bytes` 0 while
`sender_bytes` is greater than 0; legacy `bytes_transferred` and `mbit_per_sec`
follow that receiver value, including zero. That result is a measurement, not a
command failure.

#### Recording results

Record each scored run in [LLM diagnosis test results](results/llm-diagnosis.md),
the single results summary. Keep the full per-run detail (answer, tool calls,
tokens, cost, conversation id) in a dated evidence file under
`evidence/progress/llm/`. Rename the conversation (for example
`Test F3 · 5.6-luna · medium`) only after the run completes.

#### Harness path verification ✅ (WSL2)

`scripts/verify_agent_scenarios.sh` checks each scenario through the harness
path without sending model requests (no API credits). For each scenario it runs
the healthy gate, loads the fault with `agent.fault_control.load_scenario` (the
**Load scenario** button), calls `agent.tools.execute_tool` with the arguments
the model would send and asserts the evidence in the table above, checks that
tool observations contain no scenario id or ground-truth keys, resets with
`agent.fault_control.reset_scenario`, and repeats the healthy gate. For F2 it
also checks the background iperf3 client survives an agent `iperf` call.

Run as root on the testbed host, with no chat turn in progress:

```bash
export ONOS_USER=onos
export ONOS_PASSWORD=rocks
./scripts/verify_agent_scenarios.sh          # F1–F5 in order
./scripts/verify_agent_scenarios.sh F3 F5    # selected scenarios
```

Success line: `Agent scenario verification (F1 F2 F3 F4 F5): ALL CHECKS PASSED`.
Samples, including the exact observations the model would receive
(`observations_Fn.json`), are written to the printed `/tmp/coms6200-agent.*`
directory.

Latest run results: [LLM diagnosis test results](results/llm-diagnosis.md#harness-path-check-no-model).
**Not yet run on the Ubuntu reference host.**

---

## Expected diagnostic output

The starter produces ordinary conversational answers grounded in tool observations.
It does not enforce a diagnosis JSON schema. Tool arguments/results and turn
statistics are stored structurally. In the UI, tool results stay collapsed and
low-contrast until selected; measurements include
per-tool latency, per-model-request latency, whole-turn time, tokens summed over
all model rounds, cached/reasoning tokens, estimated cost, and invalid calls.
Cancelled or failed turns flag potentially incomplete usage.

A compatible structured diagnosis contract for the future scripted baseline and
evaluator remains planned; no automated diagnosis scoring is implemented.

---

## Scripted troubleshooting baseline

✅ Implemented. **This is not `org.coms6200.baseline`.**

| Term | What it is | Status |
| --- | --- | --- |
| Baseline forwarding | Datapath flows installed by `forwarding/baseline_forwarding.py` | ✅ |
| Scripted troubleshooting baseline | Deterministic diagnostic comparator in `baseline/` | ✅ Dry-run only |

The procedure reads the symptom, then uses topology, ping, port state, flow rules, and, when the complaint is slowness, iperf plus `get_link_metrics`. It stops at 14 gateway calls or 300 seconds. It does not receive a scenario id.

```bash
python3 -m baseline --prompt "h1 can no longer reach h5. Diagnose and localise the fault."
python3 -m experiments dry-run --method baseline --scenario F1
python3 -m experiments formal   # refused
```

`formal` does not start the 80-trial matrix. Details and the scoring rules are in [Experimental Protocol v1](experiments/protocol-v1.md) and [experiments/README.md](../experiments/README.md).

---

## Resetting the testbed

### Session stop

```bash
./scripts/testbed.sh reset    # clear F1–F5, leave Mininet/ONOS up
./scripts/testbed.sh stop     # reset fault, stop Mininet; ONOS stays up
./scripts/testbed.sh stop --with-onos
```

`stop` leaves the Open vSwitch service and the ONOS container running. The next session is `./scripts/testbed.sh start`. `stop --with-onos` is how an operator intentionally stops the controller.

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

Stop ONOS only when shutting the controller down:

```bash
./scripts/testbed.sh stop --with-onos
```

### After an injected fault (F1–F5) ✅

```bash
./scripts/testbed.sh reset          # or UI Reset, or: python3 -m faults.cli reset
python3 -m faults.cli status        # expect "active": false
python3 forwarding/baseline_forwarding.py verify
```

`reset` reads `/run/coms6200/fault-state.json` and undoes the active scenario:

| Scenario | Reset restores | Recovery when the state file is missing |
| --- | --- | --- |
| F1 | `s3-eth1` / `s1-eth2` UP; ONOS back to 20 directed links | `python3 -m faults.cli reset --force-f1` (same as `--force-scenario F1`) |
| F2 | TBF removed from `s1-eth4`; background iperf3 stopped | `python3 -m faults.cli reset --force-scenario F2` |
| F3 | experiment DROP flow removed | `python3 -m faults.cli reset --force-scenario F3` |
| F4 | loop experiment flows removed; safety TBF removed from `s3-eth5` | `python3 -m faults.cli reset --force-scenario F4` |
| F5 | missing s3→h5 baseline rule reinstalled (56 ADDED) | `python3 -m faults.cli reset --force-scenario F5` |

Healthy after reset: 20 directed links, 56 baseline ADDED, 0
`org.coms6200.experiment` flows, no TBF on `s1-eth4` / `s3-eth5`, `pingall`
56/56 (the gate used by `verify_fault_catalogue.sh`, all five passed on 27
August 2026). F1–F4 do not modify M3 baseline flows, so `install` is not
required after a clean reset. F5 reset reinstalls only the missing rule, with a
full `install` fallback.

`./scripts/testbed.sh stop` resets first. If that normal reset fails, it now
retries `--force-scenario` for each of F1–F5 (previously F1 only) before
stopping Mininet. Forced recovery applies only when no state file remains. This
normal reset path was live-checked on the Ubuntu server on 28 September 2026: stop after each of F1–F5 returned a clean baseline with ONOS left running. The force-scenario fallback, used only when that normal reset fails, remains a static test.

---

## Troubleshooting the testbed

### ONOS container not running

**Symptoms:** no listener on 6653/8181; Mininet switches fail to connect.

**Checks:** `./scripts/verify_onos.sh`, `docker ps --filter name=onos` (no sudo if `docker info` works).

**Action:** `./setup/setup_onos.sh` or `./scripts/testbed.sh start` (it starts a stopped container). Wait for REST and the OpenFlow port. A container that answers REST but never accepts switches is recreated once by `start`.

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

### Session helper refuses to start (`s1 already exists`)

An interactive `mininet>` session is already running, or a previous helper did not stop cleanly. Exit Mininet or run `./scripts/testbed.sh stop`, then `start` again.

### Stale Mininet / OVS state

```bash
./scripts/testbed.sh stop
./scripts/testbed.sh start
```

Or by hand: `sudo mn -c`, relaunch `main6s8h`, then `python3 forwarding/baseline_forwarding.py install`.

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

Only `h1`–`h8` and `s1`–`s6` are accepted (`h1`–`h5` and `s1`–`s5` with `COMS6200_TOPOLOGY=ring5s5h`). IPs such as `127.0.0.1` and extra flags such as `--cmd` are rejected. If valid names are rejected, or `s6` is accepted while the ring runs, the process has a different `COMS6200_TOPOLOGY` from the running network. Check `sudo --preserve-env`.

### Faults `TOPOLOGY_MISMATCH` / `STATE_CATALOGUE_MISMATCH`

`TOPOLOGY_MISMATCH` on `inject`: the running switch ports do not match the selected topology. The error's `missing`/`unexpected` lists show which ports differ. Usually `COMS6200_TOPOLOGY` was dropped by `sudo` or differs from the network you started. Add `--preserve-env=COMS6200_TOPOLOGY` or start the matching topology. Nothing was changed.

`STATE_CATALOGUE_MISMATCH` on `reset`: the active fault was injected under the other topology's catalogue. Re-run `reset` with the `COMS6200_TOPOLOGY` it was injected under. The state file is kept so the fault can still be cleared.

### Switching between `main6s8h` and `ring5s5h`

Stop with the same `COMS6200_TOPOLOGY` the session was started with, then start the other. For `ring5s5h`, `stop` removes the ring baseline flows first. If the ring was stopped some other way (for example `sudo mn -c`), ONOS can keep its rules for the disconnected ring DPIDs. `baseline_forwarding.py status` shows them as `otherDeviceAppFlows`, and the `main6s8h` verification scripts may count them. To clear them, start the ring again and stop it through the helper:

```bash
COMS6200_TOPOLOGY=ring5s5h ./scripts/testbed.sh start
COMS6200_TOPOLOGY=ring5s5h ./scripts/testbed.sh stop
```

### Telemetry `IPERF_SERVER_FAILED` / leftover iperf3

Confirm iperf3 is installed on the Ubuntu host (`iperf3 -v`). Re-run; the gateway uses one-shot `iperf3 -s -1` on port 5201 and then stops only its own port-5201 iperf3 (`pkill -f`). If a process remains, `sudo pkill -x iperf3` and investigate, then re-verify baseline flows were not changed. `pkill -x iperf3` also stops an active F2 background load; reload F2 afterwards.

### Telemetry `COMMAND_TIMEOUT` / `PARSE_ERROR`

Bounded ping/iperf hit the hard timeout, or output was not parseable. This is a tool failure (`ok: false`), not a connectivity diagnosis. Check the host namespace is healthy with a Mininet CLI ping before retrying.

### Agent tools report `ONOS_AUTH_FAILED` / ping `PARSE_ERROR` / iperf `Permission denied`

The chat process was missing ONOS REST credentials or was not root. Stop the old
server (Ctrl-C) and start it again from the repo root:

```bash
uv run --project agent python -m agent
```

Allow the sudo re-exec. You should see `uid=0` and `ONOS REST user=onos`. Then
start a **new** conversation; old failed tool results stay in the previous thread.

### Harness **Load scenario** works for one fault but not another

The banner shows the injector's error message. Run the same load/observe/reset
path outside the UI for that scenario to see which step fails:

```bash
./scripts/verify_agent_scenarios.sh F3
```

Common causes: the harness is not root (`Fault injection needs root`); ONOS REST
is down or has different credentials (F3–F5 use ONOS; F1–F2 do not); a
previous fault left state behind (`FAULT_ALREADY_ACTIVE` or
`EXPERIMENT_FLOWS_PRESENT`: **Reset**, or `python3 -m faults.cli reset
--force-scenario Fn`); `s1-eth4` / `s3-eth5` is not UP (F2/F4 `LINK_NOT_UP`).

### F2 session shows no cross-traffic on s1 port 4

The F2 background h3→h6 iperf3 and the TBF on `s1-eth4` both remain until
reset. If port 4 shows no cross-traffic, confirm F2 is still the active fault
(`python3 -m faults.cli status`) and that reset has not already run. Measurement
turns use tool delay 0 and a 14-call cap.

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
- F4: narrow h1→h5 match plus safety TBF (2 Mbit/s) on `s3-eth5`; removed on reset
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
3. Launch `main6s8h` — session helper `./scripts/testbed.sh start`, or the manual `mn` path in [Starting the network](#starting-the-network)
4. `sudo ./scripts/verify_main_openflow.sh` and `./scripts/verify_onos.sh`
5. Baseline flows: `start` already installs them; otherwise `python3 forwarding/baseline_forwarding.py install` then `verify`
6. Mininet `pingall` → 56/56, 0% dropped (interactive CLI only; background helper has no `mininet>` prompt)
7. Collect structured telemetry ✅ (`python3 -m telemetry.cli get-topology`; `./scripts/verify_telemetry.sh`)
8. Inject one fault Fn (F1–F5) ✅ (`./scripts/testbed.sh inject Fn`, harness **Load scenario**, or `python3 -m faults.cli inject --scenario Fn`)
9. Observe with telemetry ✅ (per-scenario evidence: [verified symptoms](#verified-symptoms-catalogue-v1); `./scripts/verify_fault_fN.sh`)
10. Ask the harness for a diagnosis ✅ (WSL2; [diagnosis sessions per scenario](#diagnosis-sessions-per-scenario-f1f5); harness path check `./scripts/verify_agent_scenarios.sh Fn`; record results in [results](results/llm-diagnosis.md))
11. Reset ✅ (`./scripts/testbed.sh reset`, harness **Reset**, or `python3 -m faults.cli reset`; see [after an injected fault](#after-an-injected-fault-f1f5-))
12. Verify healthy baseline again ✅ (20 directed links; 56 baseline ADDED; 0 experiment flows; pingall 56/56)
13. Session teardown `./scripts/testbed.sh stop` (ONOS stays up), or `python3 forwarding/baseline_forwarding.py remove` and/or `sudo mn -c`; `./scripts/testbed.sh stop --with-onos` if shutting down the controller

### B. Full planned experiment workflow 🟡

Unfinished steps are marked.

1. Setup environment ✅
2. Start ONOS ✅
3. Start topology ✅
4. Install baseline forwarding ✅
5. Verify healthy baseline ✅
6. Inject one fault ✅ (Fault Catalogue v1: F1–F5)
7. Present **only a symptom** to the diagnostic method — LLM ✅ (the harness never sends the scenario id); scripted baseline ✅ (symptom text only; dry runs)
8. Collect structured telemetry ✅
9. Obtain a diagnosis — LLM ✅ (chat harness; pilots in [results](results/llm-diagnosis.md)); scripted baseline ✅ (non-formal F1–F5 dry runs)
10. Log result — LLM ✅ (Cloudflare D1 for harness chats); dry-run records ✅ (`evidence/experiments/protocol-v1/dry-runs.jsonl`, labelled not formal)
11. Compare diagnosis to hidden ground truth — evaluator ✅ for dry runs. Formal scores have not been collected.
12. Reset network ✅ (`python3 -m faults.cli reset`)
13. Verify healthy state ✅
14. Repeat 🟡 Formal 8×2 matrix not started. One non-formal baseline pass per F1–F5 and one paired F2 dry run exist.

Harness pilots and the Phase 6–7 dry runs were exercised on the Ubuntu
reference host. Those records are not the formal dataset.

---

## Repository layout

| Path | Role |
| --- | --- |
| `setup/` | `setup_ubuntu.sh`, `setup_onos.sh`, `verify_environment.sh` |
| `scripts/` | `testbed.sh` (session start/stop/inject), `run_main6s8h.py`, `verify_onos.sh`, `verify_main_openflow.sh`, `verify_telemetry.sh`, `verify_fault_f1.sh` … `verify_fault_f5.sh`, `verify_fault_catalogue.sh`, `verify_agent_scenarios.sh` (harness path, F1–F5), `verify_faults.py` (data-driven, any catalogue) |
| `topologies/` | `main_topology.py`, canonical `spec.py`, `ring_topology.py` + `ring_spec.py` (`ring5s5h`, in development), `active.py` (`COMS6200_TOPOLOGY` selection), plus progress-only Mininet tests |
| `forwarding/` | ONOS baseline provisioner |
| `telemetry/` | Bounded structured diagnostic gateway (M4; Ubuntu live evidence 27 August 2026) |
| `faults/` | Operator Fault Catalogue v1 (F1–F5) injector/reset (M5/M5B; Ubuntu live evidence 27 August 2026), plus the draft `ring5s5h-v1` catalogue — not an LLM tool |
| `controllers/` | Historical Ryu-era `main_controller.py` — **not** the runtime controller |
| `tests/` | Static topology, forwarding, telemetry, and fault tests |
| `evidence/progress/` | Runtime evidence (ONOS, forwarding, telemetry, faults, LLM harness tests) |
| `docs/` | This manual, ONOS setup, decisions, Part A report, `results/llm-diagnosis.md` (LLM test results) |
| `docs/reports/part-a/` | Canonical Part A source, figures, generated DOCX/PDF |
| `.cursor/rules/` | Always-on project constraints including this manual’s sync rule |

**Implemented starter:** `agent/` (chat harness, tools, Cloudflare D1, UI).

**Implemented, dry-run only:** `baseline/` (scripted troubleshooter), `experiments/` (evaluator and runner). Formal `runs.jsonl` is not present.

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
