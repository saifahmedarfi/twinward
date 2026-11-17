"""Evaluation engine: per-scenario scoring, policy levers, and the invariants."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from research.evaluation.engine import evaluate
from research.scenario_controller.catalog import SCENARIO_IDS, load
from research.scenario_controller.controller import run_scenario


def _score(scenario_id, **kw):
    sc = load(scenario_id)
    return sc, evaluate(run_scenario(sc, **kw), sc)


def test_every_scenario_detects_its_incident():
    # Baseline policy must detect the injected incident in all seven scenarios.
    for sid in SCENARIO_IDS:
        _, doc = _score(sid)
        assert doc["reward_components"]["D"] == 1.0, f"{sid} missed its incident"
        assert doc["counts"]["FP"] == 0, f"{sid} raised a baseline false positive"


def test_sc01_counts_twenty_true_positives():
    _, doc = _score("SC-01")
    assert doc["counts"]["TP"] == 20 and doc["counts"]["G"] == 20


def test_absence_scenarios_flag_the_coverage_gap():
    for sid in ("SC-05", "SC-07"):
        _, doc = _score(sid)
        assert doc["coverage"] and doc["coverage"][0]["detected"], f"{sid} missed the gap"


def test_sc07_availability_and_recovery_are_degraded_then_bounded():
    _, doc = _score("SC-07")
    rc = doc["reward_components"]
    assert rc["A"] < 1.0        # probes fail while the forwarder is unavailable
    assert 0.0 < rc["Q"] < 1.0  # recovery takes a bounded, non-zero settle time
    assert doc["counts"]["probe_ok"] < doc["counts"]["probes"]


def test_containment_lever_changes_reward():
    # SC-04 jump-host crossing: a strict access profile denies it at the boundary.
    sc = load("SC-04")
    strict_cfg = {"idmz_gateway": {"idmz_access_profile": "strict"}}
    base = evaluate(run_scenario(sc, stream=False), sc)
    strict = evaluate(run_scenario(sc, estate_cfg=strict_cfg, stream=False), sc)
    assert base["reward_components"]["C"] == 0.0
    assert strict["reward_components"]["C"] == 1.0
    assert strict["reward"] > base["reward"]


def test_alert_threshold_lever_trades_detection_for_false_positives():
    sc = load("SC-01")
    run = run_scenario(sc, stream=False)
    loose = evaluate(run, sc, alert_threshold=1.0)   # low cutoff -> near-miss FPs
    strict = evaluate(run, sc, alert_threshold=5.0)  # high cutoff -> misses anomaly
    assert loose["reward_components"]["F"] > 0.0
    assert strict["reward_components"]["D"] < 1.0


def test_reward_is_reproducible_for_a_fixed_seed():
    sc = load("SC-07")
    a = evaluate(run_scenario(sc, stream=False), sc)
    b = evaluate(run_scenario(sc, stream=False), sc)
    assert a["reward"] == b["reward"]
    assert a["reward_components"] == b["reward_components"]


def test_ground_truth_never_enters_the_event_stream():
    # Invariant: no emitted event carries a detection label / expected_detection.
    sc = load("SC-04")
    result = run_scenario(sc, stream=False)
    forbidden = {"label", "expected_detection", "ground_truth", "detection_type",
                 "expected_severity", "contain_expected"}
    for e in result["events"]:
        assert forbidden.isdisjoint(e.keys())
        assert forbidden.isdisjoint((e.get("details") or {}).keys())


def test_pods_never_die_even_under_degradation():
    # Invariant: SC-07 degrades availability without any component becoming unbuilt;
    # the forwarder keeps answering probes (ok=False) rather than disappearing.
    sc = load("SC-07")
    result = run_scenario(sc, stream=False)
    probes = [e for e in result["events"] if e["event_type"] == "probe_result"]
    assert probes, "expected availability probes"
    assert any(not (e["details"]["ok"]) for e in probes)  # some failed (unavailable)
    assert any(e["details"]["ok"] for e in probes)         # but it recovered, still alive
