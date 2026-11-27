"""Prometheus-style metrics for experiment runs and estate services.

`RunMetrics` owns a private CollectorRegistry (so tests and parallel runners do
not collide with the global default registry). `on_event` is an EventSink hook;
`record_evaluation` is called once per scored run. `write_textfile` produces the
node-exporter textfile format; `push` sends the registry to a Pushgateway (the
standard Prometheus pattern for short-lived batch jobs).
"""
from __future__ import annotations

import os

try:
    from prometheus_client import (
        CollectorRegistry,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
        push_to_gateway,
        write_to_textfile,
    )
    AVAILABLE = True
except ImportError:  # stdlib-only path
    AVAILABLE = False

REWARD_COMPONENTS = ("D", "C", "A", "Q", "F", "L")


class RunMetrics:
    def __init__(self, namespace: str = "props") -> None:
        self.enabled = AVAILABLE
        if not self.enabled:
            return
        self.registry = CollectorRegistry()
        r = self.registry
        self.events = Counter(
            f"{namespace}_events_total", "Telemetry events emitted by estate components",
            ["scenario", "component", "event_type", "severity", "state"], registry=r)
        self.runs = Counter(
            f"{namespace}_runs_total", "Experiment runs by final status",
            ["scenario", "status"], registry=r)
        self.resets = Counter(
            f"{namespace}_resets_total", "Executed reset procedures", ["scenario"], registry=r)
        self.reward = Gauge(
            f"{namespace}_reward", "Scalar reward R of the latest run",
            ["scenario", "policy_version"], registry=r)
        self.component = Gauge(
            f"{namespace}_reward_component", "Reward components D,C,A,Q,F,L of the latest run",
            ["scenario", "policy_version", "component"], registry=r)
        self.counts = Gauge(
            f"{namespace}_detection_count", "TP/FP/FN/G/alerts of the latest run",
            ["scenario", "kind"], registry=r)
        self.delay = Gauge(
            f"{namespace}_detection_delay_seconds", "Mean detection delay of the latest run",
            ["scenario"], registry=r)
        self.retention = Gauge(
            f"{namespace}_log_retention_ratio", "Persisted / emitted event records",
            ["scenario"], registry=r)
        self.prohibited = Gauge(
            f"{namespace}_prohibited_flows", "Violating flows NOT contained in the latest run",
            ["scenario"], registry=r)
        self.duration = Histogram(
            f"{namespace}_run_duration_seconds", "Wall-clock duration of a run",
            ["scenario"], buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5), registry=r)

    # --- hooks ------------------------------------------------------------
    def on_event(self, rec: dict) -> None:
        if not self.enabled:
            return
        self.events.labels(rec["scenario_id"], rec["component"], rec["event_type"],
                           rec["severity"], rec["simulated_state"]).inc()

    def record_reset(self, scenario_id: str) -> None:
        if self.enabled:
            self.resets.labels(scenario_id).inc()

    def record_run(self, record: dict) -> None:
        """Record a finished ledger record (see ExperimentRunner)."""
        if not self.enabled:
            return
        sid = record["scenario_id"]
        self.runs.labels(sid, record["status"]).inc()
        self.duration.labels(sid).observe(record.get("duration_s", 0.0))
        if record["status"] != "completed":
            return
        pv = record["policy_version"]
        self.reward.labels(sid, pv).set(record["reward"])
        for k in REWARD_COMPONENTS:
            self.component.labels(sid, pv, k).set(record["reward_components"][k])
        for k in ("TP", "FP", "FN", "G", "alerts"):
            self.counts.labels(sid, k).set(record["counts"][k])
        self.delay.labels(sid).set(record["metrics"]["detection_delay_s"])
        self.retention.labels(sid).set(record["metrics"]["log_retention"])
        self.prohibited.labels(sid).set(record["metrics"]["prohibited_flow_count"])

    # --- export -----------------------------------------------------------
    def exposition(self) -> bytes:
        return generate_latest(self.registry) if self.enabled else b""

    def write_textfile(self, path: str) -> str | None:
        if not self.enabled:
            return None
        os.makedirs(os.path.dirname(path), exist_ok=True)
        write_to_textfile(path, self.registry)
        return path

    def push(self, gateway: str | None, job: str = "props_twin_runner") -> bool:
        """Push to a Pushgateway; returns False (never raises) if unreachable."""
        if not (self.enabled and gateway):
            return False
        try:
            push_to_gateway(gateway, job=job, registry=self.registry, timeout=3)
            return True
        except Exception:  # noqa: BLE001 - telemetry must never fail a run
            return False
