"""Shared event model and logging for every ProPS-Twin estate component.

Every component emits ONE JSON object per line. Ground truth (whether an event
*should* be detected) is deliberately NOT part of the event: it lives in the
Scenario Controller's ground-truth table and is joined later by event_id.
This keeps the detection pipeline honest.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
from collections.abc import Callable
from typing import Any

SEVERITIES = {"low", "medium", "high", "critical"}
STATES = {"normal", "anomalous", "fault", "violation"}
ZONES = {"enterprise", "idmz", "supervisory", "control", "field"}


def deterministic_event_id(experiment_id: str, component: str, seq: int) -> str:
    """Reproducible event id: same (experiment, component, seq) -> same id.

    Used instead of a random UUID so a run is byte-reproducible for a fixed seed.
    """
    raw = f"{experiment_id}|{component}|{seq}".encode()
    return hashlib.sha256(raw).hexdigest()[:32]


def build_event(
    component: str,
    event_type: str,
    severity: str,
    simulated_state: str,
    *,
    zone: str,
    experiment_id: str,
    scenario_id: str,
    policy_version: str,
    seq: int,
    details: dict | None = None,
    clock: Callable[[], dt.datetime] | None = None,
) -> dict[str, Any]:
    assert severity in SEVERITIES, f"bad severity {severity!r}"
    assert simulated_state in STATES, f"bad state {simulated_state!r}"
    assert zone in ZONES, f"bad zone {zone!r}"
    now = clock() if clock else dt.datetime.now(dt.UTC)
    return {
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "event_id": deterministic_event_id(experiment_id, component, seq),
        "experiment_id": experiment_id,
        "scenario_id": scenario_id,
        "component": component,
        "event_type": event_type,
        "severity": severity,
        "simulated_state": simulated_state,
        "zone": zone,
        "policy_version": policy_version,
        "details": details or {},
    }


def write_line(rec: dict, stream=None) -> None:
    out = stream if stream is not None else sys.stdout
    out.write(json.dumps(rec, separators=(",", ":")) + "\n")
    out.flush()


class EventSink:
    """Run-scoped emitter. Binds experiment/scenario/policy context and a per-
    component sequence counter, so component cores only supply the payload.

    - stream=sys.stdout (default): print JSON lines (what containers capture).
    - stream=False: do not print (headless/in-process collection only).
    - collect=True: also keep events in-memory (self.events) for tests/evaluation.
    """

    def __init__(
        self,
        experiment_id: str,
        scenario_id: str,
        policy_version: str,
        *,
        stream=sys.stdout,
        collect: bool = False,
        clock: Callable[[], dt.datetime] | None = None,
        hooks: list[Callable[[dict], None]] | None = None,
    ) -> None:
        self.experiment_id = experiment_id
        self.scenario_id = scenario_id
        self.policy_version = policy_version
        self.stream = stream
        self.collect = collect
        self.clock = clock
        # observers called with every emitted record (telemetry exporters:
        # Prometheus counters, OpenTelemetry log records, JSONL writers)
        self.hooks: list[Callable[[dict], None]] = list(hooks or [])
        self.events: list[dict] = []
        self._seq: dict[str, int] = {}

    def reset(self) -> None:
        """Drop collected events and restart every per-component sequence."""
        self.events = []
        self._seq = {}

    def emit(
        self,
        component: str,
        event_type: str,
        severity: str,
        simulated_state: str,
        zone: str,
        details: dict | None = None,
    ) -> dict:
        seq = self._seq.get(component, 0)
        self._seq[component] = seq + 1
        rec = build_event(
            component,
            event_type,
            severity,
            simulated_state,
            zone=zone,
            experiment_id=self.experiment_id,
            scenario_id=self.scenario_id,
            policy_version=self.policy_version,
            seq=seq,
            details=details,
            clock=self.clock,
        )
        if self.collect:
            self.events.append(rec)
        if self.stream is not False:
            write_line(rec, self.stream)
        for hook in self.hooks:
            hook(rec)
        return rec
