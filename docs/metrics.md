# Evaluation metrics and reward (Phase 5)

Every metric is implemented as a pure function in
[`research/evaluation/metrics.py`](../research/evaluation/metrics.py) with unit
tests on hand-built TP/FP/FN examples, so correctness does not depend on the
live cluster. The log-only evaluator that wires them to real runs is
[`research/evaluation/engine.py`](../research/evaluation/engine.py).

## How detection stays honest

The evaluator **never reads the ground-truth table to make a detection
decision.** It runs a detector over the raw event stream (using only
`event_type`, `simulated_state`, `severity`, `details`), and *only afterwards*
matches the resulting alerts to ground truth by `event_id` and time window.
This is the ordering that keeps the pipeline honest (see
[DECISIONS.md](DECISIONS.md)); it mirrors how Wazuh rules key on event fields.

Two detection paths:

- **presence** — a threshold alert on drop-rate signals
  (`drop_rate >= cutoff(alert_threshold)`), or a state alert on an
  `anomalous` / `fault` / `violation` event. The threshold is applied in the
  evaluator, so a policy changes what counts as an alert without re-running the
  simulation.
- **absence (coverage)** — a required periodic signal that goes missing for
  longer than `timeout` raises a coverage-gap alert. Used for SC-05 and SC-07
  (DECISIONS: Option b).

`alert_threshold` (policy range 1..5) maps to a drop-rate cutoff in
`[0.05, 0.25]`: a low threshold catches more (and raises more false positives on
near-miss benign readings); a high threshold misses the real anomaly. That is
the lever that makes detection — and the reward — non-degenerate across
policies.

## Metric definitions

Let `G` be ground-truth positive events, `B` benign events, `A` alerts. An alert
*matches* a positive if its `event_id` is in `G` (presence) or its coverage gap
overlaps the absence window (absence). Each positive matches at most once.

| Metric | Definition | Range |
|---|---|---|
| Detection rate `D` | `|TP| / |G|` | [0,1] |
| Precision | `TP / (TP + FP)` | [0,1] |
| False-positive rate | `FP / |B|`, where an FP is an alert on a **benign** (normal-state) event | [0,1] |
| FP penalty `F` | FP rate (severity scaling optional, not enabled in v1) | [0,1] |
| Detection delay | mean `t_alert − t_event` over TP, seconds | ≥0 |
| Delay penalty `L` | `min(1, mean_delay / W)`, `W` = eval-window length; missed positives count as `W` | [0,1] |
| Containment `C` | fraction of malicious/violating attempts denied/throttled before effect (`details.contained`) | [0,1] |
| Availability `A` | fraction of legitimate probes answered within the SLA (`probe_result` events) | [0,1] |
| Recovery `Q` | `1 − min(1, t_rec / T_budget)`; `t_rec` = fault-end → monitoring-normal, `T_budget` = `recovery_timeout` | [0,1] |

**A false positive is an alert on benign traffic.** An alert on an
anomalous/violation event that is not the labelled family (e.g. SC-02 also emits
`boundary_drop_rate` alongside `packet_storm_volume`) is a redundant detection of
the real incident, so it counts as neither TP nor FP.

**Neutral defaults** when a dimension does not apply to a scenario: `D = 1.0`
(no positives), `C = 1.0` (nothing to contain), `A = 1.0` (no probes),
`Q = 1.0` (no fault). These keep the reward sum well-defined and comparable
across scenarios.

## Reward

```
R(π) = w_d·D + w_c·C + w_a·A + w_r·Q − w_f·F − w_l·L
```

Starting weights (in [`configs/evaluation/reward.yaml`](../configs/evaluation/reward.yaml),
to be stress-tested in the Phase 7 sensitivity analysis):
`w_d=0.30, w_c=0.25, w_a=0.20, w_r=0.10, w_f=0.10, w_l=0.05`.

## Which scenario exercises which reward component

| Scenario | Primary | Also exercises |
|---|---|---|
| SC-01 | D (threshold), F | — |
| SC-02 | D, severity match | multi-signal attack (no FP) |
| SC-03 | D, **C** (privilege containment) | — |
| SC-04 | D, **C** (boundary deny) | — |
| SC-05 | D (**absence** / coverage gap), L | — |
| SC-06 | D, **C** (remote deny) | — |
| SC-07 | D (absence), **A** (probes), **Q** (recovery) | L |

Containment is driven by the access profile (`standard` → not contained,
`strict`/`lockdown` → contained); availability and recovery are driven by the
forwarder's degradation and bounded buffer-drain. All three keep the three
invariants intact: pods never die (unavailability is a failed probe, not a
crash), ground truth never enters the stream, and every run is byte-reproducible
for a fixed seed.
