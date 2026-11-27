"""Scenario catalog.

The canonical scenario artifacts are the YAML files in configs/scenarios/. These
built-in dicts mirror them so the simulation and evaluator run with nothing but
the Python standard library (no PyYAML), exactly like scripts/demo_local.py.

`load(scenario_id)` prefers the YAML file when PyYAML is importable and falls
back to the built-in copy otherwise. tests/unit/test_scenarios.py asserts the
two stay in sync when PyYAML is available, so this is not a silent fork.
"""
from __future__ import annotations

import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SCENARIOS: dict[str, dict] = {
    "SC-01": {
        "id": "SC-01", "seed": 1001,
        "description": "Non-whitelisted inter-zone protocol crossing at the IDMZ boundary",
        "initial_conditions": {"idmz_profile": "standard", "policy": "baseline-v1"},
        "event_sequence": [
            {"t": 0, "target": "idmz-gateway", "action": "set_mode", "value": "normal"},
            {"t": 30, "target": "idmz-gateway", "action": "inject",
             "value": "inter_zone_protocol_anomaly", "duration": 20},
        ],
        "ground_truth": [
            {"label": "inter_zone_protocol_anomaly", "window": [30, 50],
             "expected_detection": True, "detection_type": "presence",
             "component": "idmz-gateway", "event_type": "inter_zone_protocol_anomaly"},
        ],
        "evaluation_window": {"start": 0, "end": 120},
        "reset_procedure": ["restore_modes", "restore_policy_baseline",
                            "flush_state", "new_experiment_id"],
    },
    "SC-02": {
        "id": "SC-02", "seed": 1002,
        "description": "Broadcast/multicast packet storm raises the boundary drop-rate",
        "initial_conditions": {"policy": "baseline-v1", "boundary_rate_limit": 50},
        "event_sequence": [
            {"t": 0, "target": "boundary-firewall", "action": "set_mode", "value": "normal"},
            {"t": 40, "target": "boundary-firewall", "action": "inject",
             "value": "packet_storm", "duration": 15},
        ],
        "ground_truth": [
            {"label": "packet_storm", "window": [40, 55], "expected_detection": True,
             "detection_type": "presence", "component": "boundary-firewall",
             "event_type": "packet_storm_volume", "expected_severity": "high"},
        ],
        "evaluation_window": {"start": 0, "end": 120},
        "reset_procedure": ["restore_modes", "restore_policy_baseline",
                            "flush_state", "new_experiment_id"],
    },
    "SC-03": {
        "id": "SC-03", "seed": 1003,
        "description": "Privilege escalation — privileged command executed on the eng station",
        "initial_conditions": {"policy": "baseline-v1", "idmz_profile": "standard"},
        "event_sequence": [
            {"t": 0, "target": "eng-station", "action": "set_mode", "value": "normal"},
            {"t": 50, "target": "eng-station", "action": "inject",
             "value": "privileged_command", "duration": 1},
        ],
        "ground_truth": [
            {"label": "privileged_command_exec", "window": [50, 51],
             "expected_detection": True, "detection_type": "presence",
             "component": "eng-station", "event_type": "privileged_command_exec",
             "contain_expected": False},
        ],
        "evaluation_window": {"start": 0, "end": 120},
        "reset_procedure": ["restore_modes", "restore_policy_baseline",
                            "flush_state", "new_experiment_id"],
    },
    "SC-04": {
        "id": "SC-04", "seed": 1004,
        "description": "Zone-segmentation violation — jump-host crossing to a control dest",
        "initial_conditions": {"policy": "baseline-v1", "idmz_profile": "standard"},
        "event_sequence": [
            {"t": 0, "target": "idmz-gateway", "action": "set_mode", "value": "normal"},
            {"t": 35, "target": "idmz-gateway", "action": "inject",
             "value": "jump_host_crossing", "duration": 10},
        ],
        "ground_truth": [
            {"label": "idmz_jump_host_crossing", "window": [35, 45],
             "expected_detection": True, "detection_type": "presence",
             "component": "idmz-gateway", "event_type": "idmz_jump_host_crossing",
             "contain_expected": False},
        ],
        "probes": {"interval": 10, "sla_ms": 50, "targets": ["idmz-gateway"]},
        "evaluation_window": {"start": 0, "end": 120},
        "reset_procedure": ["restore_modes", "restore_policy_baseline",
                            "flush_state", "new_experiment_id"],
    },
    "SC-05": {
        "id": "SC-05", "seed": 1005,
        "description": "Missing audit — a required security-audit log is omitted from the stream",
        "initial_conditions": {"policy": "baseline-v1"},
        "event_sequence": [
            {"t": 0, "target": "eng-station", "action": "set_mode", "value": "normal"},
            {"t": 40, "target": "eng-station", "action": "inject",
             "value": "audit_log_gap", "duration": 30},
        ],
        "ground_truth": [
            {"label": "security_audit_log_gap", "window": [40, 70],
             "expected_detection": True, "detection_type": "absence",
             "component": "eng-station", "event_type": "security_audit_log",
             "cadence": 1, "timeout": 5},
        ],
        "evaluation_window": {"start": 0, "end": 120},
        "reset_procedure": ["restore_modes", "restore_policy_baseline",
                            "flush_state", "new_experiment_id"],
    },
    "SC-06": {
        "id": "SC-06", "seed": 1006,
        "description": "Remote/unauthenticated access outside the allowed channel and window",
        "initial_conditions": {"policy": "baseline-v1", "idmz_profile": "standard"},
        "event_sequence": [
            {"t": 0, "target": "idmz-gateway", "action": "set_mode", "value": "normal"},
            {"t": 45, "target": "idmz-gateway", "action": "inject",
             "value": "unauthenticated_access", "duration": 8},
        ],
        "ground_truth": [
            {"label": "unauthenticated_access_attempt", "window": [45, 53],
             "expected_detection": True, "detection_type": "presence",
             "component": "idmz-gateway", "event_type": "unauthenticated_access_attempt",
             "contain_expected": False},
        ],
        "probes": {"interval": 10, "sla_ms": 50, "targets": ["idmz-gateway"]},
        "evaluation_window": {"start": 0, "end": 120},
        "reset_procedure": ["restore_modes", "restore_policy_baseline",
                            "flush_state", "new_experiment_id"],
    },
    "SC-07": {
        "id": "SC-07", "seed": 1007,
        "description": "Data-diode forwarding heartbeat pause (coverage gap), then recovery",
        "initial_conditions": {"policy": "baseline-v1", "recovery_timeout": 60},
        "event_sequence": [
            {"t": 0, "target": "telemetry-forwarder", "action": "set_mode", "value": "normal"},
            {"t": 40, "target": "telemetry-forwarder", "action": "inject",
             "value": "heartbeat_pause", "duration": 20},
        ],
        "ground_truth": [
            {"label": "forwarding_heartbeat_gap", "window": [40, 60],
             "expected_detection": True, "detection_type": "absence",
             "component": "telemetry-forwarder", "event_type": "diode_forwarding_health",
             "cadence": 1, "timeout": 5, "measure_recovery": True},
        ],
        "probes": {"interval": 10, "sla_ms": 50, "targets": ["telemetry-forwarder"]},
        "evaluation_window": {"start": 0, "end": 120},
        "reset_procedure": ["restore_modes", "restore_policy_baseline",
                            "flush_state", "new_experiment_id"],
    },
}

SCENARIO_IDS = sorted(SCENARIOS)


def load(scenario_id: str) -> dict:
    """Prefer the canonical YAML; fall back to the built-in copy (no PyYAML)."""
    path = os.path.join(ROOT, "configs", "scenarios", f"{scenario_id}.yaml")
    try:
        import yaml  # type: ignore
        with open(path) as fh:
            return yaml.safe_load(fh)
    except Exception:
        if scenario_id not in SCENARIOS:
            raise
        return SCENARIOS[scenario_id]
