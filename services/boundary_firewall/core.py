"""Boundary-protection firewall (zone: idmz).

Enforces the protocol whitelist and rate limits; emits drop-rate, packet-storm,
MAC-spoofing and port-profile signals. SC-02 drives this component (a
broadcast/multicast packet storm that raises the boundary drop-rate).

The rate limit is a defensive-policy lever: a low enough limit throttles the
storm before effect (``contained``), a loose one does not.
"""
from __future__ import annotations

from research.common.sim import gauss_nonneg, rng_for

COMPONENT = "boundary-firewall"
ZONE = "idmz"

_NEAR_MISS_PERIOD = 11
_NEAR_MISS_BUMP = 0.10
_STORM_BUMP = 0.35
_STORM_PPS = 85000
# the storm is contained if the rate limit is tight enough to throttle it
_CONTAIN_RATE_LIMIT = 60


class BoundaryFirewall:
    def __init__(self, seed: int, config: dict | None = None):
        config = config or {}
        self.rng = rng_for(seed, offset=1)
        self.mode = "normal"
        self.drop_baseline = float(config.get("drop_baseline", 0.02))
        self.rate_limit = int(config.get("boundary_rate_limit", 50))

    def set_mode(self, mode: str) -> None:
        self.mode = mode

    def apply_policy(self, policy: dict) -> None:
        if "boundary_rate_limit" in policy:
            self.rate_limit = int(policy["boundary_rate_limit"])

    def state(self) -> dict:
        return {"component": COMPONENT, "mode": self.mode, "healthy": True}

    def tick(self, t: int, sink) -> None:
        drop = gauss_nonneg(self.rng, self.drop_baseline, 0.006)
        if self.mode == "packet_storm":
            contained = self.rate_limit <= _CONTAIN_RATE_LIMIT
            sink.emit(COMPONENT, "packet_storm_volume", "high", "anomalous", ZONE,
                      {"pps": _STORM_PPS, "drop_rate": round(drop + _STORM_BUMP, 4),
                       "rate_limit": self.rate_limit, "contained": contained})
            sink.emit(COMPONENT, "boundary_drop_rate", "high", "anomalous", ZONE,
                      {"drop_rate": round(drop + _STORM_BUMP, 4), "rate_limit": self.rate_limit})
        elif self.mode == "mac_spoofing":
            sink.emit(COMPONENT, "mac_spoofing_detected", "high", "violation", ZONE,
                      {"mac": "de:ad:be:ef:00:01", "port": "Gi0/3"})
        else:
            near = t > 0 and t % _NEAR_MISS_PERIOD == 0
            dr = drop + (_NEAR_MISS_BUMP if near else 0.0)
            sink.emit(COMPONENT, "fw_heartbeat", "low", "normal", ZONE,
                      {"drop_rate": round(dr, 4), "near_miss": near})
