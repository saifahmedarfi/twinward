"""IDMZ gateway core behaviour and SC-01 end-to-end simulation checks."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from research.common.props_log import EventSink
from research.scenario_controller.controller import run_scenario
from services.idmz_gateway.core import IdmzGateway

SC01 = {
    "id": "SC-01", "seed": 1001,
    "initial_conditions": {"policy": "baseline-v1"},
    "event_sequence": [
        {"t": 0, "target": "idmz-gateway", "action": "set_mode", "value": "normal"},
        {"t": 30, "target": "idmz-gateway", "action": "inject",
         "value": "inter_zone_protocol_anomaly", "duration": 20},
    ],
    "ground_truth": [{"label": "inter_zone_protocol_anomaly", "window": [30, 50],
                      "expected_detection": True}],
    "evaluation_window": {"start": 0, "end": 60},
    "reset_procedure": [],
}


def test_normal_mode_emits_heartbeat():
    gw = IdmzGateway(seed=1)
    sink = EventSink("e", "SC-01", "baseline-v1", stream=False, collect=True)
    gw.tick(0, sink)
    assert sink.events[0]["event_type"] == "gateway_heartbeat"


def test_anomaly_mode_emits_anomaly():
    gw = IdmzGateway(seed=1)
    gw.set_mode("inter_zone_protocol_anomaly")
    sink = EventSink("e", "SC-01", "baseline-v1", stream=False, collect=True)
    gw.tick(30, sink)
    assert sink.events[0]["event_type"] == "inter_zone_protocol_anomaly"
    assert sink.events[0]["simulated_state"] == "anomalous"


def test_non_whitelisted_protocol_denied():
    gw = IdmzGateway(seed=1)
    sink = EventSink("e", "SC-01", "baseline-v1", stream=False, collect=True)
    assert gw.handle_request({"protocol": "P9"}, sink) == "denied"
    assert sink.events[-1]["event_type"] == "non_whitelisted_protocol_violation"


def test_sc01_anomaly_count_matches_window():
    r = run_scenario(SC01, stream=False)
    anomalies = [e for e in r["events"]
                 if e["event_type"] == "inter_zone_protocol_anomaly"]
    assert len(anomalies) == 20  # t=30..49 inclusive


def test_run_is_reproducible():
    a = run_scenario(SC01, stream=False)
    b = run_scenario(SC01, stream=False)
    assert [e["event_id"] for e in a["events"]] == [e["event_id"] for e in b["events"]]
