"""Field-network / PLC edge (zone: field).

Emits field-device signals: firmware integrity, SIS mode, WDT heartbeats,
I/O-boundary violations, unused-port activation, reboot/uptime. SC-01's
telemetry source and the basis for optional firmware-integrity scenarios.
"""
from __future__ import annotations

from research.common.sim import rng_for

COMPONENT = "plc-edge"
ZONE = "field"


class PlcEdge:
    def __init__(self, seed: int, config: dict | None = None):
        config = config or {}
        self.rng = rng_for(seed, offset=3)
        self.mode = "normal"
        self.uptime_s = 0
        self.firmware_checksum = config.get("firmware_checksum", "sha256:baseline")

    def set_mode(self, mode: str) -> None:
        self.mode = mode

    def apply_policy(self, policy: dict) -> None:  # no tunable params in v1
        return

    def state(self) -> dict:
        return {"component": COMPONENT, "mode": self.mode, "healthy": self.mode == "normal"}

    def tick(self, t: int, sink) -> None:
        self.uptime_s += 1
        # WDT heartbeat every tick (used for heartbeat-gap detection)
        sink.emit(COMPONENT, "wdt_heartbeat", "low", "normal", ZONE,
                  {"uptime_s": self.uptime_s})
        if self.mode == "firmware_tamper":
            sink.emit(COMPONENT, "plc_firmware_integrity_fail", "critical", "violation",
                      ZONE, {"expected": self.firmware_checksum, "observed": "sha256:tampered"})
        elif self.mode == "io_violation":
            sink.emit(COMPONENT, "io_boundary_violation", "high", "violation", ZONE,
                      {"point": "DI-07", "command": "force_on"})
        elif self.mode == "unused_port":
            sink.emit(COMPONENT, "unused_port_activation", "medium", "anomalous", ZONE,
                      {"port": 502})
        else:
            sink.emit(COMPONENT, "plc_firmware_integrity_ok", "low", "normal", ZONE,
                      {"checksum": self.firmware_checksum})
