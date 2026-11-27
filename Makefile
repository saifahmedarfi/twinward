.PHONY: demo eval viz viz-data test lint install compose-up compose-down cluster build deploy verify experiment results reset teardown \
        run suite phase3 phase3-live ledger status stack-up stack-down stack-logs
PY ?= python3
SCENARIO ?= all
PORT ?= 8008

## --- local simulation (works now, no cluster needed) ---------------------
demo:       ; $(PY) scripts/demo_local.py
eval:       ; $(PY) scripts/evaluate_local.py $(SCENARIO)
viz:        ; $(PY) scripts/viz_server.py --port $(PORT) --open
viz-data:   ; $(PY) scripts/make_viz_data.py
test:       ; $(PY) -m pytest -q
lint:       ; ruff check . ; mypy research services
install:    ; $(PY) -m pip install -r requirements-dev.txt
compose-up: stack-up
compose-down: stack-down

## --- Phase 3: scenarios + telemetry (primary entry point: main.py) --------
# live-stack endpoints (docker compose, 127.0.0.1 only)
LIVE_ENV = PROPS_DB_URL=postgresql://props:props-local-only@127.0.0.1:55432/props_ledger \
           OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318 PROM_PUSHGATEWAY=127.0.0.1:9091
run:        ; $(PY) main.py run $(if $(filter all,$(SCENARIO)),SC-01,$(SCENARIO)) $(if $(PRESET),--preset $(PRESET))
suite:      ; $(PY) main.py suite
phase3:     ; $(PY) main.py phase3                 # local: SQLite ledger + JSONL evidence
phase3-live: ; $(LIVE_ENV) $(PY) main.py phase3    # against the docker-compose stack
ledger:     ; $(PY) main.py ledger
status:     ; $(PY) main.py status
stack-up:   ; mkdir -p results/collector && chmod 777 results/collector && docker compose up -d --build
stack-down: ; docker compose down
stack-logs: ; docker compose logs --tail=50

## --- cluster lifecycle (scaffolded in later phases) ----------------------
cluster:    ; @echo "[Phase 1] create kind cluster + Calico — see docs/ and handbook Step 1.2"
build:      ; @echo "[Phase 2] build images from services/*/Dockerfile and load into kind"
deploy:     ; @echo "[Phase 2/4] apply k8s manifests"
verify:     ; @echo "[Phase 4] verify the 5-stage log-to-alert chain"
experiment: ; @echo "[Phase 6] run SCENARIO=$(SCENARIO) METHOD=$(METHOD) SEED=$(SEED)"
results:    ; @echo "[Phase 5] export results to results/"
reset:      ; $(PY) main.py reset $(SCENARIO)
teardown:   ; @echo "[Phase 1] delete kind cluster"
