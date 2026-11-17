"""The scenario catalog: every scenario validates, is reproducible, and the
built-in dicts match the canonical YAML files."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import pytest

from research.scenario_controller.catalog import SCENARIO_IDS, SCENARIOS, load
from research.scenario_controller.controller import run_scenario
from research.scenario_controller.models import validate_scenario


def test_catalog_has_the_seven_core_scenarios():
    assert SCENARIO_IDS == [f"SC-0{i}" for i in range(1, 8)]


@pytest.mark.parametrize("sid", SCENARIO_IDS)
def test_scenario_validates(sid):
    validate_scenario(load(sid))


@pytest.mark.parametrize("sid", SCENARIO_IDS)
def test_event_stream_is_reproducible(sid):
    a = run_scenario(load(sid), stream=False)
    b = run_scenario(load(sid), stream=False)
    assert [e["event_id"] for e in a["events"]] == [e["event_id"] for e in b["events"]]


@pytest.mark.parametrize("sid", SCENARIO_IDS)
def test_yaml_matches_builtin(sid):
    yaml = pytest.importorskip("yaml")
    path = os.path.join(ROOT, "configs", "scenarios", f"{sid}.yaml")
    with open(path) as fh:
        from_yaml = yaml.safe_load(fh)
    builtin = SCENARIOS[sid]
    # compare the fields the controller + evaluator actually consume
    for key in ("id", "seed", "event_sequence", "ground_truth",
                "evaluation_window", "probes"):
        assert from_yaml.get(key) == builtin.get(key), f"{sid}: {key} drifted from YAML"
