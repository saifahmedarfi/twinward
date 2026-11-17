"""Operational metric definitions (handbook Step 5.1), as pure functions.

Each is a total function of counts/lists so it can be unit-tested on hand-built
examples with known TP/FP/FN, independent of the simulator or any cluster. All
metrics are normalized to [0, 1] (except raw detection delay in seconds) so the
reward is comparable across scenarios.

Conventions when a dimension does not apply to a scenario (documented in
docs/metrics.md): a scenario with no ground-truth positives scores D = 1.0; with
nothing to contain, C = 1.0; with no probes, A = 1.0; with no fault to recover
from, Q = 1.0. These neutral defaults keep the reward sum well-defined.
"""
from __future__ import annotations

SEVERITY_WEIGHT = {"low": 0.1, "medium": 0.4, "high": 0.7, "critical": 1.0}

DEFAULT_WEIGHTS = {
    "w_d": 0.30, "w_c": 0.25, "w_a": 0.20,
    "w_r": 0.10, "w_f": 0.10, "w_l": 0.05,
}


def detection_rate(tp: int, g: int) -> float:
    """D = |TP| / |G|. No positives -> perfect by convention."""
    return 1.0 if g == 0 else tp / g


def precision(tp: int, fp: int) -> float:
    """TP / (TP + FP). No alerts -> 1.0 by convention."""
    return 1.0 if (tp + fp) == 0 else tp / (tp + fp)


def fp_rate(fp: int, benign: int) -> float:
    """FP / |B| (alerts raised on benign events)."""
    return 0.0 if benign == 0 else fp / benign


def fp_penalty(fp: int, benign: int) -> float:
    """F: the false-positive penalty. Unweighted FP rate in v1 (severity scaling
    is an optional extension, see docs/metrics.md)."""
    return fp_rate(fp, benign)


def detection_delay(delays: list[float]) -> float:
    """Mean of t_alert - t_event over true positives, in seconds (>= 0)."""
    return 0.0 if not delays else sum(delays) / len(delays)


def delay_penalty(matched_delays: list[float], missed: int, window_len: float) -> float:
    """L = min(1, mean_delay / W); missed positives count as W (max delay)."""
    if window_len <= 0:
        return 0.0
    total = len(matched_delays) + missed
    if total == 0:
        return 0.0
    acc = sum(min(d, window_len) for d in matched_delays) + missed * window_len
    return min(1.0, (acc / total) / window_len)


def containment(contained: int, total: int) -> float:
    """C = fraction of malicious/violating attempts denied before effect."""
    return 1.0 if total == 0 else contained / total


def availability(ok: int, total: int) -> float:
    """A = fraction of legitimate probes answered correctly within the SLA."""
    return 1.0 if total == 0 else ok / total


def recovery(t_rec: float | None, budget: float) -> float:
    """Q = 1 - min(1, t_rec / T_budget). No fault to recover from -> 1.0."""
    if t_rec is None:
        return 1.0
    if budget <= 0:
        return 0.0
    return 1.0 - min(1.0, t_rec / budget)


def reward(components: dict, weights: dict | None = None) -> float:
    """R(pi) = w_d D + w_c C + w_a A + w_r Q - w_f F - w_l L."""
    w = weights or DEFAULT_WEIGHTS
    return (
        w["w_d"] * components["D"]
        + w["w_c"] * components["C"]
        + w["w_a"] * components["A"]
        + w["w_r"] * components["Q"]
        - w["w_f"] * components["F"]
        - w["w_l"] * components["L"]
    )
