# LLM-Based Network Troubleshooting Agent

COMS6200 university project.

This project will evaluate whether a tool-using LLM can diagnose and localise controlled faults in an OpenFlow-based Mininet environment, and how that compares with a deterministic scripted troubleshooting baseline.

## 1. Project Overview

The research question is:

> How accurately and efficiently can a tool-using LLM agent diagnose and localise common faults in an OpenFlow-controlled Mininet network compared with a deterministic scripted troubleshooting baseline?

The intended study is deliberately small: one Layer-2 topology, five controlled fault types, one OpenAI tool-using agent, one scripted baseline, and repeatable experiments with structured logging.

## 2. Project Status

**M0 — Reproducible Environment Bootstrap: Completed**

The project's **base Mininet/Open vSwitch environment** has been installed and verified on the team Ubuntu server.

M0 verifies only that base environment. It does **not** verify later controller, OpenFlow, or project components.

What exists now:

- repository documentation
- Ubuntu setup and verification scripts
- a verified base Mininet/Open vSwitch environment on the team Ubuntu server
- Git workflow notes
- secret-handling placeholders
- Cursor project rules
- a directory for the Part A report

The following have **not** been installed or verified:

- Ryu
- OS-Ken
- OpenFlow 1.3 controller operation
- the final 6-switch / 8-host topology
- telemetry
- fault injection
- OpenAI LLM agent
- the deterministic baseline
- experiments

## 3. Planned Architecture

These components are **planned**, not all implemented.

```
Mininet / Open vSwitch
        ↓
OpenFlow 1.3
        ↓
Ryu controller
        ↓
structured telemetry gateway
        ↓
LLM agent OR deterministic baseline
        ↓
structured diagnosis
        ↓
evaluation/logger
        ↓
optional constrained repair
```

**Primary intended controller: Ryu.**

Because compatibility with the selected Python/Ubuntu environment still needs to be validated, OS-Ken is retained as a fallback only if Ryu becomes a genuine implementation blocker. OS-Ken will not be installed or selected automatically.

**Planned main topology** (not implemented in this milestone):

- 6 switches
- 8 hosts
- Layer 2
- two redundant core switches
- four dual-homed access switches

**Planned faults** (not implemented in this milestone):

| ID | Fault |
| --- | --- |
| F1 | Link failure |
| F2 | Congestion |
| F3 | ACL / policy error |
| F4 | Forwarding loop |
| F5 | Missing / incorrect OpenFlow rule |

The project may later include **one optional constrained link-failure reroute demonstration**. Automated remediation is not the current priority. Do not add extra mandatory faults.

## 4. Verified Base Environment

### Verified reference environment

The following **base Mininet/Open vSwitch environment** has been verified on the team Ubuntu server by running `./setup/verify_environment.sh`.

This is the team's currently verified **reference** result. Do not treat it as a result from Kali or any other distribution.

This is **not** a verification of Ryu, OS-Ken, OpenFlow 1.3 controller operation, the planned topology, telemetry, fault injection, the LLM agent, the baseline, or experiments.

Observed versions and results:

- Ubuntu 24.04.4 LTS
- Python 3.12.3
- Git 2.43.0
- Mininet 2.3.0
- Open vSwitch 3.3.9
- iperf3 3.16
- `openvswitch-switch` service: active
- Basic Mininet/OVS test: `mn --switch ovsbr --test pingall`
- Result: 0% dropped, 2/2 received
- M0 verification summary: PASS: 10, FAIL: 0, WARNING: 0

Ryu and OS-Ken were not installed during M0 and have not been verified.

### Compatibility policy

The project is intended to run on Linux.

Ubuntu 24.04.4 LTS is the team's currently verified reference environment.

Other Linux distributions such as Debian or Kali may also be used if they satisfy the project's environment verification checks. Passing `./setup/verify_environment.sh` means the environment has passed the current M0 Mininet/Open vSwitch **capability** checks. It does **not** mean controller compatibility has been verified, and it does **not** mean every Linux distribution is officially supported.

## 5. Quick Start

These commands assume you have permission to access the team repository.

```bash
git clone https://github.com/dhotrey/COMS6200-Project.git
cd COMS6200-Project
git switch develop
chmod +x setup/*.sh
./setup/setup_ubuntu.sh
./setup/verify_environment.sh
```

Run the setup and verification scripts on Linux, not on macOS or Windows. Ubuntu 24.04.4 is the verified reference; other Linux systems may be used only if verification passes.

## 6. Ubuntu Environment Setup

`setup/setup_ubuntu.sh` remains the M0 installer. Ubuntu 24.04 is the primary tested target. apt-based Debian-family systems such as Debian or Kali may be able to use it, but package availability can differ. It does not provide universal Linux installation support.

On an apt-based Linux host:

```bash
chmod +x setup/*.sh
./setup/setup_ubuntu.sh
```

The script updates apt, installs Git, Mininet, Open vSwitch, iperf3, Python 3, pip, venv, jq, and curl, attempts to enable/start Open vSwitch when the Ubuntu-style service unit exists, and creates a `.venv` virtual environment if it does not already exist.

If `apt` is not available, the script stops and asks you to install equivalent dependencies manually.

It does **not** install Ryu, OS-Ken, the OpenAI SDK, or other LLM libraries.

The script cannot activate `.venv` in your current shell. After it finishes, run:

```bash
source .venv/bin/activate
```

Always follow setup with:

```bash
./setup/verify_environment.sh
```

## 7. Environment Verification

```bash
./setup/verify_environment.sh
```

Verification is **capability-based**, not Ubuntu-name-based. It reports PASS / FAIL / WARNING for required project capabilities: Linux, Python 3, Git, Mininet, Open vSwitch tools, iperf3, Open vSwitch runtime, and a basic Mininet connectivity test (`mn --switch ovsbr --test pingall`, using `sudo` only when the caller is not root).

Distribution name is informational. A Debian or Kali host can receive Overall: SUCCESS if the required capabilities work. A passing result means only that the current M0 Mininet/Open vSwitch checks succeeded. It is **not** evidence that Ryu, OS-Ken, or OpenFlow 1.3 controller integration is working.

**Observed M0 result on the team Ubuntu server:**

- Basic Mininet/OVS test: `mn --switch ovsbr --test pingall`
- Result: 0% dropped, 2/2 received
- Summary: PASS: 10, FAIL: 0, WARNING: 0

## 8. macOS / Windows Development

Cursor, Git, documentation, and Python code editing may be done from macOS or Windows.

Mininet and Open vSwitch experiments must be executed in a Linux environment such as:

- Ubuntu server (verified reference: Ubuntu 24.04.4 LTS)
- Ubuntu VM
- Debian or Kali, if `./setup/verify_environment.sh` passes
- another Linux workstation/server that passes the same capability checks

Do not redesign the project to run Mininet natively on macOS. Do not treat every Linux distribution as officially supported.

## 9. Git Workflow

| Branch | Purpose |
| --- | --- |
| `master` | Stable / submission-ready |
| `develop` | Shared integration / development |
| `feature/*` | Individual tasks |

Do not do normal development on `master`.

Example workflow:

```bash
git switch develop
git pull origin develop
git switch -c feature/<short-name>
```

After work:

```bash
git add ...
git commit -m "..."
git push -u origin feature/<short-name>
```

Feature branches should normally be reviewed and merged into `develop`. Do not push experimental work directly to `master`.

Git operations (commit, push, merge, rebase) are controlled by the human team, not by automated agents.

## 10. Secrets and OpenAI API

OpenAI credentials will eventually be loaded through `OPENAI_API_KEY` from a local `.env` file or an environment variable.

- Copy `.env.example` to `.env` when the agent milestone begins.
- Never commit `.env` or real API keys.
- Do not put secrets in `README.md`, scripts, or source files.

## 11. Planned Repository Structure

This is the expected **future** layout. Implementation directories are not all created yet.

```
COMS6200-Project/
│
├── README.md
├── CONTRIBUTING.md
├── .gitignore
├── .env.example
├── requirements.txt
│
├── .cursor/
│   └── rules/
│       └── coms6200-project.mdc
│
├── setup/
│   ├── setup_ubuntu.sh
│   └── verify_environment.sh
│
├── topology/
│   └── main_topology.py
│
├── controller/
│   ├── main_controller.py
│   ├── forwarding.py
│   └── arp_handler.py
│
├── telemetry/
│   ├── topology.py
│   ├── reachability.py
│   ├── ports.py
│   ├── flows.py
│   └── performance.py
│
├── faults/
│   ├── injector.py
│   ├── reset.py
│   └── scenarios/
│
├── agent/
│   ├── tools.py
│   ├── schemas.py
│   ├── prompts.py
│   └── runner.py
│
├── baseline/
│   └── troubleshooter.py
│
├── experiments/
│   ├── runner.py
│   ├── evaluator.py
│   └── config.yaml
│
├── tests/
│
├── logs/
│
├── results/
│
└── docs/
    ├── architecture/
    ├── evidence/
    └── reports/
        ├── part-a/
        └── final/
```

## 12. Current Milestone

**M0 — Reproducible Environment Bootstrap: Completed**

M0 success criteria were met:

- repository setup documentation exists
- Ubuntu setup script exists
- verification script exists
- Git workflow is documented
- secrets are protected
- Cursor project rules exist
- the setup and verification scripts were executed successfully on the real Ubuntu server
- the base Mininet/OVS checks returned 10 PASS / 0 FAIL / 0 WARNING

M0 does **not** mean the SDN project itself is implemented. It does **not** verify Ryu, OS-Ken, OpenFlow 1.3 controller operation, the planned topology, telemetry, fault injection, the LLM agent, the baseline, or experiments.

## 13. Next Milestone

**M1 — Main Mininet Topology**

Implement and validate the agreed 6-switch, 8-host, dual-core Layer-2 Mininet topology with deterministic host addressing and link structure.

Controller integration, OpenFlow 1.3 forwarding, telemetry, fault injection, and LLM integration remain later milestones.

M1 has not been started.

Milestone plan:

- M0 — Reproducible Environment Bootstrap — Completed
- M1 — Main Mininet Topology
- M2 — Controller + OpenFlow 1.3 Integration
- M3 — Deterministic Normal Forwarding
- M4 — Structured Telemetry
- M5 — First Automated Fault + Reset
- M6 — First LLM Tool-Calling Diagnosis

## Team Journal

Preserved from the original repository README.

### Week 3

- Aryan: minor research about the project, setup the github repo.
- Stephen
- Molly
- Amir

### M0 environment verification

- Amir Latifi: completed the M0 reproducible environment bootstrap and real-server verification. Ubuntu 24.04.4 LTS; Mininet and Open vSwitch installed via the repository setup/verification scripts; basic Mininet connectivity test (`mn --switch ovsbr --test pingall`) succeeded with 0% dropped (2/2 received); verification summary 10 PASS / 0 FAIL / 0 WARNING.
