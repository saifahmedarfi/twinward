"""Evaluation engine: the log-only (fast-mode) evaluator (handbook Phase 5).

It reads the raw JSON events produced by a scenario run and applies the SAME
detection logic Wazuh would, entirely offline. It NEVER reads the ground-truth
table to make a detection decision: detection is computed from telemetry fields
(event_type, simulated_state, details) alone, and only AFTERWARDS are alerts
matched to ground truth by event_id and time window. That ordering is what keeps
the pipeline honest (DECISIONS: ground truth stays out of the event stream).

Two detection paths:
  - presence: a threshold alert on drop-rate signals, or a state alert on
    anomalous/fault/violation events. The threshold (alert_threshold) is applied
    HERE, so a policy changes detection without re-running the simulation.
  - absence (coverage): a required periodic signal that goes missing for longer
    than `timeout` raises a coverage-gap alert (SC-05, SC-07 / Option b).

`evaluate()` returns one result document per run, with every reward component
reported separately and the reproducibility metadata (seed, policy, scenario).
"""
from __future__ import annotations

import datetime as dt

from research.evaluation import metrics as M

EPOCH = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)

# simulated_states that a stateful (non-threshold) rule treats as an alert
_ALERTING_STATES = {"anomalous", "fault", "violation"}
_DETECTION_STATES = _ALERTING_STATES  # alias for readability
# raw-signal cutoff band for alert_threshold in [1, 5] (operational z-score proxy)
_CUTOFF_LO, _CUTOFF_HI = 0.05, 0.25


def _t_of(event: dict) -> int:
    """Recover the integer simulated tick (seconds since EPOCH) from a timestamp."""
    d = dt.datetime.strptime(event["timestamp"], "%Y-%m-%dT%H:%M:%S.%fZ")
    return round((d.replace(tzinfo=dt.UTC) - EPOCH).total_seconds())


def detection_cutoff(alert_threshold: float) -> float:
    """Map the alert_threshold policy param (1..5) to a drop-rate alert cutoff.

    Low threshold -> low cutoff -> more alerts (more false positives); high
    threshold -> high cutoff -> fewer alerts (more missed). This is the lever
    that makes detection (and so the reward) non-degenerate across policies.
    """
    at = max(1.0, min(5.0, float(alert_threshold)))
    return _CUTOFF_LO + (at - 1.0) / 4.0 * (_CUTOFF_HI - _CUTOFF_LO)


def detect_presence(events: list[dict], alert_threshold: float,
                    absence_event_types: set[str]) -> list[dict]:
    """Produce presence alerts from raw events (never touches ground truth)."""
    cutoff = detection_cutoff(alert_threshold)
    alerts = []
    for e in events:
        et = e["event_type"]
        if et == "probe_result" or et in absence_event_types:
            # probes feed availability; absence-monitored signals feed coverage
            continue
        details = e.get("details") or {}
        drop = details.get("drop_rate")
        fire = (drop >= cutoff) if drop is not None else (e["simulated_state"] in _ALERTING_STATES)
        if fire:
            alerts.append({
                "event_id": e["event_id"], "t": _t_of(e), "component": e["component"],
                "event_type": et, "severity": e["severity"], "kind": "presence",
                "state": e["simulated_state"],
            })
    return alerts


def detect_coverage_gap(events: list[dict], row: dict) -> dict:
    """Longest absence of a required periodic signal inside the ground-truth window."""
    comp, et = row["component"], row["event_type"]
    cadence = int(row.get("cadence", 1))
    timeout = float(row.get("timeout", 5))
    a, b = int(row["window"][0]), int(row["window"][1])
    present = {_t_of(e) for e in events
               if e["component"] == comp and e["event_type"] == et}

    runs, cur = [], None
    for t in range(a, b + 1, cadence):
        if t not in present:
            cur = [t, t] if cur is None else [cur[0], t]
        elif cur is not None:
            runs.append(cur); cur = None
    if cur is not None:
        runs.append(cur)

    if not runs:
        return {"detected": False, "gap_start": None, "gap_len_s": 0.0, "delay": None}
    longest = max(runs, key=lambda r: r[1] - r[0])
    gap_len = (longest[1] - longest[0]) + cadence
    detected = gap_len >= timeout
    return {"detected": detected, "gap_start": longest[0], "gap_len_s": float(gap_len),
            "delay": timeout if detected else None}


def _recovery_time(events: list[dict], row: dict) -> float | None:
    """Ticks from fault end (window end) until the required signal is healthy again."""
    comp, et = row["component"], row["event_type"]
    fault_end = int(row["window"][1])
    healthy = sorted(_t_of(e) for e in events
                     if e["component"] == comp and e["event_type"] == et
                     and e["simulated_state"] == "normal" and _t_of(e) >= fault_end)
    if not healthy:
        return None
    return float(healthy[0] - fault_end)


def evaluate(run_result: dict, scenario: dict, *,
             alert_threshold: float | None = None,
             recovery_budget: float | None = None,
             weights: dict | None = None) -> dict:
    """Score one scenario run. Returns a result document (dict)."""
    events = run_result["events"]
    gt_rows = scenario["ground_truth"]
    win = scenario["evaluation_window"]
    window_len = float(int(win["end"]) - int(win["start"]))

    ic = scenario.get("initial_conditions", {})
    if alert_threshold is None:
        alert_threshold = float(ic.get("alert_threshold", 3.0))
    if recovery_budget is None:
        recovery_budget = float(ic.get("recovery_timeout", 60))

    absence_rows = [r for r in gt_rows if r.get("detection_type") == "absence"]
    presence_rows = [r for r in gt_rows if r.get("detection_type", "presence") == "presence"]
    absence_event_types = {r["event_type"] for r in absence_rows}

    alerts = detect_presence(events, alert_threshold, absence_event_types)

    # --- presence matching -------------------------------------------------
    positive_ids: set[str] = set()
    total_g = tp = 0
    matched_delays: list[float] = []
    contained_yes = contained_total = 0
    severity_hits = severity_total = 0

    for row in presence_rows:
        a, b = int(row["window"][0]), int(row["window"][1])
        fam = [e for e in events
               if e["component"] == row.get("component") and e["event_type"] == row["event_type"]
               and a <= _t_of(e) <= b]
        fam_ids = {e["event_id"] for e in fam}
        positive_ids |= fam_ids
        total_g += len(fam)
        matched = [al for al in alerts if al["event_id"] in fam_ids]
        tp += len(matched)
        matched_delays.extend(0.0 for _ in matched)
        for al in matched:
            if "expected_severity" in row:
                severity_total += 1
                severity_hits += int(al["severity"] == row["expected_severity"])
        for e in fam:
            det = e.get("details") or {}
            if "contained" in det:
                contained_total += 1
                contained_yes += int(bool(det["contained"]))

    fn = total_g - tp

    # --- absence (coverage) matching --------------------------------------
    recoveries: list[float] = []
    coverage_results = []
    for row in absence_rows:
        res = detect_coverage_gap(events, row)
        coverage_results.append({"label": row["label"], **res})
        total_g += 1
        if res["detected"]:
            tp += 1
            matched_delays.append(float(res["delay"]))
        else:
            fn += 1
        if row.get("measure_recovery"):
            t_rec = _recovery_time(events, row)
            recoveries.append(M.recovery(t_rec, recovery_budget))

    # --- false positives & benign set -------------------------------------
    # A false positive is an alert raised on a BENIGN (normal-state) event, e.g. a
    # near-miss heartbeat. An alert on an anomalous/violation event that is not the
    # labelled family is a redundant detection of the real incident, not a false
    # positive against legitimate traffic, so it counts as neither TP nor FP.
    fp_alerts = [al for al in alerts
                 if al["state"] == "normal" and al["event_id"] not in positive_ids]
    fp = len(fp_alerts)
    benign = sum(
        1 for e in events
        if e["simulated_state"] == "normal"
        and e["event_type"] != "probe_result"
        and e["event_type"] not in absence_event_types
        and e["event_id"] not in positive_ids
    )

    # --- availability (probes) --------------------------------------------
    probe_events = [e for e in events if e["event_type"] == "probe_result"]
    probe_ok = sum(1 for e in probe_events if (e.get("details") or {}).get("ok"))

    # --- reward components -------------------------------------------------
    comp = {
        "D": M.detection_rate(tp, total_g),
        "C": M.containment(contained_yes, contained_total),
        "A": M.availability(probe_ok, len(probe_events)),
        "Q": (sum(recoveries) / len(recoveries)) if recoveries else 1.0,
        "F": M.fp_penalty(fp, benign),
        "L": M.delay_penalty(matched_delays, fn, window_len),
    }
    r = M.reward(comp, weights)

    return {
        "experiment_id": run_result["experiment_id"],
        "scenario_id": scenario["id"],
        "seed": int(scenario["seed"]),
        "policy_version": ic.get("policy", "baseline-v1"),
        "policy": {"alert_threshold": alert_threshold,
                   "idmz_access_profile": ic.get("idmz_profile", ic.get("idmz_access_profile", "standard")),
                   "recovery_timeout": recovery_budget},
        "reward": r,
        "reward_components": comp,
        "metrics": {
            "detection_rate": comp["D"],
            "precision": M.precision(tp, fp),
            "fp_rate": M.fp_rate(fp, benign),
            "detection_delay_s": M.detection_delay(matched_delays),
            "containment": comp["C"],
            "availability": comp["A"],
            "recovery": comp["Q"],
            "severity_match": (severity_hits / severity_total) if severity_total else None,
        },
        "counts": {"TP": tp, "FP": fp, "FN": fn, "G": total_g, "B": benign,
                   "alerts": len(alerts), "probes": len(probe_events), "probe_ok": probe_ok},
        "coverage": coverage_results,
    }
