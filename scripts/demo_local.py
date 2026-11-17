#!/usr/bin/env python3
"""Zero-dependency local demo of the ProPS-Twin simulation.

Runs scenario SC-01 entirely in-process, in simulated time, using only the
Python standard library. It prints the JSON event stream, writes events and
ground truth to results/demo.sqlite, and prints a short summary.

    python3 scripts/demo_local.py              # SC-01, prints events
    python3 scripts/demo_local.py --quiet       # only the summary

This exercises the simulation core without Docker, Kubernetes, Wazuh or an LLM
(those arrive in Phases 4 and 6). It is the fastest way to see events flow.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from research.scenario_controller.controller import run_scenario

# Built-in SC-01 so the demo runs even without PyYAML installed.
SC01 = {
    "id": "SC-01",
    "seed": 1001,
    "initial_conditions": {"policy": "baseline-v1"},
    "event_sequence": [
        {"t": 0, "target": "idmz-gateway", "action": "set_mode", "value": "normal"},
        {"t": 30, "target": "idmz-gateway", "action": "inject",
         "value": "inter_zone_protocol_anomaly", "duration": 20},
    ],
    "ground_truth": [
        {"label": "inter_zone_protocol_anomaly", "window": [30, 50],
         "expected_detection": True},
    ],
    "evaluation_window": {"start": 0, "end": 60},
    "reset_procedure": ["restore_modes", "restore_policy_baseline"],
}


def load_sc01() -> dict:
    """Prefer the canonical YAML if PyYAML is available; else the builtin copy."""
    path = os.path.join(ROOT, "configs", "scenarios", "SC-01.yaml")
    try:
        import yaml  # type: ignore
        with open(path) as fh:
            return yaml.safe_load(fh)
    except Exception:  # noqa: BLE001 - any load failure falls back to the builtin copy
        return SC01


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true", help="suppress the event stream")
    args = ap.parse_args()

    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    db = os.path.join(ROOT, "results", "demo.sqlite")
    if os.path.exists(db):
        os.remove(db)

    stream = False if args.quiet else sys.stdout
    result = run_scenario(load_sc01(), estate_cfg={}, stream=stream, db_path=db)

    events = result["events"]
    anomalies = [e for e in events if e["event_type"] == "inter_zone_protocol_anomaly"]
    con = sqlite3.connect(db)
    n_events = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    n_gt = con.execute("SELECT COUNT(*) FROM ground_truth").fetchone()[0]
    con.close()

    print("\n--- SC-01 summary -------------------------------------------")
    print(f"experiment_id      : {result['experiment_id']}")
    print(f"total events        : {len(events)} (persisted: {n_events})")
    print(f"anomaly events      : {len(anomalies)}  (expected in window [30,50])")
    print(f"ground-truth rows   : {n_gt}")
    print(f"sqlite              : {db}")
    print("Next: same seed -> identical event_ids. Try running twice and diff.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
