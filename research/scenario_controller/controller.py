"""Scenario Controller (local, in-process, simulated-time).

Given a scenario dict it:
  1. builds the five estate components from the global seed,
  2. resets them, then steps a virtual clock over the evaluation window,
  3. applies timed mode changes against the component control endpoints,
  4. collects the emitted events and writes them + the ground-truth rows to
     SQLite (one row per labelled window), and
  5. returns the events + ground truth for the evaluator.

This is the headless core of Phase 3. The HTTP/Kubernetes and real-time-clock
paths (Step 3.3) wrap the same logic; keeping it here means the simulation can
be run and tested from a bare Ubuntu terminal with no server and no cluster.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
import sys

from research.common.props_log import EventSink
from research.scenario_controller.models import validate_scenario
from services.boundary_firewall.core import BoundaryFirewall
from services.eng_station.core import EngStation
from services.idmz_gateway.core import IdmzGateway
from services.plc_edge.core import PlcEdge
from services.telemetry_forwarder.core import TelemetryForwarder

EPOCH = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)

# zone each component reports under (for probe_result events)
COMPONENT_ZONE = {
    "idmz-gateway": "idmz",
    "boundary-firewall": "idmz",
    "plc-edge": "field",
    "eng-station": "supervisory",
    "telemetry-forwarder": "control",
}


def build_components(seed: int, estate_cfg: dict) -> dict:
    return {
        "idmz-gateway": IdmzGateway(seed, estate_cfg.get("idmz_gateway")),
        "boundary-firewall": BoundaryFirewall(seed, estate_cfg.get("boundary_firewall")),
        "plc-edge": PlcEdge(seed, estate_cfg.get("plc_edge")),
        "eng-station": EngStation(seed, estate_cfg.get("eng_station")),
        "telemetry-forwarder": TelemetryForwarder(seed, estate_cfg.get("telemetry_forwarder")),
    }


def run_scenario(
    scenario: dict,
    estate_cfg: dict | None = None,
    *,
    counter: int = 1,
    tick_seconds: int = 1,
    stream=sys.stdout,
    db_path: str | None = None,
) -> dict:
    """Run one scenario in simulated time. Returns {experiment_id, events, ground_truth}."""
    validate_scenario(scenario)
    estate_cfg = estate_cfg or {}
    seed = int(scenario["seed"])
    scenario_id = scenario["id"]
    experiment_id = f"exp-{scenario_id}-{seed}-{counter:04d}"
    policy_version = scenario["initial_conditions"].get("policy", "baseline-v1")

    components = build_components(seed, estate_cfg)

    # deterministic virtual clock: event_id stays random-free, timestamps advance
    sim_state = {"t": 0}

    def clock() -> dt.datetime:
        return EPOCH + dt.timedelta(seconds=sim_state["t"])

    sink = EventSink(experiment_id, scenario_id, policy_version,
                     stream=stream, collect=True, clock=clock)

    # schedule: expand {t, duration} into set-at / restore-at actions
    schedule: dict[int, list[tuple[str, str]]] = {}
    for act in scenario["event_sequence"]:
        target, value = act["target"], act.get("value", "normal")
        schedule.setdefault(int(act["t"]), []).append((target, value))
        if "duration" in act:
            end_t = int(act["t"]) + int(act["duration"])
            schedule.setdefault(end_t, []).append((target, "normal"))

    # optional availability probing: a legitimate-work prober polls targets every
    # `interval` seconds and logs a probe_result. Probes never kill a pod; an
    # unavailable component simply answers ok=False (availability cost, not a crash).
    probes = scenario.get("probes") or {}
    probe_interval = int(probes.get("interval", 0)) if probes else 0
    probe_targets = probes.get("targets", []) if probes else []

    end = int(scenario["evaluation_window"]["end"])
    for t in range(0, end + 1, tick_seconds):
        sim_state["t"] = t
        for target, value in schedule.get(t, []):
            if target in components:
                components[target].set_mode(value)
        for comp in components.values():
            comp.tick(t, sink)
        if probe_interval and t > 0 and t % probe_interval == 0:
            for target in probe_targets:
                comp = components.get(target)
                if comp is None or not hasattr(comp, "probe"):
                    continue
                res = comp.probe(t)
                ok = bool(res["ok"])
                sink.emit(
                    target, "probe_result",
                    "low" if ok else "high",
                    "normal" if ok else "fault",
                    COMPONENT_ZONE.get(target, "control"),
                    {"target": target, "ok": ok,
                     "latency_ms": res["latency_ms"], "sla_ms": res["sla_ms"]},
                )

    ground_truth = []
    for gt in scenario["ground_truth"]:
        ground_truth.append({
            "experiment_id": experiment_id,
            "scenario_id": scenario_id,
            "label": gt["label"],
            "t_start": gt["window"][0],
            "t_end": gt["window"][1],
            "expected_detection": bool(gt.get("expected_detection", True)),
        })

    if db_path:
        _persist(db_path, experiment_id, sink.events, ground_truth)

    return {"experiment_id": experiment_id,
            "events": sink.events,
            "ground_truth": ground_truth}


def _persist(db_path: str, experiment_id: str, events: list[dict], gt: list[dict]) -> None:
    con = sqlite3.connect(db_path)
    con.execute("""CREATE TABLE IF NOT EXISTS events(
        experiment_id TEXT, event_id TEXT, timestamp TEXT, component TEXT,
        event_type TEXT, severity TEXT, simulated_state TEXT, zone TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS ground_truth(
        experiment_id TEXT, scenario_id TEXT, label TEXT, t_start INT,
        t_end INT, expected_detection INT)""")
    con.executemany(
        "INSERT INTO events VALUES (?,?,?,?,?,?,?,?)",
        [(e["experiment_id"], e["event_id"], e["timestamp"], e["component"],
          e["event_type"], e["severity"], e["simulated_state"], e["zone"]) for e in events])
    con.executemany(
        "INSERT INTO ground_truth VALUES (?,?,?,?,?,?)",
        [(g["experiment_id"], g["scenario_id"], g["label"], g["t_start"],
          g["t_end"], int(g["expected_detection"])) for g in gt])
    con.commit()
    con.close()
