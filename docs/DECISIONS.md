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
- 2026-11-27  Phase 3 completed: scenarios + telemetry. `main.py` is the primary
  entry point (`python main.py phase3` runs everything and writes
  `results/phase3/report.{md,json}`).
- 2026-11-27  `estate-config.yaml` and `reward.yaml` are now read on every run
  (research/common/config.py). Effective policy = estate baseline <- scenario
  `initial_conditions` <- candidate policy; candidate levers are applied through
  each core's `apply_policy()`. Baseline rewards are byte-identical to before.
- 2026-11-27  Reset path (Step 3.4) is real: `TwinController.reset()` executes the
  scenario's `reset_procedure`. A run on a dirty twin auto-resets first (keeping
  any policy set for the next run). Verified per scenario: identical payload after
  reset, *different* payload when the reset is bypassed (control), fresh id.
- 2026-11-27  Scenario schema is a Pydantic v2 model (unknown actions/targets/reset
  steps, inverted windows and windows past the evaluation end are rejected); the
  plain validator remains the stdlib fallback.
- 2026-11-27  Observability split: Prometheus = numbers (service /metrics scraped;
  batch runs pushed to a Pushgateway + textfile), OpenTelemetry = evidence (one
  trace per experiment with configure/simulate/evaluate/persist spans; one OTel
  log record per event, trace-correlated) -> Collector -> JSONL files, ledger =
  authoritative record (PostgreSQL via PROPS_DB_URL, SQLite otherwise). Trace and
  span ids live in the ledger and log files only, never in the event stream the
  detector reads.
- 2026-11-27  Experiment ids are unique per ledger: the run counter is the next
  free counter for (scenario, seed), so repeated runs never overwrite evidence.
- 2026-11-27  SC-04 and SC-06 gained an idmz-gateway availability probe so the
  over-restrictive `lockdown` profile shows its availability cost (A=0). Baseline
  rewards unchanged (probes all pass under `standard`). SC-01 left untouched.
- 2026-11-27  Added proposal Table 3 metrics to each record: blocked vs
  prohibited flow counts, recovery time, retained event records / log retention.
