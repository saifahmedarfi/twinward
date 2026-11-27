"""Phase 3: config wiring, Pydantic schema, reset path, ledger, telemetry, HTTP wrapper."""
from __future__ import annotations

import copy
import json
import os

import pytest

from research.common.config import baseline_policy, load_weights, merge_policy
from research.evaluation.metrics import DEFAULT_WEIGHTS
from research.ledger.store import Ledger
from research.scenario_controller.catalog import SCENARIO_IDS, load
from research.scenario_controller.controller import TwinController
from research.scenario_controller.models import PYDANTIC, validate_scenario
from research.scenario_controller.runner import ExperimentRunner
from research.telemetry.otel import Telemetry
from research.telemetry.prom import RunMetrics


def _jsonl(path):
    with open(path) as fh:
        return [json.loads(x) for x in fh]


def _payload(events):
    return [(e["timestamp"], e["component"], e["event_type"], e["simulated_state"],
             json.dumps(e["details"], sort_keys=True)) for e in events]


@pytest.fixture
def runner(tmp_path):
    r = ExperimentRunner(ledger=Ledger(f"sqlite:///{tmp_path / 'ledger.sqlite'}"),
                         telemetry=Telemetry(evidence_dir=str(tmp_path / "otel"), endpoint=""),
                         metrics=RunMetrics(), log_dir=str(tmp_path / "logs"))
    yield r
    r.close()


# --- T1: config files are live ---------------------------------------------
def test_reward_yaml_is_read_and_matches_defaults():
    assert load_weights() == DEFAULT_WEIGHTS


def test_reward_weights_change_the_reward(tmp_path):
    p = tmp_path / "reward.yaml"
    p.write_text("w_d: 0.30\nw_c: 0.0\nw_a: 0.20\nw_r: 0.10\nw_f: 0.10\nw_l: 0.05\n")
    w = load_weights(str(p))
    assert w["w_c"] == 0.0
    r = ExperimentRunner(ledger=Ledger(f"sqlite:///{tmp_path / 'l.sqlite'}"),
                         telemetry=Telemetry(endpoint=""), log_dir=str(tmp_path / "logs"),
                         weights=w)
    rec = r.run("SC-04")
    r.close()
    assert rec["reward"] == pytest.approx(0.30 + 0.20 + 0.10)  # C no longer counts


def test_merge_policy_writes_levers_into_component_sections():
    est = merge_policy({"idmz_gateway": {"drop_baseline": 0.01}},
                       {"idmz_access_profile": "strict", "boundary_rate_limit": 30})
    assert est["idmz_gateway"] == {"drop_baseline": 0.01, "idmz_access_profile": "strict"}
    assert est["eng_station"]["idmz_access_profile"] == "strict"
    assert est["boundary_firewall"]["boundary_rate_limit"] == 30
    assert baseline_policy(est)["idmz_access_profile"] == "strict"


# --- T4: Pydantic schema ------------------------------------------------------
@pytest.mark.skipif(not PYDANTIC, reason="pydantic not installed")
@pytest.mark.parametrize("mutate", [
    lambda s: s["event_sequence"][1].update(action="explode"),
    lambda s: s["event_sequence"][1].update(target="reactor-core"),
    lambda s: s["ground_truth"][0].update(window=[50, 30]),
    lambda s: s["reset_procedure"].append("format_disk"),
    lambda s: s.update(probes={"interval": 0, "targets": []}),
    lambda s: s["ground_truth"][0].update(window=[30, 500]),
])
def test_malformed_scenarios_are_rejected(mutate):
    sc = copy.deepcopy(load("SC-01"))
    mutate(sc)
    with pytest.raises(ValueError):
        validate_scenario(sc)


@pytest.mark.parametrize("sid", SCENARIO_IDS)
def test_catalog_validates_under_pydantic(sid):
    validate_scenario(load(sid))


# --- T2: reset path -------------------------------------------------------------
@pytest.mark.parametrize("sid", SCENARIO_IDS)
def test_reset_restores_baseline_and_reproduces_the_run(sid):
    twin = TwinController(load(sid), {})
    first = twin.run()
    report = twin.reset()
    assert report["steps"] == ["restore_modes", "restore_policy_baseline",
                               "flush_state", "new_experiment_id"]
    assert report["all_normal"]
    second = twin.run()
    assert second["experiment_id"] != first["experiment_id"]
    assert _payload(first["events"]) == _payload(second["events"])


def test_without_reset_the_rerun_is_not_reproducible():
    twin = TwinController(load("SC-01"), {})
    first = twin.run()
    twin.dirty = False  # bypass the reset procedure
    again = twin.run()
    assert _payload(first["events"]) != _payload(again["events"])


def test_dirty_twin_auto_resets_before_the_next_run():
    twin = TwinController(load("SC-02"), {})
    a = twin.run()
    b = twin.run()
    assert b["experiment_id"].endswith("0002")
    assert _payload(a["events"]) == _payload(b["events"])


def test_restore_policy_baseline_undoes_a_candidate_policy():
    twin = TwinController(load("SC-04"), {}, policy={"idmz_access_profile": "lockdown"})
    assert twin.components["idmz-gateway"].idmz_access_profile == "lockdown"
    twin.run()
    twin.reset()
    assert twin.components["idmz-gateway"].idmz_access_profile == "standard"
    assert twin.policy == {}


def test_policy_set_before_a_dirty_run_survives_the_auto_reset():
    twin = TwinController(load("SC-04"), {})
    twin.run()
    twin.set_policy({"idmz_access_profile": "strict"})
    res = twin.run()
    crossings = [e for e in res["events"] if e["event_type"] == "idmz_jump_host_crossing"]
    assert crossings and all(e["details"]["contained"] for e in crossings)


# --- runner + ledger ------------------------------------------------------------
def test_experiment_record_has_every_field_the_proposal_requires(runner):
    rec = runner.run("SC-04")
    stored = runner.ledger.get(rec["experiment_id"])
    # unique id, timestamp, seed, initial config, policy, event ids, metrics, reward, status
    assert stored["experiment_id"] == "exp-SC-04-1004-0001"
    assert stored["created_at"] and stored["finished_at"]
    assert stored["seed"] == 1004
    assert stored["config_json"]["scenario"]["id"] == "SC-04"
    assert stored["policy_json"]["idmz_access_profile"] == "standard"
    assert stored["event_ids_sha256"] == rec["event_ids_sha256"]
    assert stored["metrics_json"]["detection_rate"] == 1.0
    assert stored["reward"] == pytest.approx(0.6)
    assert stored["status"] == "completed"


def test_every_emitted_event_is_persisted_and_logged(runner):
    rec = runner.run("SC-07")
    assert rec["metrics"]["retained_events"] == rec["n_events"]
    assert rec["metrics"]["log_retention"] == 1.0
    assert rec["metrics"]["log_lines"] == rec["n_events"]
    assert len(runner.ledger.events_for(rec["experiment_id"])) == rec["n_events"]


def test_experiment_ids_are_unique_across_runs(runner):
    ids = {runner.run("SC-01")["experiment_id"] for _ in range(3)}
    assert ids == {"exp-SC-01-1001-0001", "exp-SC-01-1001-0002", "exp-SC-01-1001-0003"}


def test_baseline_rewards_are_unchanged_by_the_phase3_wiring(runner):
    expected = {"SC-01": 0.85, "SC-02": 0.85, "SC-03": 0.60, "SC-04": 0.60,
                "SC-05": 0.8479, "SC-06": 0.60, "SC-07": 0.7879}
    for sid, r in expected.items():
        assert runner.run(sid)["reward"] == pytest.approx(r, abs=1e-4)


def test_policy_levers_move_containment_availability_and_false_positives(runner):
    strict = runner.run("SC-04", {"idmz_access_profile": "strict"})
    assert strict["reward_components"]["C"] == 1.0
    assert strict["metrics"]["prohibited_flow_count"] == 0
    lock = runner.run("SC-06", {"idmz_access_profile": "lockdown"})
    assert lock["reward_components"]["A"] == 0.0  # over-restriction starves legit work
    sens = runner.run("SC-01", {"alert_threshold": 1.0})
    assert sens["counts"]["FP"] > 0


# --- telemetry --------------------------------------------------------------------
def test_otel_trace_and_logs_are_correlated_with_the_ledger(runner, tmp_path):
    rec = runner.run("SC-01")
    runner.telemetry.tracer_provider.force_flush()
    spans = _jsonl(tmp_path / "otel" / "spans.jsonl")
    names = {s["name"] for s in spans if s["trace_id"] == rec["trace_id"]}
    assert names == {"experiment.run", "experiment.configure", "experiment.simulate",
                     "experiment.evaluate", "experiment.persist"}
    sim = next(s for s in spans if s["name"] == "experiment.simulate")
    assert [e["attributes"]["sim.t"] for e in sim["events"]] == [0, 30, 50]
    logs = _jsonl(tmp_path / "otel" / "logs.jsonl")
    assert len(logs) == rec["n_events"]
    assert {lg["trace_id"] for lg in logs} == {rec["trace_id"]}
    line = _jsonl(rec["log_path"])[0]
    assert line["trace_id"] == rec["trace_id"]


def test_prometheus_exposition_reports_the_run(runner):
    runner.run("SC-04")
    text = runner.metrics.exposition().decode()
    assert 'props_reward{policy_version="baseline-v1",scenario="SC-04"} 0.6' in text
    assert 'props_runs_total{scenario="SC-04",status="completed"} 1.0' in text
    assert "props_events_total{" in text
    assert 'props_log_retention_ratio{scenario="SC-04"} 1.0' in text


def test_event_schema_is_untouched_by_telemetry(runner):
    jsonschema = pytest.importorskip("jsonschema")
    with open(os.path.join(os.path.dirname(__file__), "..", "..", "research", "common",
                           "event_schema.json")) as fh:
        schema = json.load(fh)
    rec = runner.run("SC-05")
    ev = runner.ledger.events_for(rec["experiment_id"])[0]
    assert "trace_id" not in ev
    twin = TwinController(load("SC-05"), {})
    for e in twin.run()["events"][:50]:
        jsonschema.validate(e, schema)


# --- HTTP wrapper -------------------------------------------------------------------
def test_service_wrapper_endpoints():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from services.idmz_gateway.main import app
    with TestClient(app) as c:
        assert c.get("/healthz").json()["ok"]
        assert c.post("/tick?n=5").json()["t"] == 5
        ev = c.get("/events?limit=10").json()
        assert len(ev) == 5
        assert [e["details"]["near_miss"] for e in ev] == [False] * 5  # t=0..4: no near-miss
        assert c.post("/control/mode", json={"mode": "jump_host_crossing"}).json()["mode"] \
            == "jump_host_crossing"
        assert c.post("/policy", json={"idmz_access_profile": "strict"}).status_code == 200
        c.post("/tick")
        last = c.get("/events?limit=1").json()[0]
        assert last["event_type"] == "idmz_jump_host_crossing" and last["details"]["contained"]
        assert "ok" in c.get("/probe").json()
        m = c.get("/metrics").text
        assert "props_service_events_total" in m and "props_service_healthy" in m
        assert c.post("/reset").json()["mode"] == "normal"
        assert c.get("/state").json()["t"] == 0
        assert c.post("/policy", json={}).status_code == 422


def test_service_without_probe_returns_404():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from services.plc_edge.main import app
    with TestClient(app) as c:
        assert c.get("/probe").status_code == 404


@pytest.mark.skipif(not os.environ.get("PROPS_TEST_PG_URL"), reason="no PostgreSQL configured")
def test_postgres_ledger_roundtrip():
    led = Ledger(os.environ["PROPS_TEST_PG_URL"])
    r = ExperimentRunner(ledger=led, telemetry=Telemetry(endpoint=""))
    rec = r.run("SC-03")
    assert led.get(rec["experiment_id"])["status"] == "completed"
    assert led.count_events(rec["experiment_id"]) == rec["n_events"]
    r.close()
