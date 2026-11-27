# ProPS-Twin — Phase 3 results (scenarios + telemetry)

Generated 2026-11-27T08:08:48+00:00 · code `7adbd37` · ledger `postgresql` · wall time 13.65s

## 1. Baseline suite (policy baseline-v1)

| Scenario | Proposal condition | R | D | C | A | Q | F | L | TP/FP/FN | blocked / prohibited | retained |
|---|---|---|---|---|---|---|---|---|---|---|---|
| SC-01 | Segmentation misconfiguration (non-whitelisted protocol) | 0.8500 | 1.00 | 1.00 | 1.00 | 1.00 | 0.000 | 0.000 | 20/0/0 | 0 / 0 | 968/968 |
| SC-02 | Segmentation / boundary (packet storm) | 0.8500 | 1.00 | 1.00 | 1.00 | 1.00 | 0.000 | 0.000 | 15/0/0 | 15 / 0 | 983/983 |
| SC-03 | Excessive privileges | 0.6000 | 1.00 | 0.00 | 1.00 | 1.00 | 0.000 | 0.000 | 1/0/0 | 0 / 1 | 967/967 |
| SC-04 | Segmentation misconfiguration (jump-host crossing) | 0.6000 | 1.00 | 0.00 | 1.00 | 1.00 | 0.000 | 0.000 | 10/0/0 | 0 / 10 | 980/980 |
| SC-05 | Incomplete logging | 0.8479 | 1.00 | 1.00 | 1.00 | 1.00 | 0.000 | 0.042 | 1/0/0 | 0 / 0 | 938/938 |
| SC-06 | Remote-access policy failure | 0.6000 | 1.00 | 0.00 | 1.00 | 1.00 | 0.000 | 0.000 | 8/0/0 | 0 / 8 | 980/980 |
| SC-07 | Monitoring / service outage | 0.7879 | 1.00 | 1.00 | 0.75 | 0.90 | 0.000 | 0.042 | 1/0/0 | 0 / 0 | 934/934 |

Reproducibility (same seed, repeated runs):

- SC-01: 3 runs, rewards [0.85] → identical
- SC-02: 3 runs, rewards [0.85] → identical
- SC-03: 3 runs, rewards [0.6] → identical
- SC-04: 3 runs, rewards [0.6] → identical
- SC-05: 3 runs, rewards [0.847917] → identical
- SC-06: 3 runs, rewards [0.6] → identical
- SC-07: 3 runs, rewards [0.787917] → identical

## 2. Reset path (Step 3.4)

| Scenario | first → second | all normal | identical after reset | identical without reset (control) | fresh id |
|---|---|---|---|---|---|
| SC-01 | exp-SC-01-1001-0004 → exp-SC-01-1001-0005 | True | True | False | True |
| SC-02 | exp-SC-02-1002-0004 → exp-SC-02-1002-0005 | True | True | False | True |
| SC-03 | exp-SC-03-1003-0004 → exp-SC-03-1003-0005 | True | True | False | True |
| SC-04 | exp-SC-04-1004-0004 → exp-SC-04-1004-0005 | True | True | False | True |
| SC-05 | exp-SC-05-1005-0004 → exp-SC-05-1005-0005 | True | True | False | True |
| SC-06 | exp-SC-06-1006-0004 → exp-SC-06-1006-0005 | True | True | False | True |
| SC-07 | exp-SC-07-1007-0004 → exp-SC-07-1007-0005 | True | True | False | True |

## 3. Policy-lever check (fixed presets, not optimization)

| Scenario | Policy | R | D | C | A | Q | F | FP | prohibited |
|---|---|---|---|---|---|---|---|---|---|
| SC-01 | baseline-v1 | 0.8500 | 1.00 | 1.00 | 1.00 | 1.00 | 0.000 | 0 | 0 |
| SC-01 | strict-v1 | 0.8500 | 1.00 | 1.00 | 1.00 | 1.00 | 0.000 | 0 | 0 |
| SC-01 | lockdown-v1 | 0.8500 | 1.00 | 1.00 | 1.00 | 1.00 | 0.000 | 0 | 0 |
| SC-01 | sensitive-v1 | 0.8475 | 1.00 | 1.00 | 1.00 | 1.00 | 0.025 | 24 | 0 |
| SC-02 | baseline-v1 | 0.8500 | 1.00 | 1.00 | 1.00 | 1.00 | 0.000 | 0 | 0 |
| SC-02 | strict-v1 | 0.8500 | 1.00 | 1.00 | 1.00 | 1.00 | 0.000 | 0 | 0 |
| SC-02 | lockdown-v1 | 0.8500 | 1.00 | 1.00 | 1.00 | 1.00 | 0.000 | 0 | 0 |
| SC-02 | sensitive-v1 | 0.8473 | 1.00 | 1.00 | 1.00 | 1.00 | 0.027 | 26 | 0 |
| SC-03 | baseline-v1 | 0.6000 | 1.00 | 0.00 | 1.00 | 1.00 | 0.000 | 0 | 1 |
| SC-03 | strict-v1 | 0.8500 | 1.00 | 1.00 | 1.00 | 1.00 | 0.000 | 0 | 0 |
| SC-03 | lockdown-v1 | 0.8500 | 1.00 | 1.00 | 1.00 | 1.00 | 0.000 | 0 | 0 |
| SC-03 | sensitive-v1 | 0.5972 | 1.00 | 0.00 | 1.00 | 1.00 | 0.028 | 27 | 1 |
| SC-04 | baseline-v1 | 0.6000 | 1.00 | 0.00 | 1.00 | 1.00 | 0.000 | 0 | 10 |
| SC-04 | strict-v1 | 0.8500 | 1.00 | 1.00 | 1.00 | 1.00 | 0.000 | 0 | 0 |
| SC-04 | lockdown-v1 | 0.6500 | 1.00 | 1.00 | 0.00 | 1.00 | 0.000 | 0 | 0 |
| SC-04 | sensitive-v1 | 0.5974 | 1.00 | 0.00 | 1.00 | 1.00 | 0.026 | 25 | 10 |
| SC-05 | baseline-v1 | 0.8479 | 1.00 | 1.00 | 1.00 | 1.00 | 0.000 | 0 | 0 |
| SC-05 | strict-v1 | 0.8479 | 1.00 | 1.00 | 1.00 | 1.00 | 0.000 | 0 | 0 |
| SC-05 | lockdown-v1 | 0.8479 | 1.00 | 1.00 | 1.00 | 1.00 | 0.000 | 0 | 0 |
| SC-05 | sensitive-v1 | 0.8447 | 1.00 | 1.00 | 1.00 | 1.00 | 0.032 | 27 | 0 |
| SC-06 | baseline-v1 | 0.6000 | 1.00 | 0.00 | 1.00 | 1.00 | 0.000 | 0 | 8 |
| SC-06 | strict-v1 | 0.8500 | 1.00 | 1.00 | 1.00 | 1.00 | 0.000 | 0 | 0 |
| SC-06 | lockdown-v1 | 0.6500 | 1.00 | 1.00 | 0.00 | 1.00 | 0.000 | 0 | 0 |
| SC-06 | sensitive-v1 | 0.5973 | 1.00 | 0.00 | 1.00 | 1.00 | 0.027 | 26 | 8 |
| SC-07 | baseline-v1 | 0.7879 | 1.00 | 1.00 | 0.75 | 0.90 | 0.000 | 0 | 0 |
| SC-07 | strict-v1 | 0.7879 | 1.00 | 1.00 | 0.75 | 0.90 | 0.000 | 0 | 0 |
| SC-07 | lockdown-v1 | 0.7879 | 1.00 | 1.00 | 0.75 | 0.90 | 0.000 | 0 | 0 |
| SC-07 | sensitive-v1 | 0.7746 | 1.00 | 1.00 | 0.75 | 0.80 | 0.033 | 27 | 0 |

## 4. Evidence and exports

- **prometheus_textfile**: `/home/saifarfi/Volumetric/CSE499/results/metrics/props_twin.prom`
- **pushgateway**: `True`
- **otlp_endpoint**: `http://127.0.0.1:4318`
- **otel_evidence**: `/home/saifarfi/Volumetric/CSE499/results/otel`
- **ledger**: `postgresql://props:***@127.0.0.1:55432/props_ledger`
- **ledger contents**: 49 experiments, 47250 events, 49 ground-truth rows, 7 resets

## 5. Live stack (docker compose)

- idmz-gateway: up, mode=normal, t=20, healthy=True
- boundary-firewall: up, mode=normal, t=57, healthy=True
- plc-edge: up, mode=normal, t=57, healthy=True
- eng-station: up, mode=normal, t=57, healthy=True
- telemetry-forwarder: up, mode=normal, t=57, healthy=True
- prometheus target `estate` telemetry-forwarder:8000: up
- prometheus target `estate` idmz-gateway:8000: up
- prometheus target `estate` boundary-firewall:8000: up
- prometheus target `estate` plc-edge:8000: up
- prometheus target `estate` eng-station:8000: up
- prometheus target `otel-collector` otel-collector:8888: up
- prometheus target `pushgateway` pushgateway:9091: up
- PromQL `service_events_total` = 415.0
- PromQL `runner_reward_series` = None
- PromQL `collector_log_records_accepted` = 45482.0
- PromQL `collector_spans_accepted` = 192.0
- collector evidence files: {'logs.jsonl': 68, 'traces.jsonl': 5}
