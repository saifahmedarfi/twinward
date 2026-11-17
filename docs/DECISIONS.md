# Design decisions (running log)

Add a dated line for every design choice. Started 2026-11-07.

- 2026-11-07  Ground truth is kept OUT of the monitored log stream. Events carry
  only `event_id`; labels live in the controller ground-truth table, joined by
  `event_id` in the evaluator. (Prevents detection cheating.)
- 2026-11-07  `event_id` is derived deterministically from
  (experiment_id, component, sequence) so a run is reproducible for a fixed seed.
- 2026-11-07  Absence detection (SC-05, SC-07): use Option (b) — the evaluation
  engine computes expected-vs-observed coverage. Simpler and fully testable.
- 2026-11-07  Primary evaluation mode is fast mode (log-only evaluator);
  Wazuh-in-the-loop only for a validation subset.
- 2026-11-07  Simulation cores are stdlib-only and separate from their FastAPI
  wrappers, so the simulation runs and is tested without a server or cluster.
- 2026-11-08  SC-02..SC-07 built (Phase 3 complete) plus the Phase 5 evaluation
  engine (log-only / fast-mode path). Design notes below.
- 2026-11-08  The log-only detector reads ONLY telemetry fields (`event_type`,
  `simulated_state`, `severity`, `details`) and never the ground-truth table;
  alerts are matched to ground truth afterwards by `event_id`/time. `simulated_state`
  is a device's self-report (like a real log severity), not a detection label, so
  using it in the detector does not breach the "ground truth out of the stream"
  invariant. A test asserts no emitted event carries a label field.
- 2026-11-08  A false positive is an alert on a BENIGN (normal-state) event. An
  alert on an anomalous/violation event outside the labelled family is a redundant
  detection of the same incident, counted as neither TP nor FP.
- 2026-11-08  `alert_threshold` is applied at DETECTION time (evaluator), not at
  emission. Components emit the raw drop-rate; the detector decides alerts via a
  cutoff derived from `alert_threshold`. This lets policy sweeps re-score a single
  run without re-simulating, and keeps D/F non-degenerate across policies.
- 2026-11-08  Containment is emitted by the component as a `details.contained`
  boolean computed from its own access profile (the device enforcing its policy);
  `standard` does not contain, `strict`/`lockdown` does. The evaluator only
  aggregates it. This gives the reward component C a real policy lever.
- 2026-11-08  Availability uses `probe_result` events from a controller-side
  prober (only when a scenario declares a `probes` section, so SC-01 stays
  byte-identical). An unavailable component answers `ok:false` — it never crashes,
  preserving the "pods never die" invariant.
- 2026-11-08  Recovery Q measures a bounded buffer-drain: when the forwarder
  leaves a degraded state it stays `fault` for `buffer_drain_ticks` before healthy
  telemetry resumes, so `t_rec > 0` and Q responds to the `recovery_timeout` budget.
- 2026-11-08  SC-05 (absence) is modelled on the eng-station: in normal mode it
  emits a periodic `security_audit_log`; the `audit_log_gap` mode keeps the host
  alive and compliant but omits that one required audit event (Option b coverage).
