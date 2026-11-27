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
import hashlib
import json
import sqlite3
import sys
from collections.abc import Callable

from research.common.config import baseline_policy
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


class TwinController:
    """Stateful twin for one scenario: run, reset, re-run (handbook Step 3.4).

    The components live across runs so the reset path is real: after a run they
    are left in whatever mode the scenario drove them to, and `reset()` executes
    the scenario's declared `reset_procedure` steps to bring the estate back to
    a known baseline before the next candidate policy is evaluated.

    - restore_modes            every component back to mode "normal" (and any
                               in-flight recovery/drain cleared)
    - restore_policy_baseline  active policy back to the estate baseline
    - flush_state              rebuild every component from the global seed
                               (fresh RNG streams, counters, uptime) and clear
                               the event sink
    - new_experiment_id        advance the run counter -> fresh experiment_id
    """

    def __init__(self, scenario: dict, estate_cfg: dict | None = None, *,
                 policy: dict | None = None, counter: int = 1,
                 tick_seconds: int = 1, stream=False,
                 hooks: list[Callable[[dict], None]] | None = None,
                 on_action: Callable[[int, str, str], None] | None = None) -> None:
        validate_scenario(scenario)
        self.scenario = scenario
        self.estate_cfg = estate_cfg or {}
        self.counter = counter
        self.tick_seconds = tick_seconds
        self.stream = stream
        self.hooks = list(hooks or [])
        self.on_action = on_action
        self.seed = int(scenario["seed"])
        self.policy: dict = dict(policy or {})
        self.components = build_components(self.seed, self.estate_cfg)
        self._apply_policy()
        self.dirty = False  # True once a run has perturbed the components

    # --- identity ---------------------------------------------------------
    @property
    def experiment_id(self) -> str:
        return f"exp-{self.scenario['id']}-{self.seed}-{self.counter:04d}"

    @property
    def policy_version(self) -> str:
        ic = self.scenario["initial_conditions"]
        if not self.policy:
            return ic.get("policy", "baseline-v1")
        return self.policy.get("name") or "custom-" + policy_hash(self.policy)

    # --- policy -----------------------------------------------------------
    def set_policy(self, policy: dict | None) -> None:
        """Set the policy for the next run (applied through apply_policy())."""
        self.policy = dict(policy or {})
        self._apply_policy()

    def _apply_policy(self) -> None:
        levers = {k: v for k, v in self.policy.items() if k != "name"}
        if not levers:
            return
        for comp in self.components.values():
            comp.apply_policy(levers)

    # --- reset ------------------------------------------------------------
    def reset(self) -> dict:
        """Execute the scenario's reset_procedure. Returns a reset report."""
        before = {name: c.state() for name, c in self.components.items()}
        steps = []
        for step in self.scenario["reset_procedure"]:
            if step == "restore_modes":
                for comp in self.components.values():
                    comp.mode = "normal"
                    if hasattr(comp, "_recovering"):
                        comp._recovering = 0
            elif step == "restore_policy_baseline":
                # write the estate-baseline value of every lever back through
                # apply_policy() (RNG streams untouched; flush_state does those)
                self.policy = {}
                base = baseline_policy(self.estate_cfg)
                wl = (self.estate_cfg.get("idmz_gateway") or {}).get("protocol_whitelist")
                base["protocol_whitelist"] = wl or ["P1", "P2", "P3"]
                for comp in self.components.values():
                    comp.apply_policy(base)
            elif step == "flush_state":
                self.components = build_components(self.seed, self.estate_cfg)
                self._apply_policy()
            elif step == "new_experiment_id":
                self.counter += 1
            else:  # validated upstream; keep a hard failure for safety
                raise ValueError(f"unknown reset step {step!r}")
            steps.append(step)
        after = {name: c.state() for name, c in self.components.items()}
        self.dirty = False
        return {"scenario_id": self.scenario["id"], "steps": steps,
                "experiment_id": self.experiment_id,
                "before": before, "after": after,
                "all_normal": all(s["mode"] == "normal" for s in after.values())}

    # --- run --------------------------------------------------------------
    def run(self, db_path: str | None = None) -> dict:
        """Run the scenario once from a clean state. Auto-resets a dirty twin,
        keeping any policy set (via set_policy) for this next run."""
        if self.dirty:
            pending = dict(self.policy)
            self.reset()
            self.set_policy(pending)
        scenario = self.scenario
        scenario_id = scenario["id"]
        experiment_id = self.experiment_id
        components = self.components

        # deterministic virtual clock: event_id stays random-free, timestamps advance
        sim_state = {"t": 0}

        def clock() -> dt.datetime:
            return EPOCH + dt.timedelta(seconds=sim_state["t"])

        sink = EventSink(experiment_id, scenario_id, self.policy_version,
                         stream=self.stream, collect=True, clock=clock, hooks=self.hooks)

        # schedule: expand {t, duration} into set-at / restore-at actions
        schedule: dict[int, list[tuple[str, str]]] = {}
        for act in scenario["event_sequence"]:
            target, value = act["target"], act.get("value", "normal")
            schedule.setdefault(int(act["t"]), []).append((target, value))
            if act.get("duration"):
                end_t = int(act["t"]) + int(act["duration"])
                schedule.setdefault(end_t, []).append((target, "normal"))

        # optional availability probing: a legitimate-work prober polls targets every
        # `interval` seconds and logs a probe_result. Probes never kill a pod; an
        # unavailable component simply answers ok=False (availability cost, not a crash).
        probes = scenario.get("probes") or {}
        probe_interval = int(probes.get("interval", 0)) if probes else 0
        probe_targets = probes.get("targets", []) if probes else []

        self.dirty = True
        end = int(scenario["evaluation_window"]["end"])
        for t in range(0, end + 1, self.tick_seconds):
            sim_state["t"] = t
            for target, value in schedule.get(t, []):
                if target in components:
                    components[target].set_mode(value)
                    if self.on_action:
                        self.on_action(t, target, value)
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
                "policy_version": self.policy_version,
                "policy": dict(self.policy),
                "events": sink.events,
                "ground_truth": ground_truth,
                "final_state": {n: c.state() for n, c in components.items()}}


def policy_hash(policy: dict) -> str:
    raw = json.dumps(policy, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()[:8]


def run_scenario(
    scenario: dict,
    estate_cfg: dict | None = None,
    *,
    counter: int = 1,
    tick_seconds: int = 1,
    stream=sys.stdout,
    db_path: str | None = None,
    policy: dict | None = None,
    hooks: list[Callable[[dict], None]] | None = None,
) -> dict:
    """Run one scenario in simulated time. Returns {experiment_id, events, ground_truth, ...}."""
    twin = TwinController(scenario, estate_cfg, policy=policy, counter=counter,
                          tick_seconds=tick_seconds, stream=stream, hooks=hooks)
    return twin.run(db_path=db_path)


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
