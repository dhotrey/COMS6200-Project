# ONOS Setup

Reproducible setup for the ONOS SDN controller used by the COMS6200
LLM-Based Network Troubleshooting Agent project.

ONOS runs in an isolated Docker container. The host's Mininet, Open vSwitch
and Python installations are not modified.

## Tested environment

| Component | Value |
| --- | --- |
| Server OS | Ubuntu 24.04.4 LTS (Noble Numbat), kernel 6.8.0-137-generic, x86_64 |
| ONOS version | 2.7.0 (LTS) |
| ONOS artifact | Docker image `onosproject/onos:2.7.0`, digest `sha256:bc844aaafd64e6b3834c7043bad83fa1eecc6afb6984e9b4887c12e1a307a7c2` |
| Java (inside container) | OpenJDK 11.0.8 LTS, Zulu11.41+23-CA, `JAVA_HOME=/usr/lib/jvm/zulu11-ca-amd64` |
| Java on host | not installed, and not required |
| Docker | 29.1.3 (already present on the server) |
| Mininet | 2.3.0 |
| Open vSwitch | 3.3.9 (`ovs-ofctl` reports OpenFlow versions `0x1:0x6`) |
| Python (host) | 3.12.3 |
| Date tested | 20 August 2026 |

Host resources during testing: 1 vCPU, 955 MiB RAM, 2.3 GiB swap, 23 GB disk.
The small memory budget is why the JVM heap and container memory are capped
below.

## Installation method

ONOS is deployed from the official pre-built Docker image. No source build and
no host JDK are required.

```bash
docker pull onosproject/onos:2.7.0
```

```bash
docker run -d \
  --name onos \
  --memory=640m \
  --memory-swap=1280m \
  -p 127.0.0.1:6653:6653 \
  -p 127.0.0.1:8181:8181 \
  -p 127.0.0.1:8101:8101 \
  -e ONOS_APPS="drivers,openflow,gui2" \
  -e JAVA_OPTS="-Xms64m -Xmx256m -XX:+UseSerialGC" \
  -e JAVA_TOOL_OPTIONS="-Xms64m -Xmx256m -XX:+UseSerialGC" \
  onosproject/onos:2.7.0
```

The repository provides `setup/setup_onos.sh`, which performs the same steps
idempotently. The script tries `docker info` without sudo first. If that
succeeds, every Docker action uses `docker` as the current user. `sudo docker`
is a fallback only when direct daemon access fails. The script does not add
users to the `docker` group or change socket permissions.

Mininet is separate and typically still needs root (`sudo mn ...`).

All published ports are bound to `127.0.0.1` only. ONOS is not reachable from
the public internet, and no firewall rules were changed.

## Why this method was chosen

- **Pre-built and version-pinned.** ONOS 2.7.0 is the final 2.x LTS release and
  the last release with an official pre-built distribution. The image tag and
  digest are recorded above, so every team member gets identical bits.
- **No host JDK.** ONOS 2.7.0 needs Java 11. The host runs Ubuntu 24.04 with
  Python 3.12 and no Java. The container ships its own Zulu OpenJDK 11, so we
  avoid installing and pinning a second JDK on the host.
- **Isolated.** The container cannot alter the working Mininet/OVS/Python
  environment. Removing the container fully reverses the installation.
- **Docker was already installed** (29.1.3), so no new container stack had to be
  introduced.
- **Source build was rejected.** Building ONOS requires Bazel/Bazelisk, a large
  toolchain and several GB of build output. On a 1 vCPU / 955 MiB host that is
  slow, fragile and not reproducible for four team members.

The `tar.gz` distribution under `/opt/onos` remains a viable fallback, but it
would require installing a Java 11 JDK on the host.

## Starting ONOS

First run, or after the container has been removed:

```bash
./setup/setup_onos.sh
```

If the container already exists:

```bash
docker start onos
```

ONOS takes roughly 60–90 seconds on this host before the OpenFlow listener is
ready. Wait for the REST API to answer before starting Mininet.

## Stopping ONOS

The normal experiment cycle does not stop ONOS:

```bash
./scripts/testbed.sh stop
```

Stop the container when that is the intended operator action:

```bash
./scripts/testbed.sh stop --with-onos
```

Low-level equivalent:

```bash
docker stop onos
```

Remove the container entirely (image is kept):

```bash
docker stop onos && docker rm onos
```

The container has `RestartPolicy=no`, so it does not come back automatically
after a reboot. `./scripts/testbed.sh start` starts a stopped container, and
recreates only the `onos` container once if REST is up but the six switches
do not attach. `docker logs` checks in setup are limited to recent output
(`--tail` / `--since`), not the full container history.

## Verifying ONOS

```bash
./scripts/verify_onos.sh
```

Manual equivalents:

```bash
docker ps --filter name=onos
ss -lntp | grep -E ':6653|:8181|:8101'
docker logs onos 2>&1 | grep 'Listening for OF switch connections'
```

Observed listening sockets:

```
LISTEN 127.0.0.1:6653   docker-proxy    # OpenFlow
LISTEN 127.0.0.1:8181   docker-proxy    # REST API + GUI
LISTEN 127.0.0.1:8101   docker-proxy    # Karaf CLI (SSH)
```

ONOS also logs an OpenFlow listener on 6633 inside the container. That port is
deliberately not published; the project uses 6653 only.

## Required ONOS applications

Started through `ONOS_APPS=drivers,openflow,gui2`. Observed active applications
(`apps -a -s`):

```
org.onosproject.drivers         2.7.0    Default Drivers
org.onosproject.optical-model   2.7.0    Optical Network Model
org.onosproject.hostprovider    2.7.0    Host Location Provider
org.onosproject.lldpprovider    2.7.0    LLDP Link Provider
org.onosproject.openflow-base   2.7.0    OpenFlow Base Provider
org.onosproject.openflow        2.7.0    OpenFlow Provider Suite
org.onosproject.gui2            2.7.0    ONOS GUI2
```

`org.onosproject.openflow` is a meta-application that pulls in
`openflow-base`, `hostprovider` and `lldpprovider`. `optical-model` is a
dependency of `drivers`.

**Reactive forwarding (`org.onosproject.fwd`) is installed but deliberately NOT
activated.** The project topology has redundant physical links and therefore
physical cycles. Deterministic forwarding is a separate milestone and must be
designed rather than obtained from a reactive learning application.

## Mininet connection

### Simple sanity test (h1 -- s1 -- h2)

```bash
sudo mn -c
sudo mn --topo single,2 \
  --controller=remote,ip=127.0.0.1,port=6653 \
  --switch ovsk,protocols=OpenFlow13
```

### Main project topology (6 switches, 8 hosts)

```bash
sudo mn -c
sudo mn --custom topologies/main_topology.py \
  --topo main6s8h \
  --controller=remote,ip=127.0.0.1,port=6653 \
  --switch=ovsk
```

`topologies/main_topology.py` already requests `protocols='OpenFlow13'` and
`failMode='secure'` per switch, so no extra switch options are needed.

Do not use `--controller=none` or `--switch ovsbr` with this topology. Standalone
bridge mode would flood across the redundant links.

Cleanup after exiting Mininet:

```bash
sudo mn -c
```

## OpenFlow 1.3 verification

```bash
sudo ovs-vsctl get bridge s1 protocols
sudo ovs-vsctl get-fail-mode s1
sudo ovs-vsctl get-controller s1
sudo ovs-vsctl --columns=target,is_connected,role,status list controller
sudo ovs-ofctl -O OpenFlow13 show s1 | head -1
sudo ovs-ofctl -O OpenFlow13 dump-flows s1
```

Observed for every switch s1–s6 while `main6s8h` was running:

```
protocols   : [OpenFlow13]
fail-mode   : secure
controller  : ptcp:665x tcp:127.0.0.1:6653
is_connected: true      role: master      state=ACTIVE
of13 features: OFPT_FEATURES_REPLY (OF1.3) (xid=0x2): dpid:000000000000000N
```

Controller-side confirmation, from the ONOS device annotations:

```
protocol=OF_13
```

Together these are runtime proof of OpenFlow 1.3, independent of the Python
topology source.

## ONOS CLI verification

The Karaf CLI is exposed on port 8101 over SSH. From the server:

```bash
ssh -p 8101 karaf@127.0.0.1
```

This prompts for the ONOS Karaf password. The upstream ONOS default applies;
credentials are not stored in this repository. Change them before any
non-localhost exposure.

The official `onos` client script inside the container (`/root/onos/bin/onos`)
requires an SSH client, which the 2.7.0 image does not ship. During testing an
SSH client was installed **inside the container only** to run the CLI
non-interactively. That change is not persistent and is not required: the REST
API provides the same information and is the project's canonical interface.

Useful CLI commands:

```
summary
nodes
apps -a -s
devices
links
hosts
flows -s
```

## REST verification

The REST API is served on `http://127.0.0.1:8181/onos/v1`. It requires HTTP
basic authentication. Supply credentials through environment variables so they
never enter Git:

```bash
export ONOS_USER=onos
export ONOS_PASSWORD='<your ONOS REST password>'

curl -sS -u "$ONOS_USER:$ONOS_PASSWORD" http://127.0.0.1:8181/onos/v1/devices
curl -sS -u "$ONOS_USER:$ONOS_PASSWORD" http://127.0.0.1:8181/onos/v1/links
curl -sS -u "$ONOS_USER:$ONOS_PASSWORD" http://127.0.0.1:8181/onos/v1/hosts
curl -sS -u "$ONOS_USER:$ONOS_PASSWORD" http://127.0.0.1:8181/onos/v1/flows
curl -sS -u "$ONOS_USER:$ONOS_PASSWORD" http://127.0.0.1:8181/onos/v1/topology
```

Observed results with `main6s8h` running (all HTTP 200):

```
/topology   {"devices":6,"links":18,"clusters":1}
/devices    6 devices, of:0000000000000001 .. of:0000000000000006, protocol=OF_13
/links      18 directed links = 9 physical switch-switch links
/hosts      0 hosts
/flows      18 flows (3 per device: lldp, bddp, arp punt-to-controller)
```

`/onos/v1/topology/overview` returns HTTP 404 in 2.7.0; use `/onos/v1/topology`.

This confirms the intended data path for later work:

```
Python tool layer -> REST -> ONOS -> OpenFlow 1.3 -> Mininet / OVS
```

## GUI

The GUI2 application is active. `http://127.0.0.1:8181/onos/ui` returned HTTP
302 (redirect to the login page), which confirms the GUI is being served.

Port 8181 is bound to localhost only and was not exposed publicly. To view the
GUI from a workstation, use an SSH tunnel rather than a firewall change:

```bash
ssh -L 8181:127.0.0.1:8181 <user>@<server>
```

Then open `http://127.0.0.1:8181/onos/ui` locally. This was not exercised during
testing.

## Host connectivity status

Host-to-host connectivity (`pingall`) was **not** tested on `main6s8h`, by
design. No forwarding application is active, so no host-reachability flows
exist. The switches only have the ONOS LLDP/BDDP/ARP punt rules.

This is not a controller-integration failure. Deterministic loop-free forwarding
across the redundant topology is the next milestone.

Consequently ONOS reports `hosts=0`: host discovery is packet-driven, and no
host traffic was forwarded.

## Link-count semantics

ONOS models links as **directed**. The physical topology has 9 switch-to-switch
links, which ONOS reports as 18 directed links. Mininet's 17 links count 9
switch-switch plus 8 host-switch links. ONOS does not report host-facing links
as topology links; hosts appear separately under `/hosts` once discovered.

Do not compare the ONOS directed-link count with the Mininet link count
directly.

## Troubleshooting

Only issues actually encountered on this server are recorded.

### ONOS Karaf CLI script fails inside the container

```
/root/onos/bin/onos: line 6: ssh: command not found
```

The `onosproject/onos:2.7.0` image has no SSH client, so the bundled `onos`
client script cannot connect to Karaf on port 8101. Use the REST API, or
`ssh -p 8101 karaf@127.0.0.1` from the host, or install an SSH client inside the
container for interactive CLI use.

### `/onos/v1/topology/overview` returns 404

That path does not exist in ONOS 2.7.0. Use `/onos/v1/topology`.

### Transient `ERROR [Tools] Device not found` in the ONOS log

Twelve of these appeared, each within milliseconds of a switch connecting or of
a REST/CLI query for a device that was still registering or had just
disconnected after `mn -c`. They did not prevent device discovery, link
discovery or flow installation, and the affected devices subsequently reported
`available=true`.

### Memory pressure

The host has 955 MiB RAM. Without JVM limits ONOS plus a 6-switch, 8-host
Mininet network can exhaust memory. The documented `--memory=640m` and
`-Xmx256m` settings kept the run stable; peak observed usage was about 890 MiB
of RAM with roughly 1.1 GiB of swap in use. If a team member's host has more
memory, these caps can be relaxed.
