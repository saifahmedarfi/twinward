#!/usr/bin/env python3
"""Zero-dependency local runner for the evaluation engine (Phase 5, fast mode).

Runs one scenario in simulated time and scores it with the log-only evaluator,
printing the result document (all reward components reported separately).

    python3 scripts/evaluate_local.py SC-04
    python3 scripts/evaluate_local.py SC-07 --json
    python3 scripts/evaluate_local.py all          # score the whole suite

Uses only the Python standard library, like scripts/demo_local.py. This is the
fast-mode path that drives the large policy sweeps in later phases; the
Wazuh-in-the-loop path reuses the same metric and reward code.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from research.evaluation.engine import evaluate
from research.scenario_controller.catalog import SCENARIO_IDS, load
from research.scenario_controller.controller import run_scenario


def score(scenario_id: str) -> dict:
    scenario = load(scenario_id)
    result = run_scenario(scenario, estate_cfg={}, stream=False)
    return evaluate(result, scenario)


def _print_human(doc: dict) -> None:
    rc = doc["reward_components"]
    c = doc["counts"]
    print(f"\n=== {doc['scenario_id']}  ({doc['experiment_id']}) ===")
    print(f"  reward R        : {doc['reward']:.4f}")
    print(f"  D={rc['D']:.3f} C={rc['C']:.3f} A={rc['A']:.3f} "
          f"Q={rc['Q']:.3f} F={rc['F']:.3f} L={rc['L']:.3f}")
    print(f"  TP={c['TP']} FP={c['FP']} FN={c['FN']} G={c['G']} B={c['B']} "
          f"alerts={c['alerts']} probes={c['probes']}(ok {c['probe_ok']})")
    if doc["coverage"]:
        for cov in doc["coverage"]:
            print(f"  coverage[{cov['label']}]: detected={cov['detected']} "
                  f"gap={cov['gap_len_s']}s @t={cov['gap_start']}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", nargs="?", default="all",
                    help="scenario id (e.g. SC-04) or 'all'")
    ap.add_argument("--json", action="store_true", help="emit the raw result document(s)")
    args = ap.parse_args()

    ids = SCENARIO_IDS if args.scenario == "all" else [args.scenario.upper()]
    docs = [score(sid) for sid in ids]

    if args.json:
        print(json.dumps(docs if len(docs) > 1 else docs[0], indent=2))
    else:
        for doc in docs:
            _print_human(doc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
