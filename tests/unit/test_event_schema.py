"""Every emitted event must be exactly one valid JSON object against the schema."""
import json
import os
import sys

import jsonschema

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from research.common.props_log import EventSink

with open(os.path.join(ROOT, "research", "common", "event_schema.json")) as _f:
    SCHEMA = json.load(_f)


def test_emitted_event_validates():
    sink = EventSink("exp-T-1-0001", "SC-01", "baseline-v1", stream=False, collect=True)
    sink.emit("idmz-gateway", "gateway_heartbeat", "low", "normal", "idmz", {"drop_rate": 0.01})
    assert len(sink.events) == 1
    jsonschema.validate(sink.events[0], SCHEMA)


def test_event_id_is_deterministic():
    a = EventSink("exp-T-1-0001", "SC-01", "baseline-v1", stream=False, collect=True)
    b = EventSink("exp-T-1-0001", "SC-01", "baseline-v1", stream=False, collect=True)
    a.emit("plc-edge", "wdt_heartbeat", "low", "normal", "field")
    b.emit("plc-edge", "wdt_heartbeat", "low", "normal", "field")
    assert a.events[0]["event_id"] == b.events[0]["event_id"]
