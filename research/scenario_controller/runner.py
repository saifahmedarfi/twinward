"""Experiment runner: the proposal's run cycle (Figure 2, steps 1-4 + persist).

    1. Configure   load scenario + estate config + reward weights, assign a
                   unique experiment id (ledger counter), snapshot the config
    2. Simulate    TwinController runs the controlled failure in simulated time
    3. Observe     every event goes to the structured JSONL log, OTel log
                   records (trace-correlated) and Prometheus counters
    4. Evaluate    deterministic log-only evaluator -> metrics + reward
    5. Persist     events, ground truth, metrics, reward, status -> ledger

Steps 5-7 of Figure 2 (Propose / Validate / Re-run) are the ProPS loop of the
next phase; it will call `ExperimentRunner.run(scenario_id, policy=...)`.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import time

from research.common.config import (
    ROOT,
    baseline_policy,
    load_estate,
    load_weights,
    merge_policy,
)
from research.evaluation.engine import _t_of, evaluate
from research.ledger.store import Ledger
from research.scenario_controller.catalog import load
from research.scenario_controller.controller import TwinController, policy_hash
from research.telemetry.jsonlog import RunLog
from research.telemetry.otel import Telemetry
from research.telemetry.prom import RunMetrics

RESULTS = os.path.join(ROOT, "results")

# scenario initial_conditions keys that are policy levers
_IC_LEVERS = {"idmz_profile": "idmz_access_profile", "idmz_access_profile": "idmz_access_profile",
              "boundary_rate_limit": "boundary_rate_limit", "alert_threshold": "alert_threshold",
              "recovery_timeout": "recovery_timeout"}


def code_version() -> str | None:
    try:
        return subprocess.run(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=5, check=False).stdout.strip() or None
    except Exception:  # noqa: BLE001
        return None


def flow_metrics(events: list[dict]) -> dict:
    """Containment-side counts (proposal Table 3): violating flows that were
    blocked before effect vs prohibited flows that got through."""
    blocked = prohibited = 0
    for e in events:
        det = e.get("details") or {}
        if "contained" in det and e["simulated_state"] in ("violation", "anomalous"):
            if det["contained"]:
                blocked += 1
            else:
                prohibited += 1
    return {"blocked_flow_count": blocked, "prohibited_flow_count": prohibited}


def recovery_time(events: list[dict], scenario: dict) -> float | None:
    """Seconds from fault end until the monitored signal is healthy again."""
    for row in scenario["ground_truth"]:
        if not row.get("measure_recovery"):
            continue
        end = int(row["window"][1])
        ts = sorted(_t_of(e) for e in events
                    if e["component"] == row["component"] and e["event_type"] == row["event_type"]
                    and e["simulated_state"] == "normal")
        healthy = [t for t in ts if t >= end]
        return float(healthy[0] - end) if healthy else None
    return None


class ExperimentRunner:
    def __init__(self, *, ledger: Ledger | None = None, telemetry: Telemetry | None = None,
                 metrics: RunMetrics | None = None, log_dir: str | None = None,
                 estate: dict | None = None, weights: dict | None = None,
                 stream=False) -> None:
        self.ledger = ledger or Ledger()
        self.telemetry = telemetry or Telemetry(evidence_dir=os.path.join(RESULTS, "otel"))
        self.metrics = metrics or RunMetrics()
        self.log_dir = log_dir or os.path.join(RESULTS, "logs")
        self.estate = load_estate() if estate is None else estate
        self.weights = load_weights() if weights is None else weights
        self.stream = stream
        self.code_version = code_version()

    # --- policy resolution -------------------------------------------------
    def effective_policy(self, scenario: dict, policy: dict | None) -> dict:
        """estate baseline <- scenario initial_conditions <- candidate policy."""
        eff = baseline_policy(self.estate)
        for k, lever in _IC_LEVERS.items():
            if k in scenario.get("initial_conditions", {}):
                eff[lever] = scenario["initial_conditions"][k]
        for k, v in (policy or {}).items():
            if k != "name":
                eff[k] = v
        return eff

    # --- one experiment ------------------------------------------------------
    def run(self, scenario_id: str, policy: dict | None = None) -> dict:
        t0 = time.perf_counter()
        scenario = load(scenario_id)
        seed = int(scenario["seed"])
        counter = self.ledger.next_counter(scenario["id"], seed)
        eff = self.effective_policy(scenario, policy)
        # components boot with the scenario baseline; the candidate is applied
        # on top through apply_policy() (so reset can restore the baseline)
        base_cfg = merge_policy(self.estate, self.effective_policy(scenario, None))
        twin = TwinController(scenario, base_cfg, policy=policy, counter=counter,
                              stream=self.stream, on_action=self.telemetry.on_action)
        exp_id = twin.experiment_id
        policy_version = twin.policy_version
        config = {"scenario": scenario, "estate": self.estate, "weights": self.weights,
                  "effective_policy": eff}

        self.ledger.start(experiment_id=exp_id, scenario_id=scenario["id"], seed=seed,
                          run_counter=counter, policy_version=policy_version,
                          policy=eff, config=config, code_version=self.code_version)
        attrs = {"experiment.id": exp_id, "scenario.id": scenario["id"], "scenario.seed": seed,
                 "policy.version": policy_version, "policy.hash": policy_hash(eff),
                 "policy.params": eff, "code.version": self.code_version}
        record: dict = {"experiment_id": exp_id, "scenario_id": scenario["id"], "seed": seed,
                        "policy_version": policy_version, "policy": eff}
        try:
            with self.telemetry.run_span(attrs) as ids:
                with self.telemetry.phase("configure", {"ledger.backend": self.ledger.backend}):
                    log = RunLog(self.log_dir, exp_id, ids["trace_id"], None)
                    twin.hooks = [self.metrics.on_event, self.telemetry.on_event, log.on_event]
                with self.telemetry.phase("simulate", {"sim.window_end":
                                                       scenario["evaluation_window"]["end"]}):
                    log.span_id = self.telemetry.current_ids()["span_id"]
                    run = twin.run()
                    log.close()
                with self.telemetry.phase("evaluate") as span:
                    doc = evaluate(run, scenario,
                                   alert_threshold=float(eff["alert_threshold"]),
                                   recovery_budget=float(eff["recovery_timeout"]),
                                   weights=self.weights)
                    if span is not None:
                        span.add_event("evaluation.result", {
                            "reward": doc["reward"], **{f"R.{k}": v for k, v in
                                                        doc["reward_components"].items()}})
                with self.telemetry.phase("persist"):
                    n_persisted = self.ledger.persist_evidence(exp_id, run["events"],
                                                               run["ground_truth"])
                events = run["events"]
                ids_sha = hashlib.sha256("".join(e["event_id"] for e in events).encode()
                                         ).hexdigest()
                metrics = dict(doc["metrics"])
                metrics.update(flow_metrics(events))
                metrics["recovery_time_s"] = recovery_time(events, scenario)
                metrics["retained_events"] = n_persisted
                metrics["log_retention"] = n_persisted / len(events) if events else 1.0
                metrics["log_lines"] = log.lines
                duration = time.perf_counter() - t0
                record.update({
                    "status": "completed", "reward": doc["reward"],
                    "reward_components": doc["reward_components"], "metrics": metrics,
                    "counts": doc["counts"], "coverage": doc["coverage"],
                    "n_events": len(events), "event_ids_sha256": ids_sha,
                    "trace_id": ids["trace_id"], "log_path": log.path,
                    "duration_s": duration, "final_state": run["final_state"],
                })
                self.telemetry.set_run_attrs({"run.status": "completed",
                                              "run.reward": doc["reward"],
                                              "run.events": len(events)})
            self.ledger.finish(exp_id, status="completed", duration_s=duration,
                               reward=doc["reward"], components=doc["reward_components"],
                               metrics=metrics, counts=doc["counts"], n_events=len(events),
                               n_persisted=n_persisted, event_ids_sha256=ids_sha,
                               trace_id=ids["trace_id"])
        except Exception as exc:
            duration = time.perf_counter() - t0
            record.update({"status": "failed", "error": repr(exc), "duration_s": duration})
            self.ledger.finish(exp_id, status="failed", duration_s=duration, error=repr(exc))
            self.metrics.record_run(record)
            raise
        self.metrics.record_run(record)
        self._last_twin = twin
        return record

    # --- reset demonstration (Step 3.4) ---------------------------------------
    def run_reset_cycle(self, scenario_id: str, policy: dict | None = None) -> dict:
        """Run -> reset -> re-run on one twin and check the reset restored the
        baseline: same event payload sequence, fresh experiment id."""
        scenario = load(scenario_id)
        base_cfg = merge_policy(self.estate, self.effective_policy(scenario, None))
        twin = TwinController(scenario, base_cfg, policy=policy,
                              counter=self.ledger.next_counter(scenario["id"],
                                                               int(scenario["seed"])))
        first = twin.run()
        dirty_state = {n: c.state() for n, c in twin.components.items()}
        report = twin.reset()
        self.ledger.record_reset(report, first["experiment_id"])
        self.metrics.record_reset(scenario["id"])
        twin.set_policy(policy)
        second = twin.run()

        # control: the same twin re-run WITHOUT the reset procedure (RNG streams
        # and counters carry over) should NOT reproduce the first run
        twin.dirty = False
        no_reset = twin.run()

        def payload(evs: list[dict]) -> list[tuple]:
            return [(e["timestamp"], e["component"], e["event_type"], e["severity"],
                     e["simulated_state"], repr(sorted((e.get("details") or {}).items())))
                    for e in evs]

        return {"scenario_id": scenario["id"], "first_experiment": first["experiment_id"],
                "second_experiment": second["experiment_id"], "steps": report["steps"],
                "state_before_reset": dirty_state, "state_after_reset": report["after"],
                "all_normal_after_reset": report["all_normal"],
                "events": [len(first["events"]), len(second["events"])],
                "payload_identical": payload(first["events"]) == payload(second["events"]),
                "payload_identical_without_reset":
                    payload(second["events"]) == payload(no_reset["events"]),
                "fresh_experiment_id": first["experiment_id"] != second["experiment_id"]}

    def close(self) -> None:
        self.telemetry.shutdown()
        self.ledger.close()
