# LLM-Based Network Troubleshooting Agent

COMS6200 university project.

This project will evaluate whether a tool-using LLM can diagnose and localise controlled faults in an OpenFlow-based Mininet environment, and how that compares with a deterministic scripted troubleshooting baseline.

## 1. Project Overview

The research question is:

> How accurately and efficiently can a tool-using LLM agent diagnose and localise common faults in an OpenFlow-controlled Mininet network compared with a deterministic scripted troubleshooting baseline?

The intended study is deliberately small: one Layer-2 topology, five controlled fault types, one OpenAI tool-using agent, one scripted baseline, and repeatable experiments with structured logging.

## 2. Project Status

The project is currently in the **environment/bootstrap phase**.

What exists now:

- repository documentation
- Ubuntu setup and verification scripts
- Git workflow notes
- secret-handling placeholders
- Cursor project rules
- a directory for the Part A report

The following have **not** been demonstrated yet and must not be described as working:

- Ryu
- OpenFlow 1.3 controller integration
- telemetry
- fault injection
- LLM diagnosis
- the deterministic baseline
- the 6-switch / 8-host topology

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

## 4. Target Environment

Current target environment:

- Ubuntu 24.04.4 LTS
- Python 3.12.3

This environment is currently being validated. It is **not** a fully tested environment until `./setup/verify_environment.sh` has been executed successfully on the team Ubuntu server.

Mininet and Open vSwitch are installed by the setup script. Ryu and OS-Ken are **not** installed during bootstrap.

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

Run the setup and verification scripts on Ubuntu/Linux, not on macOS or Windows.

## 6. Ubuntu Environment Setup

On an Ubuntu host:

```bash
chmod +x setup/*.sh
./setup/setup_ubuntu.sh
```

The script updates apt, installs Git, Mininet, Open vSwitch, iperf3, Python 3, pip, venv, jq, and curl, enables/starts Open vSwitch, and creates a `.venv` virtual environment if it does not already exist.

It does **not** install Ryu, OS-Ken, the OpenAI SDK, or other LLM libraries.

The script cannot activate `.venv` in your current shell. After it finishes, run:

```bash
source .venv/bin/activate
```

## 7. Environment Verification

```bash
./setup/verify_environment.sh
```

This check reports PASS / FAIL / WARNING for OS, Python, Git, Mininet, Open vSwitch, iperf3, and the Open vSwitch service. It then runs one basic Mininet test:

```bash
sudo mn --switch ovsbr --test pingall
```

A passing result means only that Mininet and Open vSwitch can start a simple ping test. It is **not** evidence that the final Ryu/OpenFlow project architecture is working.

## 8. macOS / Windows Development

Cursor, Git, documentation, and Python code editing may be done from macOS or Windows.

Mininet and Open vSwitch experiments must be executed in a Linux environment such as:

- Ubuntu server
- Ubuntu VM
- Linux workstation

Do not redesign the project to run Mininet natively on macOS.

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

**M0 — Reproducible environment bootstrap.**

Success means:

- repository setup documentation exists
- Ubuntu setup script exists
- verification script exists
- Git workflow is documented
- secrets are protected
- Cursor project rules exist
- team members can clone the repository and follow the same setup process

M0 does **not** mean the SDN project itself is implemented.

## 13. Next Milestone

After this environment has been manually verified on the real Ubuntu server, the next milestone is:

**M1 — Main Mininet topology.**

That milestone will implement the agreed 6-switch, 8-host, dual-core, Layer-2 topology. M1 is not part of this bootstrap task.

## Team Journal

Preserved from the original repository README.

### Week 3

- Aryan: minor research about the project, setup the github repo.
- Stephen
- Molly
- Armin
