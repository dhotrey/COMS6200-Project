# LLM-Based Network Troubleshooting Agent

COMS6200 university project.

This project evaluates whether a tool-using LLM can diagnose and localise controlled faults in an OpenFlow-based Mininet environment, and how that compares with a deterministic scripted troubleshooting baseline.

## Documentation

- **[User Manual](docs/user-guide.md)** — setup, testbed operation, the three topologies, fault injection, the agent, the scripted baseline, the completed benchmark and troubleshooting.
- **[Part A report](docs/reports/part-a/)** — September 2026 progress report. It is a historical snapshot and does not describe the finished agent or the 525-trial evaluation.
- **[Completed benchmark](evidence/experiments/sweep/sweep-2026-10/summary.md)** — 525 final trials and 527 attempt rows. Early pilots in [docs/results/](docs/results/llm-diagnosis.md) are not that dataset.

## Chat harness

From the repository root, run `uv sync --project agent`, then
`uv run --project agent python -m agent`. Open http://127.0.0.1:8000.
Configure the root `.env` using `.env.example`; store the OpenAI key in Cloudflare
BYOK. [Agent setup](agent/README.md) covers credentials, Logfire, tool timings,
Cloudflare D1 history, and tests. Run
`uv run --project agent python -m agent.setup_d1` before first launch. The telemetry tools are reused, including a bounded one-port `nmap` scan. The UI loads F1–F5;
`./scripts/verify_agent_scenarios.sh` checks each scenario's load → tools →
reset path without model requests. Test results:
[LLM diagnosis test results](docs/results/llm-diagnosis.md). Disable the default
artificial tool delays before measuring actual research performance.

## 1. Project Overview

The research question is:

> How accurately and efficiently can a tool-using LLM agent diagnose and localise common faults in an OpenFlow-controlled Mininet network compared with a deterministic scripted troubleshooting baseline?

The finished study uses three Layer-2 topologies, five fault families, eight diagnostic tools, one OpenAI tool-using agent and one scripted baseline. The completed repeated evaluation is archived under `evidence/experiments/sweep/sweep-2026-10/`.

## 2. Project Status

| Milestone | Description | Status |
| --- | --- | --- |
| M0 | Reproducible Environment Bootstrap | Completed |
| M1 | Enhanced Main Mininet Topology | Completed |
| M2 | ONOS + OpenFlow 1.3 Integration | Completed |
| M3 | Deterministic Loop-Free Forwarding | Completed |
| M4 | Structured Telemetry Gateway | **Completed** |
| M5 | First Automated Fault + Reset | **Completed** (F1) |
| M5B | Complete Fault Catalogue v1 | **Completed** (F1–F5 frozen) |
| M6 | LLM tool-calling diagnosis, scripted baseline and repeated evaluation | **Completed.** The archived dataset is the 525-trial sweep below, not the earlier protocol-v1 80-trial design. |

Completed implementation:

- verified base Mininet / Open vSwitch environment on the team Ubuntu server
- implemented enhanced six-switch / eight-host Layer-2 topology
- ONOS 2.7.0 installed as a version-pinned Docker container
- OpenFlow 1.3 controller integration against the enhanced topology
- deterministic loop-free baseline forwarding (`pingall` 0% dropped, 56/56)
- structured telemetry gateway (`scripts/verify_telemetry.sh` ALL CHECKS PASSED, 27 August 2026)
- Fault Catalogue v1 frozen: F1–F5 inject/reset verified (`scripts/verify_fault_catalogue.sh` ALL FIVE PASSED, 27 August 2026)

Completed evaluation:

- `evidence/experiments/sweep/sweep-2026-10/` (seed 6202): 3 topologies × 5 faults × 7 methods × 5 rounds = **525 final trials**. `trials.jsonl` has **527 attempt rows**. Two Ring round-3 GPT-6 Astra first attempts (F3 read timeout, F4 read error) completed on attempt 2. No final trial was excluded.
- Methods: scripted baseline, `gpt-5.6-luna`, `gpt-5.6-terra`, `gpt-5.6-sol`, `gpt-6-astra` (reasoning effort `medium`), and `gpt-4.1-mini` / `gpt-4.1-nano` (no reasoning effort).
- Diagnosis uses the OpenAI Responses API through Cloudflare AI Gateway. Semantic grading uses the OpenAI Decisions API (`gpt-6-luna`) through the same gateway. Stored verdicts were not regraded.
- Gateway response caching was bypassed (`cf-aig-skip-cache`). Provider storage was off (`store=false`). Provider prompt caching stayed on, and cached input tokens were recorded. Each trial restarted the network and used a fresh conversation.
- The stored records keep the label `EXPLORATORY SWEEP / NOT PROTOCOL V1`. That label means the sweep is not the earlier main-only 80-trial protocol. It is the completed dataset. Do not rewrite the evidence files.
- Under the semantic-judge metric, reasoning-capable models succeeded on 76–92% of trials, the scripted baseline on 73.3% (55/75), and the two smaller models on 10.7% and 2.7%. Counts, cost and time are in `summary.md`. Collection spanned more than one source state; per-trial metadata was kept.

Historical, and not the completed dataset:

- September pilots in `docs/results/`.
- [Experimental Protocol v1](docs/experiments/protocol-v1.md): an earlier `main6s8h` design whose `formal` command still refuses to start. Its 80-trial matrix was not collected. Dry runs are not the 525-trial dataset.

Not implemented: constrained automatic repair, and an h6 failover experiment.

## 3. Architecture

```
Mininet / Open vSwitch
        ↓
OpenFlow 1.3
        ↓
ONOS 2.7.0
        ↓
Telemetry / Tool Gateway (eight read-only tools)
       ↙                        ↘
OpenAI Responses API          scripted baseline
(Cloudflare AI Gateway)       (baseline/)
       ↘                        ↙
        free-text diagnosis
                ↓
OpenAI Decisions API (gpt-6-luna)  +  protocol-v1 rule cross-check
                ↓
Cloudflare D1 and archived JSON; Logfire is optional
```

Operator/evaluator only (not an LLM tool):

```
Fault injector (F1–F5) → Mininet/OVS / ONOS experiment flows
Fault injector → evaluator ground truth (/run/coms6200/fault-state.json)
```

The LLM does **not** receive unrestricted ONOS REST access, controller credentials, fault labels or injector state. The gateway tools are `get_topology`, `ping`, `nmap`, `get_port_status`, `get_port_stats`, `get_link_metrics`, `get_flow_table`, and `iperf`. Allow-lists follow the selected topology. Gateway iperf uses port 5201. F2 background load uses port 5202 and lasts until reset. Constrained automatic repair is not implemented.

**Chat UI default** (`/api/config`): `gpt-6.1-sol`, reasoning `low`. The completed sweep used the six model identifiers above, not that UI default. The unused protocol-v1 runner still expects `gpt-5.6-sol` / `medium`, 14 calls, 300 seconds, delay 0/0 and `main6s8h`, and its `formal` command remains disarmed.

Topologies: `main6s8h` (6 switches, 8 hosts), `ring5s5h` (5 switches, 5 hosts) and `tree5s8h` (selector name retained; 7 switches, 8 hosts). Part A does not describe this later work.

The selected controller is **ONOS 2.7.0**. The earlier Ryu / OS-Ken plan was replaced after ONOS passed runtime verification; see `docs/decisions/onos-controller-decision.md`.

**Faults** (Fault Catalogue v1 — frozen):

| ID | Fault | Status |
| --- | --- | --- |
| F1 | Link failure (primary s3–s1) | **Completed** |
| F2 | Congestion (s1–s5 TBF + background) | **Completed** |
| F3 | ACL / policy error (selective DROP) | **Completed** |
| F4 | Forwarding loop (bounded unicast cycle) | **Completed** |
| F5 | Missing baseline flow (s3→h5) | **Completed** |

The project may later include **one optional constrained link-failure reroute demonstration**. Automated remediation is not the current priority. Do not add extra mandatory faults.

## 4. Implemented Topology

The main topology is implemented in `topologies/main_topology.py` (`--topo main6s8h`). It is Layer 2, IPv4 `10.0.0.0/24`, OpenFlow 1.3, and `failMode=secure`.

| Class | Count |
| --- | ---: |
| Switches | 6 |
| Hosts | 8 |
| Inter-switch physical links | 10 |
| Host-switch physical links | 9 |
| Total physical links | 19 |

Dual-core layout: s1 (Core A) and s2 (Core B); access switches s3–s6 each attach to both cores. Extra paths increase diagnostic diversity, not node count:

- `s3-s4` is a dedicated **access-edge test link** for controlled forwarding-loop / core-bypass experiments.
- Host **h6** is dual-attached:
  - primary `h6-eth0` → s5 (`10.0.0.6/24`)
  - secondary `h6-eth1` → s6 (no baseline IPv4 address)

No Linux bonding, LACP, MLAG, VRRP, or automatic host failover is implemented.

Baseline forwarding uses s1 as the active core. The following links stay physically present but remain outside normal baseline forwarding:

- s2 redundant access uplinks
- s1–s2 inter-core link
- s3–s4 access-edge test link
- h6–s6 secondary attachment

Details and the exact port map: `topologies/README.md`.

## 5. Verified ONOS Controller

Verified on the team Ubuntu server on 20 August 2026 against the **enhanced 19-link** topology. Evidence: `evidence/progress/onos/main6s8h-enhanced-2026-08-20.txt`. Setup procedure: `docs/setup/onos-setup.md`.

| Item | Observed |
| --- | --- |
| Controller | ONOS 2.7.0 (`onosproject/onos:2.7.0` Docker image) |
| OpenFlow | 1.3 on all six OVS switches |
| Fail mode | secure |
| Devices | 6/6 (`of:0000000000000001` … `of:0000000000000006`) |
| Directed ONOS links | 20 (= 10 physical switch–switch links, including s3:5 ↔ s4:5) |
| REST | HTTP 200 for `/devices`, `/links`, `/hosts`, `/flows`, `/topology` |
| Reactive forwarding | `org.onosproject.fwd` installed, **not** active |
| OVS NORMAL | not used |
| STP | not enabled |
| Baseline forwarding | `org.coms6200.baseline`, 56 ADDED flows (unicast prio 41000, ARP-tree prio 42000) |
| `pingall` | 0% dropped (56/56 received) on primary h1–h8 |

s2, s1–s2, s3–s4 and h6–s6 remain discovered but unused by baseline forwarding. Evidence: `evidence/progress/forwarding/deterministic-baseline-2026-08-20.txt`.

Do not enable `org.onosproject.fwd`, NORMAL, STP or FLOOD. Reinstall baseline after `mn -c` with `python3 forwarding/baseline_forwarding.py install`.

## 6. Verified Base Environment

The following **base Mininet / Open vSwitch environment** (M0) was verified on the team Ubuntu server by running `./setup/verify_environment.sh`. That check is independent of ONOS.

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

That ovsbr `pingall` result is a **simple two-host bridge test**. It is not evidence that the six-switch project topology forwards packets.

### Compatibility policy

The project is intended to run on Linux.

- **Verified reference environment:** Ubuntu 24.04.4 LTS (M0–M3 evidence).
- **Supported course compatibility target:** the UQ-provided Kali VM. The apt-based `setup/setup_ubuntu.sh` continues on Kali; do not treat Kali as fully milestone-verified until evidence is recorded.

Passing `./setup/verify_environment.sh` means the environment has passed the current M0 Mininet / Open vSwitch **capability** checks. It does **not** mean ONOS is installed, and it does **not** mean every Linux distribution is officially supported.


## 7. Quick Start

These commands assume you have permission to access the team repository. Run setup and Mininet on Linux, not on macOS or Windows.

```bash
git clone https://github.com/dhotrey/COMS6200-Project.git
cd COMS6200-Project
chmod +x setup/*.sh scripts/*.sh
./setup/setup_ubuntu.sh
./setup/verify_environment.sh
```

Stay on `master`. That branch is the submission snapshot. Mininet and ONOS run on Linux, not on macOS or Windows.

ONOS is a **separate** step. Do not expect `setup_ubuntu.sh` to install it:

```bash
./setup/setup_onos.sh
./scripts/verify_onos.sh
```

Wait until ONOS is listening on `127.0.0.1:6653` (typically 60–90 seconds on the small team server). Then either use the session helper (background Mininet, no `mininet>` prompt):

```bash
./scripts/testbed.sh start
./scripts/testbed.sh inject F1    # F1–F5; also accepted: f1 or 1
./scripts/testbed.sh stop         # Mininet down; ONOS stays up
```

`stop` is the normal experiment reset. It clears an active F1–F5 fault and
Mininet, and leaves the ONOS container running. Stop ONOS itself with
`./scripts/testbed.sh stop --with-onos`. If REST is up but the six switches
never attach, `start` recreates only the `onos` container once and retries.

Or launch the main topology interactively:

```bash
sudo mn -c
sudo mn --custom topologies/main_topology.py \
  --topo main6s8h \
  --controller=remote,ip=127.0.0.1,port=6653 \
  --switch=ovsk
```

While Mininet is running, from another shell:

```bash
export ONOS_USER=onos
export ONOS_PASSWORD=rocks
python3 forwarding/baseline_forwarding.py install
python3 forwarding/baseline_forwarding.py verify
sudo ./scripts/verify_main_openflow.sh
./scripts/verify_onos.sh
./scripts/verify_telemetry.sh
```

`setup_onos.sh` uses `docker` without sudo when `docker info` works. Mininet still typically needs `sudo mn`. `verify_telemetry.sh` re-executes with sudo only if OVS is not usable as the current user.

Do not use `--controller=none`, `--switch ovsbr`, NORMAL, STP, or `org.onosproject.fwd`. Full procedure: `docs/setup/onos-setup.md`, `topologies/README.md` and `forwarding/README.md`.

## 8. Setup Scripts

ONOS installation is **not** merged into `setup_ubuntu.sh`. Keep the two environments separate.

| Script | Role |
| --- | --- |
| `setup/setup_ubuntu.sh` | Base Mininet / OVS environment (M0) |
| `setup/setup_onos.sh` | ONOS 2.7.0 controller environment (M2) |
| `setup/verify_environment.sh` | Base Mininet / OVS capability verification |
| `scripts/testbed.sh` | Session start/stop plus F1–F5 inject/reset (operator helper; not an LLM tool) |
| `scripts/verify_onos.sh` | ONOS health and REST/OpenFlow verification |
| `scripts/verify_main_openflow.sh` | Running topology / OVS OpenFlow verification |
| `scripts/verify_telemetry.sh` | Live M4 telemetry tools vs healthy baseline |
| `scripts/verify_fault_f1.sh` … `verify_fault_f5.sh` | Live per-scenario fault inject/observe/reset |
| `scripts/verify_fault_catalogue.sh` | Sequential F1–F5 catalogue verifier |
| `scripts/verify_faults.py` | Data-driven F1–F5 verifier for the selected topology |
| `scripts/list_models.py` | Lists the model IDs the Cloudflare AI Gateway key can reach |
| `scripts/verify_agent_scenarios.sh` | F1–F5 through the chat harness path (UI load → agent tools → UI reset); no model requests |
| `forwarding/baseline_forwarding.py` | Deterministic baseline flow install/status/verify/remove |
| `faults/` | Operator fault injector/reset for all three catalogues (not an LLM tool) |

A future `--with-onos` convenience flag on the Ubuntu setup script could be added later. It is **not** implemented now. Do not duplicate `setup_onos.sh` logic here; see `docs/setup/onos-setup.md`.

`setup_ubuntu.sh` updates apt, installs Git, Mininet, Open vSwitch, iperf3, Python 3, pip, venv, jq, and curl, attempts to enable/start Open vSwitch when the Ubuntu-style service unit exists, and creates a `.venv` if it does not already exist. It does **not** install ONOS, the OpenAI SDK, or other LLM libraries.

The script cannot activate `.venv` in your current shell. After it finishes, run:

```bash
source .venv/bin/activate
```

## 9. Environment Verification

```bash
./setup/verify_environment.sh
```

Verification is **capability-based**, not Ubuntu-name-based. It reports PASS / FAIL / WARNING for required project capabilities: Linux, Python 3, Git, Mininet, Open vSwitch tools, iperf3, Open vSwitch runtime, and a basic Mininet connectivity test (`mn --switch ovsbr --test pingall`, using `sudo` only when the caller is not root).

A passing result means only that the current M0 Mininet / Open vSwitch checks succeeded. Verify ONOS separately with `./scripts/verify_onos.sh`.

**Observed M0 result on the team Ubuntu server:**

- Basic Mininet/OVS test: `mn --switch ovsbr --test pingall`
- Result: 0% dropped, 2/2 received
- Summary: PASS: 10, FAIL: 0, WARNING: 0

## 10. macOS / Windows Development

Cursor, Git, documentation, and Python code editing may be done from macOS or Windows.

Mininet, Open vSwitch, and ONOS experiments must be executed in a Linux environment such as:

- Ubuntu server (verified reference: Ubuntu 24.04.4 LTS)
- Ubuntu VM
- UQ-provided Kali VM (supported course compatibility target)
- another Linux workstation/server that passes the same capability checks

Do not redesign the project to run Mininet natively on macOS. Do not treat every Linux distribution as officially supported.

## 11. Git Workflow

| Branch | Purpose |
| --- | --- |
| `master` | Submission snapshot. Implementation is complete. |
| `develop` | Earlier integration branch |
| `feature/*` | Historical individual tasks |

New feature work is not planned. Do not commit `.env`, credentials, `incoming/`, or generated report drafts.

The earlier development workflow was:

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

Feature branches were reviewed before integration. Git operations remain human-controlled.

## 12. Secrets and OpenAI API

The OpenAI provider key is stored in Cloudflare BYOK. Local gateway credentials are loaded from the root `.env` or environment variables.

- Copy `.env.example` to `.env` for the chat harness.
- Configure `CLOUDFLARE_API_TOKEN` with D1 Write access and set
  `CLOUDFLARE_D1_DATABASE_ID`; this account token is not the AI Gateway token.
- Never commit `.env` or real API keys.
- Do not put secrets in `README.md`, scripts, or source files.

ONOS REST/CLI credentials are likewise environment-only (`ONOS_USER` / `ONOS_PASSWORD`). They are not stored in this repository.

## 13. Current Repository Structure

```
COMS6200-Project/
│
├── README.md
├── CONTRIBUTING.md
├── .gitignore
├── .env.example
│
├── .cursor/
│   └── rules/
│       └── coms6200-project.mdc
│
├── setup/
│   ├── setup_ubuntu.sh
│   ├── setup_onos.sh
│   └── verify_environment.sh
│
├── scripts/
│   ├── verify_onos.sh
│   ├── verify_main_openflow.sh
│   ├── verify_telemetry.sh
│   ├── verify_fault_f1.sh … verify_fault_f5.sh
│   ├── verify_fault_catalogue.sh
│   ├── verify_faults.py             # data-driven verifier for the selected catalogue
│   ├── list_models.py               # model IDs reachable through the gateway
│   └── verify_agent_scenarios.sh    # F1–F5 through the chat harness path
│
├── topologies/
│   ├── main_topology.py            # main6s8h
│   ├── ring_topology.py            # ring5s5h
│   ├── tree_topology.py            # selector tree5s8h: 7 switches, 8 hosts
│   ├── spec.py, ring_spec.py, tree_spec.py
│   └── active.py                   # COMS6200_TOPOLOGY selection (default main6s8h)
│
├── forwarding/
│   └── baseline_forwarding.py      # ONOS REST baseline provisioner
│
├── telemetry/                      # eight bounded diagnostic tools
│
├── faults/                         # operator F1–F5 injector/reset (not an LLM tool)
│
├── controllers/
│   └── main_controller.py          # superseded design reference; not used
│
├── tests/                          # repository tests (no network, no API spend)
│
├── evidence/
│   ├── progress/                   # milestone evidence
│   └── experiments/sweep/sweep-2026-10/  # completed 525-trial dataset
│
├── docs/
│   ├── user-guide.md
│   ├── setup/
│   ├── decisions/
│   ├── experiments/protocol-v1.md  # earlier design; formal runner disarmed
│   ├── reports/part-a/             # historical Part A report
│   └── results/                    # September pilots, not the 525-trial dataset
│
├── agent/                          # chat harness, operator UI, Decisions grading
├── baseline/                       # scripted troubleshooting baseline
├── experiments/                    # protocol-v1 runner and the completed sweep
└── judge/                          # evaluator-only rubrics (not model tools)
```

`controllers/main_controller.py` is retained as a forwarding-design reference only. It is not the runtime controller.

## 14. Current state

Implementation is complete on `master`. The operator manual is `docs/user-guide.md`.

Diagnosis uses the OpenAI Responses API through Cloudflare AI Gateway. Automatic grading uses the OpenAI Decisions API (`gpt-6-luna`) through the same gateway. No separate judge key is required. See [agent setup](agent/README.md#credentials).

The completed dataset is `evidence/experiments/sweep/sweep-2026-10/`. Do not rerun or rewrite it. The protocol-v1 `formal` command still exits without collecting trials.

## 15. Tests

Offline tests do not call Cloudflare, spend API credits, or change a network:

```bash
source .venv/bin/activate
python3 -m pytest tests
uv run --project agent python -m pytest agent/tests
```

## 16. Project reports

The Part A progress report, its Word/PDF outputs and build instructions are under `docs/reports/part-a/`. Edit `docs/reports/part-a/part-a-source.md` only when changing that historical report, then regenerate it. Later milestones are not back-ported into Part A.

## Team Journal

Preserved from the original repository README.

### Week 3

- Aryan: minor research about the project, setup the github repo.
- Stephen
- Molly
- Amir

### M0 environment verification

- Amir Latifi: completed the M0 reproducible environment bootstrap and real-server verification. Ubuntu 24.04.4 LTS; Mininet and Open vSwitch installed via the repository setup/verification scripts; basic Mininet connectivity test (`mn --switch ovsbr --test pingall`) succeeded with 0% dropped (2/2 received); verification summary 10 PASS / 0 FAIL / 0 WARNING.

### Amir Latifi — Part A report reproducibility and validation

Imported the Part A report into the repository as a canonical Markdown source, preserved the original report figures, and established reproducible DOCX/PDF generation and automated report validation. Citations now use stable BibTeX-style keys in `part-a-source.md` with `references.bib` as the bibliographic source of truth; IEEE numbers are generated automatically from first appearance. The builder programmatically validates citation keys, sequential numbering, unused-library warnings, and clickable citation-to-bibliography links in both PDF and DOCX. Dedicated title-page layout/validation and generated DOCX/PDF checks remain in place. Numeric citation rewriting is obsolete.

### M2 ONOS setup and verification

The team installed ONOS 2.7.0 from the official `onosproject/onos:2.7.0` Docker image and verified OpenFlow 1.3 controller integration on the Ubuntu server. All six OVS switches connected with secure fail mode; ONOS discovered the six deterministic DPIDs. Reactive forwarding remained inactive. Host `pingall` on the project topology was not tested.

### M1 enhanced topology verification

The main topology was enhanced with an s3–s4 access-edge test link and an optional h6–s6 secondary attachment (19 physical links). Runtime verification against ONOS on 20 August 2026 reported 6/6 devices and 20 directed inter-switch links, including s3:5 ↔ s4:5. Evidence: `evidence/progress/onos/main6s8h-enhanced-2026-08-20.txt`.

### M3 deterministic baseline forwarding

The team installed explicit ONOS flow rules owned by `org.coms6200.baseline` (numeric id 176) for dest-MAC unicast and loop-free ARP on the s1 active tree. 56 flows reached ADDED; s2 had none. Mininet `pingall` recorded 0% dropped (56/56 received). `org.onosproject.fwd` stayed inactive. Remove/reinstall restored the same connectivity. Evidence: `evidence/progress/forwarding/deterministic-baseline-2026-08-20.txt`.
