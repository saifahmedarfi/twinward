#!/usr/bin/env python3
"""Regenerate viz/demo_data.json — the offline dataset for the visualization.

Runs every scenario SC-01..SC-07 under the baseline policy and bakes the real
event stream + reward document into a single JSON file, so viz/index.html can
replay a true simulation with no backend running (e.g. under VS Code Live
Server). The live backend (scripts/viz_server.py) produces the same shape per
tick over SSE. Stdlib-only, like the rest of the local path.

    python3 scripts/make_viz_data.py
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from research.evaluation.engine import _t_of, evaluate
from research.scenario_controller.catalog import SCENARIO_IDS, load
from research.scenario_controller.controller import COMPONENT_ZONE, run_scenario

COMPONENTS = ["idmz-gateway", "boundary-firewall", "plc-edge",
              "eng-station", "telemetry-forwarder"]


def pack(e: dict) -> dict:
    return {
        "t": _t_of(e), "ts": e["timestamp"], "id": e["event_id"][:12],
        "component": e["component"], "event_type": e["event_type"],
        "severity": e["severity"], "state": e["simulated_state"],
        "zone": e["zone"], "details": e.get("details") or {},
    }


def main() -> None:
    out = {"generated": True, "components": COMPONENTS, "zones": COMPONENT_ZONE,
           "scenarios": []}
    for sid in SCENARIO_IDS:
        sc = load(sid)
        run = run_scenario(sc, estate_cfg={}, stream=False)
        doc = evaluate(run, sc)
        out["scenarios"].append({
            "id": sid, "description": sc.get("description", ""),
            "seed": sc["seed"], "window": sc["evaluation_window"],
            "ground_truth": [
                {"label": g["label"], "window": g["window"],
                 "detection_type": g.get("detection_type", "presence"),
                 "component": g.get("component"), "event_type": g.get("event_type")}
                for g in sc["ground_truth"]
            ],
            "experiment_id": run["experiment_id"],
            "events": [pack(e) for e in run["events"]],
            "reward": doc,
        })

    dest = os.path.join(ROOT, "viz", "demo_data.json")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w") as fh:
        json.dump(out, fh, separators=(",", ":"))

    print(f"wrote {dest}  ({os.path.getsize(dest)} bytes)")
    for s in out["scenarios"]:
        print(f"  {s['id']}: {len(s['events'])} events, R={s['reward']['reward']:.4f}")


if __name__ == "__main__":
    main()
