"""Component cores: the behaviour the evaluator relies on, pinned per generator."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from research.common.props_log import EventSink
from services.eng_station.core import EngStation
from services.idmz_gateway.core import IdmzGateway
from services.telemetry_forwarder.core import TelemetryForwarder


def _sink():
    return EventSink("e", "SC", "baseline-v1", stream=False, collect=True)


def test_jump_host_contained_flag_tracks_access_profile():
    s = _sink()
    std = IdmzGateway(seed=1, config={"idmz_access_profile": "standard"})
    std.set_mode("jump_host_crossing"); std.tick(1, s)
    assert s.events[-1]["details"]["contained"] is False

    strict = IdmzGateway(seed=1, config={"idmz_access_profile": "strict"})
    strict.set_mode("jump_host_crossing"); strict.tick(1, s)
    assert s.events[-1]["details"]["contained"] is True


def test_gateway_probe_fails_only_under_lockdown():
    assert IdmzGateway(seed=1).probe(10)["ok"] in (True,)  # standard answers legitimate work
    assert IdmzGateway(seed=1, config={"idmz_access_profile": "lockdown"}).probe(10)["ok"] is False


def test_eng_station_audit_gap_omits_only_the_audit_log():
    s = _sink()
    es = EngStation(seed=1)
    es.tick(0, s)
    normal_types = {e["event_type"] for e in s.events}
    assert "security_audit_log" in normal_types     # present in normal operation

    s2 = _sink()
    es.set_mode("audit_log_gap"); es.tick(1, s2)
    gap_types = {e["event_type"] for e in s2.events}
    assert "security_audit_log" not in gap_types     # the required audit event is missing
    assert "tca_compliance_status" in gap_types      # but the host is still alive & reporting


def test_forwarder_pauses_then_drains_before_healthy():
    s = _sink()
    fw = TelemetryForwarder(seed=1, config={"buffer_drain_ticks": 3})
    fw.set_mode("heartbeat_pause")
    fw.tick(40, s)
    assert s.events == []                             # no heartbeat emitted during the pause

    fw.set_mode("normal")                             # lift the pause -> buffer drain owed
    s2 = _sink()
    for t in range(60, 66):
        fw.tick(t, s2)
    health = [e for e in s2.events if e["event_type"] == "diode_forwarding_health"]
    # first few ticks still fault (draining), then healthy normal resumes
    assert health[0]["simulated_state"] == "fault"
    assert health[-1]["simulated_state"] == "normal"
