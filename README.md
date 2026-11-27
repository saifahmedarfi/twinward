# ProPS-Twin

An LLM-guided digital twin of a nuclear power plant **IT/OT security department**.
A synthetic estate of five containerized components emits security telemetry;
controlled cyber scenarios perturb it; Wazuh monitors it; and (later) an LLM
proposes bounded defensive policies that are validated, applied and scored.

This repo is scaffolded **simulation-first**. The simulation core runs today in
a bare terminal. Wazuh and the LLM/ProPS loop come in later phases.

## Primary entry point: `main.py`

```bash
python main.py phase3                     # whole Phase 3 run -> results/phase3/report.md
python main.py run SC-04 --preset strict-v1
python main.py run SC-04 --policy idmz_access_profile=lockdown
python main.py reset all                  # run -> reset -> re-run checks (Step 3.4)
python main.py ledger                     # recorded experiments
```

Each run is one recorded experiment: unique id, config snapshot, policy, events,
metrics, reward, status -> **ledger** (SQLite by default, PostgreSQL via
`PROPS_DB_URL`); structured **JSONL log** per experiment; an **OpenTelemetry**
trace (configure / simulate / evaluate / persist) with trace-correlated log
records; **Prometheus** metrics (textfile + Pushgateway).

### Full observability stack (Docker)

```bash
make stack-up        # 5 estate services + OTel Collector + Prometheus + Pushgateway + PostgreSQL
make phase3-live     # same Phase 3 run, exporting to the stack
make status          # services, Prometheus targets, collector evidence
make stack-down
```

Ports (127.0.0.1 only): services 8001-8005, Prometheus 9090, Pushgateway 9091,
OTLP 4318, PostgreSQL 55432. Services expose `/healthz /state /control/mode
/policy /tick /probe /reset /events /metrics` and emit live telemetry every
second.

## Quick start (no cluster, no dependencies)

```bash
python3 scripts/demo_local.py          # run scenario SC-01 in simulated time
python3 scripts/demo_local.py --quiet  # just the summary

python3 scripts/evaluate_local.py SC-04    # run + score one scenario (reward breakdown)
python3 scripts/evaluate_local.py all       # score the whole SC-01..SC-07 suite
python3 scripts/evaluate_local.py SC-07 --json
```

You should see a JSON event stream and a summary reporting ~20 anomaly events in
the `[30,50]` window, ground truth persisted to `results/demo.sqlite`, and
reproducible `event_id`s (run it twice — identical). `evaluate_local.py` runs the
log-only (fast-mode) evaluator and prints the per-component reward
`R = w_dD + w_cC + w_aA + w_rQ − w_fF − w_lL` — see [docs/metrics.md](docs/metrics.md).

## Run the tests

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
make test        # pytest: schema validation + SC-01 simulation checks
make lint        # ruff + mypy
```

## Run the components as HTTP services (optional, local)

```bash
pip install -r requirements.txt
uvicorn services.idmz_gateway.main:app --port 8001
curl -s localhost:8001/healthz
curl -s -X POST localhost:8001/control/mode -H 'content-type: application/json' \
     -d '{"mode":"inter_zone_protocol_anomaly"}'
# or: docker compose up --build   (all five on ports 8001-8005)
```

## Layout

```
configs/estate/        estate-config.yaml (zones, baselines, policy defaults)
configs/scenarios/     SC-01.yaml (+ SC-02..SC-07 to add)
research/common/       event model, logging, schema, seeded RNG  <-- shared
research/scenario_controller/  runs a scenario in simulated time
services/<component>/   core.py (sim logic) + main.py (FastAPI) + Dockerfile
scripts/demo_local.py   zero-dependency SC-01 runner
tests/unit/             schema + simulation tests
docs/                   DECISIONS, VERSIONS, props_notes, protocol, signals
research/policy_engine/ research/evaluation/ research/props_optimizer/  <-- later phases
wazuh/ k8s/ cluster/    <-- Phases 1 and 4
```

## Where this sits in the handbook

- **Built now:** Phase 2 (estate simulator); Phase 3 complete — seven scenarios
  SC-01..SC-07, Pydantic scenario schema, reset path, live estate/reward config,
  experiment ledger (SQLite/PostgreSQL), structured logs, OpenTelemetry traces +
  logs, Prometheus metrics, docker-compose observability stack; and the Phase 5
  evaluation engine (log-only / fast-mode path, see [docs/metrics.md](docs/metrics.md)).
- **Next:** Phase 4 of the proposal — Policy Engine (bounds + hard constraints)
  and the ProPS/LLM loop with random-search and conventional-optimizer
  baselines; then Wazuh-in-the-loop and Kubernetes.
- **After the simulation is solid:** Phase 6 (Policy Engine + LLM/ProPS loop);
  the policy levers (`alert_threshold`, access profile, rate limit, recovery
  timeout) already move the reward, so the optimizer has a real search space.

Build order and acceptance checks are in the step-by-step handbook PDF.
Keep `docs/DECISIONS.md` current as you go.
