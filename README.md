# ProPS-Twin

An LLM-guided digital twin of a nuclear power plant **IT/OT security department**.
A synthetic estate of five containerized components emits security telemetry;
controlled cyber scenarios perturb it; Wazuh monitors it; and (later) an LLM
proposes bounded defensive policies that are validated, applied and scored.

This repo is scaffolded **simulation-first**. The simulation core runs today in
a bare terminal. Wazuh and the LLM/ProPS loop come in later phases.

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

- **Built now:** Phase 2 (estate simulator), the headless half of Phase 3
  (scenario engine) for all seven scenarios SC-01..SC-07, and the Phase 5
  evaluation engine (log-only / fast-mode path: metrics + reward, see
  [docs/metrics.md](docs/metrics.md)).
- **Next:** the reset path (Step 3.4), then Phase 1 (kind + Calico) and Phase 4
  (Wazuh) to add the Wazuh-in-the-loop evaluation subset and reach `milestone-1`.
- **After the simulation is solid:** Phase 6 (Policy Engine + LLM/ProPS loop);
  the policy levers (`alert_threshold`, access profile, rate limit, recovery
  timeout) already move the reward, so the optimizer has a real search space.

Build order and acceptance checks are in the step-by-step handbook PDF.
Keep `docs/DECISIONS.md` current as you go.
