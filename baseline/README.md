# Scripted troubleshooting baseline

Deterministic diagnostic comparator. It is not the ONOS
forwarding application `org.coms6200.baseline`.

The baseline was one method in the completed 525-trial sweep. On `ring5s5h` it
looks for F1 and F2 on the shortest configured path, which healthy ring
forwarding does not use, so those two ring faults sit outside the path it
checks. That limitation was left unchanged.

The baseline receives the symptom sentence and calls `TelemetryGateway`. It
does not receive a scenario id, fault state, injector configuration, or raw
qdisc settings. It stops at 14 gateway calls or 300 seconds and returns
`link_failure`, `congestion`, `policy_drop`, `forwarding_loop`, `missing_flow`,
or null.

```bash
python3 -m baseline --prompt "h1 can no longer reach h5. Diagnose and localise the fault."
```

Run it from the repository root on a healthy testbed. The experiment runner,
not this command, injects faults.
