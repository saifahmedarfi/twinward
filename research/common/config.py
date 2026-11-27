"""Load the estate and reward configuration files (implementation plan T1).

Before this module existed, ``configs/estate/estate-config.yaml`` and
``configs/evaluation/reward.yaml`` were never opened: every run used each
component's built-in defaults and the evaluator's DEFAULT_WEIGHTS. These loaders
make both files authoritative. PyYAML is optional: without it the loaders fall
back to the same defaults the code always used, so the stdlib-only path still runs.
"""
from __future__ import annotations

import copy
import os
from typing import Any

from research.evaluation.metrics import DEFAULT_WEIGHTS

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ESTATE_PATH = os.path.join(ROOT, "configs", "estate", "estate-config.yaml")
REWARD_PATH = os.path.join(ROOT, "configs", "evaluation", "reward.yaml")

# Policy levers the twin exposes, with the baseline value of each. The baseline
# is what `restore_policy_baseline` returns the estate to between runs.
BASELINE_POLICY: dict[str, Any] = {
    "alert_threshold": 3.0,
    "idmz_access_profile": "standard",
    "boundary_rate_limit": 50,
    "recovery_timeout": 60,
}

# which estate-config section(s) each policy lever lives in
_POLICY_SECTIONS = {
    "alert_threshold": ["idmz_gateway"],
    "idmz_access_profile": ["idmz_gateway", "eng_station"],
    "boundary_rate_limit": ["boundary_firewall"],
    "recovery_timeout": ["telemetry_forwarder"],
}


def _read_yaml(path: str) -> dict | None:
    try:
        import yaml  # type: ignore
    except ImportError:
        return None
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        return yaml.safe_load(fh) or {}


def load_estate(path: str = ESTATE_PATH) -> dict:
    """Return the estate config dict ({} when PyYAML or the file is missing)."""
    return _read_yaml(path) or {}


def load_weights(path: str = REWARD_PATH) -> dict:
    """Return reward weights from reward.yaml, filling any gap from the defaults."""
    doc = _read_yaml(path) or {}
    w = dict(DEFAULT_WEIGHTS)
    for k in DEFAULT_WEIGHTS:
        if k in doc:
            w[k] = float(doc[k])
    return w


def baseline_policy(estate: dict | None = None) -> dict:
    """The baseline policy, as declared by the estate config (or built-in)."""
    estate = estate or {}
    pol = dict(BASELINE_POLICY)
    for lever, sections in _POLICY_SECTIONS.items():
        for sec in sections:
            val = (estate.get(sec) or {}).get(lever)
            if val is not None:
                pol[lever] = val
                break
    return pol


def merge_policy(estate: dict, policy: dict | None) -> dict:
    """Return a copy of the estate config with `policy` levers written into the
    right component sections, so components boot with the policy applied."""
    out = copy.deepcopy(estate)
    for lever, value in (policy or {}).items():
        for sec in _POLICY_SECTIONS.get(lever, []):
            out.setdefault(sec, {})
            if out[sec] is None:
                out[sec] = {}
            out[sec][lever] = value
    return out
