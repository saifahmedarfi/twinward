.PHONY: demo eval viz viz-data test lint install compose-up compose-down cluster build deploy verify experiment results reset teardown
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
compose-up: ; docker compose up --build
compose-down: ; docker compose down

## --- cluster lifecycle (scaffolded in later phases) ----------------------
cluster:    ; @echo "[Phase 1] create kind cluster + Calico — see docs/ and handbook Step 1.2"
build:      ; @echo "[Phase 2] build images from services/*/Dockerfile and load into kind"
deploy:     ; @echo "[Phase 2/4] apply k8s manifests"
verify:     ; @echo "[Phase 4] verify the 5-stage log-to-alert chain"
experiment: ; @echo "[Phase 6] run SCENARIO=$(SCENARIO) METHOD=$(METHOD) SEED=$(SEED)"
results:    ; @echo "[Phase 5] export results to results/"
reset:      ; @echo "[Phase 3] reset scenario via controller API"
teardown:   ; @echo "[Phase 1] delete kind cluster"
