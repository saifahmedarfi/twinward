# Signal catalog

Every monitored signal is an `event_type` family emitted by exactly one owning
component. This is the master mapping used by the simulator, the Wazuh rules
(Phase 4) and the evaluator (Phase 5).

| Component | Zone | Signals (`event_type` families) |
|---|---|---|
| `idmz-gateway` | idmz | inter-zone protocol anomalies; IDMZ jump-host lateral crossings; unauthenticated access attempts; electronic access-control badging; request allow/deny; access / segmentation / remote-access violations |
| `boundary-firewall` | idmz | boundary-protection drop rates; non-whitelisted protocol violations; MAC spoofing & port-profile changes; broadcast/multicast packet-storm volumes; rate-limit actions |
| `plc-edge` | field | PLC firmware integrity checksums; SIS mode status; WDT heartbeats; invalid I/O-boundary command violations; unused PLC port activation; device reboot & uptime |
| `eng-station` | supervisory | config drift; privileged command execution; TCA compliance; transient-media malicious-payload signatures; SBOM vuln matches; HSM revocation status |
| `telemetry-forwarder` | control | data-diode forwarding health; buffer & log-storage capacities; memory-utilization anomalies; network latency & jitter; power-signature profiling; chassis-intrusion microswitch; UPS autonomy & health; gold-master backup integrity; PTP/NTP time-sync drift |

Two cross-cutting signals support the evaluation engine (Phase 5):

| Signal | Owner | Purpose |
|---|---|---|
| `security_audit_log` | `eng-station` | required periodic audit record in normal mode; its omission (`audit_log_gap`) is the positive in SC-05 (absence detection) |
| `probe_result` | emitted for a probe target (`idmz-gateway`, `telemetry-forwarder`) | result of a legitimate availability probe (`ok`, `latency_ms`, `sla_ms`); feeds availability `A` and recovery `Q`. A failed probe means `ok:false`, never a crash |

Status in this scaffold: all five components emit their baseline plus the
injected signals for the seven core scenarios (SC-01..SC-07). The optional
extended catalog (SC-08+) is future work. The signal→scenario→reward mapping is
in [metrics.md](metrics.md).
