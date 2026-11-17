"""Telemetry forwarder / data diode (zone: control).

Unidirectional OT->IT forwarder. Emits the monitoring-estate signals and
exposes an aggregate health state used for availability + recovery probes.
SC-07 drives this component: controlled degradation of the forwarding
heartbeat (or a PTP/NTP time-sync drift), never a pod kill.

Recovery is not instantaneous: when a degradation/pause is lifted the forwarder
drains its buffer for ``buffer_drain_ticks`` before healthy telemetry resumes.
That settle time is what the evaluator measures as the recovery score Q, and it
is bounded by the ``recovery_timeout`` policy budget.
"""
from __future__ import annotations

from research.common.sim import gauss_nonneg, rng_for

COMPONENT = "telemetry-forwarder"
ZONE = "control"

_DEGRADED_MODES = {"heartbeat_pause", "forwarding_degraded"}


class TelemetryForwarder:
    def __init__(self, seed: int, config: dict | None = None):
        config = config or {}
        self.rng = rng_for(seed, offset=2)
        self.probe_rng = rng_for(seed, offset=22)
        self.mode = "normal"
        self.mem_baseline = float(config.get("mem_baseline", 0.45))
        self.jitter_baseline = float(config.get("jitter_baseline", 2.0))  # ms
        self.recovery_timeout = int(config.get("recovery_timeout", 60))
        self.buffer_drain_ticks = int(config.get("buffer_drain_ticks", 6))
        self.probe_sla_ms = float(config.get("probe_sla_ms", 50.0))
        self._recovering = 0  # ticks of buffer drain still owed

    def set_mode(self, mode: str) -> None:
        if self.mode in _DEGRADED_MODES and mode == "normal":
            # leaving a degraded state: owe a bounded buffer-drain before healthy
            self._recovering = self.buffer_drain_ticks
        self.mode = mode

    def apply_policy(self, policy: dict) -> None:
        if "recovery_timeout" in policy:
            self.recovery_timeout = int(policy["recovery_timeout"])

    def state(self) -> dict:
        healthy = self.mode == "normal" and self._recovering == 0
        return {"component": COMPONENT, "mode": self.mode, "healthy": healthy}

    @property
    def _available(self) -> bool:
        return self.mode not in _DEGRADED_MODES and self._recovering == 0

    def tick(self, t: int, sink) -> None:
        mem = gauss_nonneg(self.rng, self.mem_baseline, 0.03)
        jitter = gauss_nonneg(self.rng, self.jitter_baseline, 0.5)

        if self.mode == "heartbeat_pause":
            # deliberately emit NO forwarding heartbeat -> coverage gap (SC-07)
            return
        if self.mode == "forwarding_degraded":
            sink.emit(COMPONENT, "diode_forwarding_health", "high", "fault", ZONE,
                      {"forwarding_ok": False, "buffer_pct": 0.95})
            return
        if self.mode == "time_sync_drift":
            sink.emit(COMPONENT, "time_sync_drift", "medium", "anomalous", ZONE,
                      {"source": "ptp", "drift_ms": 420})
            return
        if self._recovering > 0:
            # draining buffer after a degradation: still not healthy yet
            self._recovering -= 1
            sink.emit(COMPONENT, "diode_forwarding_health", "high", "fault", ZONE,
                      {"forwarding_ok": False, "buffer_pct": round(0.95 - mem * 0.1, 3),
                       "recovering": True})
            return

        # normal baseline telemetry
        sink.emit(COMPONENT, "diode_forwarding_health", "low", "normal", ZONE,
                  {"forwarding_ok": True, "buffer_pct": round(0.20 + mem * 0.1, 3)})
        sink.emit(COMPONENT, "memory_utilization", "low", "normal", ZONE,
                  {"mem_pct": round(mem, 3), "jitter_ms": round(jitter, 2)})

    def probe(self, t: int) -> dict:
        """Answer an availability probe. Degraded/draining forwarder is unavailable."""
        latency = gauss_nonneg(self.probe_rng, 10.0, 3.0)
        if not self._available:
            return {"ok": False, "latency_ms": round(latency, 2), "sla_ms": self.probe_sla_ms}
        return {"ok": latency <= self.probe_sla_ms,
                "latency_ms": round(latency, 2), "sla_ms": self.probe_sla_ms}
