"""Engineering workstation host (zone: supervisory).

Emits supervisory signals: configuration drift, privileged command execution,
TCA compliance, transient-media payload signatures, SBOM vuln matches, HSM
revocation, and a periodic security-audit log. SC-03 (privilege escalation)
and SC-05 (a required audit event intentionally omitted) touch this component.

In normal operation the host emits BOTH a compliance status and a periodic
``security_audit_log``. The ``audit_log_gap`` mode keeps the host alive and
still reporting compliance, but stops emitting the required audit event: that
missing stream is the positive in SC-05 (absence detection, Option b).
"""
from __future__ import annotations

from research.common.sim import rng_for

COMPONENT = "eng-station"
ZONE = "supervisory"

_CONTAINING_PROFILES = {"strict", "lockdown"}


class EngStation:
    def __init__(self, seed: int, config: dict | None = None):
        config = config or {}
        self.rng = rng_for(seed, offset=4)
        self.mode = "normal"
        # host honours the estate-wide access posture for least-privilege enforcement
        self.access_profile = config.get("idmz_access_profile", "standard")

    def set_mode(self, mode: str) -> None:
        self.mode = mode

    def apply_policy(self, policy: dict) -> None:
        if "idmz_access_profile" in policy:
            self.access_profile = policy["idmz_access_profile"]

    def state(self) -> dict:
        return {"component": COMPONENT, "mode": self.mode, "healthy": self.mode == "normal"}

    @property
    def _contained(self) -> bool:
        return self.access_profile in _CONTAINING_PROFILES

    def tick(self, t: int, sink) -> None:
        if self.mode == "privileged_command":
            sink.emit(COMPONENT, "privileged_command_exec", "high", "violation", ZONE,
                      {"identity": "svc-ops", "role": "operator", "command": "write_config",
                       "contained": self._contained})
        elif self.mode == "config_drift":
            sink.emit(COMPONENT, "config_drift", "medium", "anomalous", ZONE,
                      {"baseline": "gold-v1", "delta_keys": 3})
        elif self.mode == "malicious_media":
            sink.emit(COMPONENT, "transient_media_payload_signature", "critical", "violation",
                      ZONE, {"device": "usb-1", "signature": "EICAR-TEST"})
        elif self.mode == "sbom_vuln":
            sink.emit(COMPONENT, "sbom_vuln_match", "high", "anomalous", ZONE,
                      {"package": "libexample", "cve": "CVE-0000-0000"})
        elif self.mode == "hsm_revoked":
            sink.emit(COMPONENT, "hsm_revocation_status", "high", "fault", ZONE,
                      {"key_id": "sign-01", "status": "revoked"})
        elif self.mode == "audit_log_gap":
            # host stays alive and compliant, but the required audit event is omitted
            sink.emit(COMPONENT, "tca_compliance_status", "low", "normal", ZONE,
                      {"compliant": True})
        else:
            sink.emit(COMPONENT, "tca_compliance_status", "low", "normal", ZONE,
                      {"compliant": True})
            # required periodic audit event; its absence is what SC-05 detects
            sink.emit(COMPONENT, "security_audit_log", "low", "normal", ZONE,
                      {"source": "access-badge", "records": 1})
