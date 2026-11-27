#!/usr/bin/env python3
"""ProPS-Twin — primary execution file.

    python main.py phase3                 # the whole Phase 3 run + report (default)
    python main.py run SC-04              # one experiment (ledger + logs + traces + metrics)
    python main.py run SC-04 --policy idmz_access_profile=strict
    python main.py run SC-02 --preset strict-v1
    python main.py suite --repeat 3       # SC-01..SC-07 under the baseline policy
    python main.py reset all              # Step 3.4: run -> reset -> re-run checks
    python main.py ledger                 # recent experiments in the ledger
    python main.py status                 # probe the live docker-compose stack

Environment (all optional — without them everything runs locally):
    PROPS_DB_URL                  postgresql://...  (default: SQLite results/ledger.sqlite)
    OTEL_EXPORTER_OTLP_ENDPOINT   http://127.0.0.1:4318   (OTel Collector, OTLP/HTTP)
    PROM_PUSHGATEWAY              127.0.0.1:9091          (Prometheus Pushgateway)
    PROPS_PROMETHEUS_URL          http://127.0.0.1:9090   (used by `status` / phase3)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.request
from urllib.parse import urlsplit, urlunsplit

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from research.ledger.store import Ledger
from research.scenario_controller.catalog import SCENARIO_IDS
from research.scenario_controller.runner import RESULTS, ExperimentRunner
from research.telemetry.otel import Telemetry
from research.telemetry.prom import RunMetrics

PRESET_DIR = os.path.join(ROOT, "configs", "policies")
PHASE3_DIR = os.path.join(RESULTS, "phase3")
PRESETS = ["baseline-v1", "strict-v1", "lockdown-v1", "sensitive-v1"]

# proposal Table 1 -> scenario mapping
PROPOSAL_TABLE1 = {
    "SC-01": "Segmentation misconfiguration (non-whitelisted protocol)",
    "SC-02": "Segmentation / boundary (packet storm)",
    "SC-03": "Excessive privileges",
    "SC-04": "Segmentation misconfiguration (jump-host crossing)",
    "SC-05": "Incomplete logging",
    "SC-06": "Remote-access policy failure",
    "SC-07": "Monitoring / service outage",
}

SERVICES = {"idmz-gateway": 8001, "boundary-firewall": 8002, "plc-edge": 8003,
            "eng-station": 8004, "telemetry-forwarder": 8005}


# --- helpers ----------------------------------------------------------------
def load_preset(name: str) -> dict:
    import yaml  # type: ignore
    with open(os.path.join(PRESET_DIR, f"{name}.yaml")) as fh:
        return yaml.safe_load(fh)


def parse_policy(pairs: list[str] | None) -> dict:
    out: dict = {}
    for p in pairs or []:
        k, _, v = p.partition("=")
        if not _:
            raise SystemExit(f"--policy expects key=value, got {p!r}")
        try:
            out[k] = json.loads(v)
        except json.JSONDecodeError:
            out[k] = v
    return out


def mask_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.password:
        netloc = parts.netloc.replace(f":{parts.password}@", ":***@")
        return urlunsplit(parts._replace(netloc=netloc))
    return url


def make_runner(stream=False) -> ExperimentRunner:
    return ExperimentRunner(
        ledger=Ledger(),
        telemetry=Telemetry(evidence_dir=os.path.join(RESULTS, "otel")),
        metrics=RunMetrics(),
        stream=stream,
    )


def finish_exports(runner: ExperimentRunner) -> dict:
    prom_path = runner.metrics.write_textfile(os.path.join(RESULTS, "metrics", "props_twin.prom"))
    pushed = runner.metrics.push(os.environ.get("PROM_PUSHGATEWAY"))
    return {"prometheus_textfile": prom_path, "pushgateway": pushed,
            "otlp_endpoint": runner.telemetry.endpoint,
            "otel_evidence": os.path.join(RESULTS, "otel"),
            "ledger": mask_url(runner.ledger.url)}


def http_json(url: str, timeout: float = 3.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def fmt_row(rec: dict) -> str:
    rc = rec["reward_components"]
    c = rec["counts"]
    m = rec["metrics"]
    return (f"{rec['scenario_id']:6} {rec['policy_version']:13} R={rec['reward']:.4f}  "
            f"D={rc['D']:.2f} C={rc['C']:.2f} A={rc['A']:.2f} Q={rc['Q']:.2f} "
            f"F={rc['F']:.3f} L={rc['L']:.3f}  TP={c['TP']} FP={c['FP']} FN={c['FN']}  "
            f"blocked={m['blocked_flow_count']} prohibited={m['prohibited_flow_count']}  "
            f"retained={m['retained_events']}/{rec['n_events']}")


# --- commands ---------------------------------------------------------------
def cmd_run(args) -> int:
    policy = load_preset(args.preset) if args.preset else {}
    policy.update(parse_policy(args.policy))
    runner = make_runner(stream=sys.stdout if args.events else False)
    try:
        for _ in range(args.repeat):
            rec = runner.run(args.scenario.upper(), policy or None)
            if args.json:
                print(json.dumps(rec, indent=2, default=str))
            else:
                print(fmt_row(rec))
                print(f"   experiment={rec['experiment_id']} trace={rec['trace_id']} "
                      f"log={os.path.relpath(rec['log_path'], ROOT)}")
        exports = finish_exports(runner)
    finally:
        runner.close()
    if not args.json:
        print(json.dumps(exports, indent=2))
    return 0


def cmd_suite(args) -> int:
    runner = make_runner()
    try:
        recs = [runner.run(sid, None) for _ in range(args.repeat) for sid in SCENARIO_IDS]
        for r in recs:
            print(fmt_row(r))
        print(json.dumps(finish_exports(runner), indent=2))
    finally:
        runner.close()
    return 0


def cmd_reset(args) -> int:
    runner = make_runner()
    ids = SCENARIO_IDS if args.scenario == "all" else [args.scenario.upper()]
    ok = True
    try:
        for sid in ids:
            rep = runner.run_reset_cycle(sid)
            good = (rep["payload_identical"] and rep["fresh_experiment_id"]
                    and rep["all_normal_after_reset"])
            ok &= good
            print(f"{sid}: {'PASS' if good else 'FAIL'}  {rep['first_experiment']} -> "
                  f"{rep['second_experiment']}  steps={rep['steps']}  "
                  f"identical_after_reset={rep['payload_identical']}  "
                  f"identical_without_reset={rep['payload_identical_without_reset']}")
    finally:
        runner.close()
    return 0 if ok else 1


def cmd_ledger(args) -> int:
    led = Ledger()
    st = led.stats()
    st["url"] = mask_url(st["url"])
    print(json.dumps(st, indent=2))
    for r in led.experiments(args.limit):
        print(f"{r['created_at']}  {r['experiment_id']:24} {r['status']:9} "
              f"{r['policy_version'] or '':13} R={r['reward'] if r['reward'] is not None else '-'}"
              f"  events={r['n_events']} persisted={r['n_persisted']} trace={r['trace_id']}")
    led.close()
    return 0


def live_stack_status() -> dict:
    """Probe the docker-compose stack. Every field is None/False when it is down."""
    out: dict = {"services": {}, "prometheus": None, "collector": None}
    for name, port in SERVICES.items():
        try:
            st = http_json(f"http://127.0.0.1:{port}/state")
            out["services"][name] = {"up": True, "mode": st["mode"], "t": st["t"],
                                     "healthy": st["healthy"]}
        except Exception:  # noqa: BLE001
            out["services"][name] = {"up": False}
    prom = os.environ.get("PROPS_PROMETHEUS_URL", "http://127.0.0.1:9090")
    try:
        tg = http_json(f"{prom}/api/v1/targets")
        out["prometheus"] = {
            "targets": [{"job": t["labels"]["job"], "instance": t["labels"]["instance"],
                         "health": t["health"]} for t in tg["data"]["activeTargets"]]}
        q = {
            "service_events_total": "sum(props_service_events_total)",
            "runner_reward_series": "count(props_reward)",
            "collector_log_records_accepted": "sum(otelcol_receiver_accepted_log_records)",
            "collector_spans_accepted": "sum(otelcol_receiver_accepted_spans)",
        }
        vals = {}
        for k, expr in q.items():
            res = http_json(f"{prom}/api/v1/query?query={urllib.request.quote(expr)}")
            r = res["data"]["result"]
            vals[k] = float(r[0]["value"][1]) if r else None
        out["prometheus"]["queries"] = vals
    except Exception:  # noqa: BLE001, S110 - prometheus down -> reported as None
        pass
    coll = os.path.join(RESULTS, "collector")
    if os.path.isdir(coll):
        out["collector"] = {}
        for f in sorted(os.listdir(coll)):
            if f.endswith(".jsonl"):
                with open(os.path.join(coll, f)) as fh:
                    out["collector"][f] = sum(1 for _ in fh)
    return out


def cmd_status(_args) -> int:
    print(json.dumps(live_stack_status(), indent=2))
    return 0


def cmd_phase3(args) -> int:
    """Everything Phase 3 asks for, end to end, with a written report."""
    os.makedirs(PHASE3_DIR, exist_ok=True)
    t0 = time.perf_counter()
    runner = make_runner()
    report: dict = {"generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
                    "code_version": runner.code_version,
                    "ledger_backend": runner.ledger.backend,
                    "weights": runner.weights}
    try:
        # 1. baseline suite, repeated: reproducibility across repeats
        print("== 1. Baseline suite (SC-01..SC-07) x", args.repeat)
        base = [runner.run(sid, None) for _ in range(args.repeat) for sid in SCENARIO_IDS]
        for r in base[: len(SCENARIO_IDS)]:
            print("  " + fmt_row(r))
        repro = {}
        for sid in SCENARIO_IDS:
            rs = [r for r in base if r["scenario_id"] == sid]
            repro[sid] = {"runs": len(rs), "rewards": sorted({round(r["reward"], 6) for r in rs}),
                          "identical_reward": len({round(r["reward"], 9) for r in rs}) == 1}
        print("  reward identical across repeats:",
              all(v["identical_reward"] for v in repro.values()))

        # 2. reset path
        print("== 2. Reset path (Step 3.4): run -> reset -> re-run")
        resets = {}
        for sid in SCENARIO_IDS:
            rep = runner.run_reset_cycle(sid)
            resets[sid] = {k: rep[k] for k in (
                "first_experiment", "second_experiment", "steps", "all_normal_after_reset",
                "payload_identical", "payload_identical_without_reset", "fresh_experiment_id")}
            print(f"  {sid}: identical_after_reset={rep['payload_identical']} "
                  f"identical_without_reset={rep['payload_identical_without_reset']} "
                  f"fresh_id={rep['fresh_experiment_id']}")

        # 3. policy-lever check (risk propagation, RQ1): fixed presets
        print("== 3. Policy presets x scenarios (lever check, RQ1)")
        presets = {name: load_preset(name) for name in PRESETS}
        lever = []
        for sid in SCENARIO_IDS:
            for pol in presets.values():
                rec = runner.run(sid, pol)
                lever.append(rec)
                print("  " + fmt_row(rec))

        exports = finish_exports(runner)
    finally:
        runner.close()

    # 4. live stack (if running)
    live = live_stack_status()

    def slim(r: dict) -> dict:
        return {k: r[k] for k in ("experiment_id", "scenario_id", "policy_version", "reward",
                                  "reward_components", "metrics", "counts", "n_events",
                                  "trace_id", "event_ids_sha256", "duration_s")}

    led = Ledger()
    stats = led.stats()
    stats["url"] = mask_url(stats["url"])
    led.close()
    report.update({
        "baseline": [slim(r) for r in base[: len(SCENARIO_IDS)]],
        "reproducibility": repro, "reset": resets,
        "policy_presets": presets,
        "lever_check": [slim(r) for r in lever],
        "exports": exports, "ledger": stats, "live_stack": live,
        "wall_time_s": round(time.perf_counter() - t0, 2),
    })
    with open(os.path.join(PHASE3_DIR, "report.json"), "w") as fh:
        json.dump(report, fh, indent=2, default=str)
    with open(os.path.join(PHASE3_DIR, "report.md"), "w") as fh:
        fh.write(render_markdown(report))
    print("== 4. Exports")
    print(json.dumps(exports, indent=2))
    print("== 5. Live stack")
    up = sum(1 for s in live["services"].values() if s["up"])
    print(f"  services up: {up}/5   prometheus: {'up' if live['prometheus'] else 'down'}   "
          f"collector files: {live['collector']}")
    print(f"\nreport: {os.path.relpath(os.path.join(PHASE3_DIR, 'report.md'), ROOT)}  "
          f"(+ report.json)   wall time {report['wall_time_s']}s")
    return 0


def render_markdown(rep: dict) -> str:
    L: list[str] = []
    w = L.append
    w("# ProPS-Twin — Phase 3 results (scenarios + telemetry)\n")
    w(f"Generated {rep['generated_at']} · code `{rep['code_version']}` · "
      f"ledger `{rep['ledger']['backend']}` · wall time {rep['wall_time_s']}s\n")
    w("## 1. Baseline suite (policy baseline-v1)\n")
    w("| Scenario | Proposal condition | R | D | C | A | Q | F | L | TP/FP/FN | "
      "blocked / prohibited | retained |")
    w("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rep["baseline"]:
        rc, c, m = r["reward_components"], r["counts"], r["metrics"]
        w(f"| {r['scenario_id']} | {PROPOSAL_TABLE1[r['scenario_id']]} | {r['reward']:.4f} | "
          f"{rc['D']:.2f} | {rc['C']:.2f} | {rc['A']:.2f} | {rc['Q']:.2f} | {rc['F']:.3f} | "
          f"{rc['L']:.3f} | {c['TP']}/{c['FP']}/{c['FN']} | "
          f"{m['blocked_flow_count']} / {m['prohibited_flow_count']} | "
          f"{m['retained_events']}/{r['n_events']} |")
    w("\nReproducibility (same seed, repeated runs):\n")
    for sid, v in rep["reproducibility"].items():
        w(f"- {sid}: {v['runs']} runs, rewards {v['rewards']} → "
          f"{'identical' if v['identical_reward'] else 'DIFFER'}")
    w("\n## 2. Reset path (Step 3.4)\n")
    w("| Scenario | first → second | all normal | identical after reset | "
      "identical without reset (control) | fresh id |")
    w("|---|---|---|---|---|---|")
    for sid, v in rep["reset"].items():
        w(f"| {sid} | {v['first_experiment']} → {v['second_experiment']} | "
          f"{v['all_normal_after_reset']} | {v['payload_identical']} | "
          f"{v['payload_identical_without_reset']} | {v['fresh_experiment_id']} |")
    w("\n## 3. Policy-lever check (fixed presets, not optimization)\n")
    w("| Scenario | Policy | R | D | C | A | Q | F | FP | prohibited |")
    w("|---|---|---|---|---|---|---|---|---|---|")
    for r in rep["lever_check"]:
        rc, c, m = r["reward_components"], r["counts"], r["metrics"]
        w(f"| {r['scenario_id']} | {r['policy_version']} | {r['reward']:.4f} | {rc['D']:.2f} | "
          f"{rc['C']:.2f} | {rc['A']:.2f} | {rc['Q']:.2f} | {rc['F']:.3f} | {c['FP']} | "
          f"{m['prohibited_flow_count']} |")
    w("\n## 4. Evidence and exports\n")
    for k, v in rep["exports"].items():
        w(f"- **{k}**: `{v}`")
    s = rep["ledger"]
    w(f"- **ledger contents**: {s['experiments']} experiments, {s['events']} events, "
      f"{s['ground_truth']} ground-truth rows, {s['resets']} resets")
    w("\n## 5. Live stack (docker compose)\n")
    live = rep["live_stack"]
    for name, st in live["services"].items():
        w(f"- {name}: " + (f"up, mode={st['mode']}, t={st['t']}, healthy={st['healthy']}"
                           if st["up"] else "down"))
    if live["prometheus"]:
        for t in live["prometheus"]["targets"]:
            w(f"- prometheus target `{t['job']}` {t['instance']}: {t['health']}")
        for k, v in live["prometheus"].get("queries", {}).items():
            w(f"- PromQL `{k}` = {v}")
    else:
        w("- prometheus: not reachable")
    w(f"- collector evidence files: {live['collector']}")
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="ProPS-Twin primary entry point")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("run", help="run one scenario as a recorded experiment")
    p.add_argument("scenario")
    p.add_argument("--policy", nargs="*", help="lever=value overrides")
    p.add_argument("--preset", choices=PRESETS, help="policy preset from configs/policies")
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--events", action="store_true", help="print the event stream")
    p.add_argument("--json", action="store_true", help="print the full ledger record")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("suite", help="run SC-01..SC-07 under the baseline policy")
    p.add_argument("--repeat", type=int, default=1)
    p.set_defaults(fn=cmd_suite)

    p = sub.add_parser("reset", help="run -> reset -> re-run checks (Step 3.4)")
    p.add_argument("scenario", nargs="?", default="all")
    p.set_defaults(fn=cmd_reset)

    p = sub.add_parser("ledger", help="list recent experiments")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(fn=cmd_ledger)

    p = sub.add_parser("status", help="probe the live docker-compose stack")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("phase3", help="full Phase 3 run + report (default)")
    p.add_argument("--repeat", type=int, default=3)
    p.set_defaults(fn=cmd_phase3)

    args = ap.parse_args()
    if not getattr(args, "fn", None):
        args = ap.parse_args(["phase3"])
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
