"""IDMZ boundary gateway (zone: idmz).

Brokers inter-zone requests and emits the boundary/identity signals:
inter-zone protocol anomalies, jump-host lateral crossings, unauthenticated
access attempts, electronic access-control badging, and allow/deny/violation
events. SC-01 drives the protocol anomaly; SC-04 the jump-host crossing;
SC-06 the unauthenticated/remote access.

Raw signal only lives in the event stream. The *detection* threshold is applied
later by the evaluator (log-only detector) or by Wazuh rules, never here, so a
policy can change what counts as an alert without re-running the simulation.
Attack events carry a ``contained`` flag derived from the access profile: that
is the device enforcing its own policy (realistic), not ground truth.
"""
from __future__ import annotations

from research.common.sim import gauss_nonneg, rng_for

COMPONENT = "idmz-gateway"
ZONE = "idmz"

# profiles under which the gateway denies/blocks a crossing before effect
_CONTAINING_PROFILES = {"strict", "lockdown"}
# every Nth normal tick emits a benign-but-elevated reading (false-positive bait)
_NEAR_MISS_PERIOD = 7
_NEAR_MISS_BUMP = 0.12
_ANOMALY_BUMP = 0.20


class IdmzGateway:
    def __init__(self, seed: int, config: dict | None = None):
        config = config or {}
        self.rng = rng_for(seed, offset=0)
        self.probe_rng = rng_for(seed, offset=20)  # separate stream: probes never
        self.mode = "normal"                        # perturb the telemetry stream
        self.drop_baseline = float(config.get("drop_baseline", 0.01))
        self.drop_sigma = float(config.get("drop_sigma", 0.004))
        # defensive-policy parameters (set by the Policy Engine later)
        self.alert_threshold = float(config.get("alert_threshold", 3.0))
        self.idmz_access_profile = config.get("idmz_access_profile", "standard")
        self.protocol_whitelist = set(config.get("protocol_whitelist", ["P1", "P2", "P3"]))
        self.probe_sla_ms = float(config.get("probe_sla_ms", 50.0))

    # --- control -----------------------------------------------------------
    def set_mode(self, mode: str) -> None:
        self.mode = mode

    def apply_policy(self, policy: dict) -> None:
        if "alert_threshold" in policy:
            self.alert_threshold = float(policy["alert_threshold"])
        if "idmz_access_profile" in policy:
            self.idmz_access_profile = policy["idmz_access_profile"]
        if "protocol_whitelist" in policy:
            self.protocol_whitelist = set(policy["protocol_whitelist"])

    def state(self) -> dict:
        return {"component": COMPONENT, "mode": self.mode, "healthy": True}

    @property
    def _contained(self) -> bool:
        return self.idmz_access_profile in _CONTAINING_PROFILES

    # --- telemetry tick ----------------------------------------------------
    def tick(self, t: int, sink) -> None:
        drop = gauss_nonneg(self.rng, self.drop_baseline, self.drop_sigma)
        if self.mode == "inter_zone_protocol_anomaly":
            sink.emit(
                COMPONENT, "inter_zone_protocol_anomaly", "high", "anomalous", ZONE,
                {"protocol": "modbus_unlisted", "drop_rate": round(drop + _ANOMALY_BUMP, 4),
                 "threshold": self.alert_threshold},
            )
        elif self.mode == "jump_host_crossing":
            sink.emit(
                COMPONENT, "idmz_jump_host_crossing", "high", "violation", ZONE,
                {"src_zone": "enterprise", "dst_zone": "control", "via": "jump-host-01",
                 "contained": self._contained},
            )
        elif self.mode == "unauthenticated_access":
            sink.emit(
                COMPONENT, "unauthenticated_access_attempt", "high", "violation", ZONE,
                {"identity": "unknown", "channel": "remote", "contained": self._contained},
            )
        else:
            # normal: heartbeat; periodic benign near-miss (elevated-but-allowed)
            near = t > 0 and t % _NEAR_MISS_PERIOD == 0
            dr = drop + (_NEAR_MISS_BUMP if near else 0.0)
            sink.emit(
                COMPONENT, "gateway_heartbeat", "low", "normal", ZONE,
                {"drop_rate": round(dr, 4), "near_miss": near},
            )

    # --- availability probe (legitimate inter-zone work) -------------------
    def probe(self, t: int) -> dict:
        """Answer a legitimate availability probe. Lockdown starves real work."""
        latency = gauss_nonneg(self.probe_rng, 8.0, 3.0)
        if self.idmz_access_profile == "lockdown":
            # over-restrictive policy denies legitimate probes (availability cost)
            return {"ok": False, "latency_ms": round(latency, 2), "sla_ms": self.probe_sla_ms}
        return {"ok": latency <= self.probe_sla_ms,
                "latency_ms": round(latency, 2), "sla_ms": self.probe_sla_ms}

    # --- request handling (used by the full HTTP path and integration tests)
    def handle_request(self, req: dict, sink) -> str:
        protocol = req.get("protocol", "P1")
        role = req.get("role", "operator")
        channel = req.get("channel", "local")
        strict = self.idmz_access_profile in ("strict", "lockdown")

        if protocol not in self.protocol_whitelist:
            sink.emit(COMPONENT, "non_whitelisted_protocol_violation", "high",
                      "violation", ZONE, {"protocol": protocol})
            return "denied"
        if channel == "remote" and strict and role != "admin":
            sink.emit(COMPONENT, "policy_violation_remote_access", "high",
                      "violation", ZONE, {"role": role})
            return "denied"
        sink.emit(COMPONENT, "gateway_request_allowed", "low", "normal", ZONE,
                  {"protocol": protocol, "role": role})
        return "allowed"
