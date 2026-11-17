"""Scenario schema validation.

Phase 3 upgrades this to a Pydantic v2 model (see the handbook, Step 3.1).
For the dependency-free local run we keep a plain validator so the simulation
can be exercised with nothing but the Python standard library.

A ground-truth row is one *labelled window*. Each row declares how the evaluator
should turn the window into expected positive events:

  detection_type: presence   (default)
    The `event_type` from `component` emitted inside the window is a positive.
    Detection is a threshold/state alert on that event.

  detection_type: absence
    The `event_type` from `component` is a *required periodic* signal (cadence
    `cadence` seconds). The positive is its ABSENCE: the evaluator raises a
    coverage-gap alert when the signal is missing for longer than `timeout`
    seconds, and measures recovery when it resumes. (DECISIONS: Option b.)
"""
from __future__ import annotations

REQUIRED_TOP = {
    "id", "seed", "initial_conditions", "event_sequence",
    "ground_truth", "evaluation_window", "reset_procedure",
}

DETECTION_TYPES = {"presence", "absence"}


def validate_scenario(doc: dict) -> None:
    missing = REQUIRED_TOP - set(doc)
    if missing:
        raise ValueError(f"scenario missing sections: {sorted(missing)}")

    for i, act in enumerate(doc["event_sequence"]):
        for k in ("t", "target", "action"):
            if k not in act:
                raise ValueError(f"event_sequence[{i}] missing {k!r}")

    for i, gt in enumerate(doc["ground_truth"]):
        if "label" not in gt or "window" not in gt:
            raise ValueError(f"ground_truth[{i}] needs label+window")
        win = gt["window"]
        if not (isinstance(win, (list, tuple)) and len(win) == 2 and win[0] <= win[1]):
            raise ValueError(f"ground_truth[{i}] window must be [start, end] with start<=end")
        dtype = gt.get("detection_type", "presence")
        if dtype not in DETECTION_TYPES:
            raise ValueError(f"ground_truth[{i}] detection_type must be one of {DETECTION_TYPES}")
        if dtype == "absence" and "event_type" not in gt:
            raise ValueError(f"ground_truth[{i}] absence rows need the required event_type")

    win = doc["evaluation_window"]
    if "start" not in win or "end" not in win:
        raise ValueError("evaluation_window needs start+end")

    probes = doc.get("probes")
    if probes is not None and ("interval" not in probes or "targets" not in probes):
        raise ValueError("probes section needs interval+targets")
