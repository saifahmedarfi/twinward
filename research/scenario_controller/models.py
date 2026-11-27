"""Scenario schema validation (handbook Step 3.1).

When Pydantic v2 is installed, scenarios are validated by the typed models
below (`Scenario`), which reject unknown actions, inverted windows, unknown
reset steps and malformed probes with a ``pydantic.ValidationError`` (a
``ValueError`` subclass). Without Pydantic, the plain validator
(`_validate_plain`) runs instead, so the simulation still works with nothing but
the Python standard library.

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

from typing import Any

REQUIRED_TOP = {
    "id", "seed", "initial_conditions", "event_sequence",
    "ground_truth", "evaluation_window", "reset_procedure",
}

DETECTION_TYPES = {"presence", "absence"}
ACTIONS = {"set_mode", "inject"}
RESET_STEPS = {"restore_modes", "restore_policy_baseline", "flush_state", "new_experiment_id"}
COMPONENTS = {"idmz-gateway", "boundary-firewall", "plc-edge", "eng-station",
              "telemetry-forwarder"}


def _validate_plain(doc: dict) -> None:
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


try:
    from typing import Literal

    from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

    class _Loose(BaseModel):
        # scenario YAMLs carry documentation keys (attack_technique, ...)
        model_config = ConfigDict(extra="allow")

    class Action(_Loose):
        t: int = Field(ge=0)
        target: str
        action: Literal["set_mode", "inject"]
        value: str = "normal"
        duration: int | None = Field(default=None, ge=1)

        @field_validator("target")
        @classmethod
        def _known_target(cls, v: str) -> str:
            if v not in COMPONENTS:
                raise ValueError(f"unknown target component {v!r}")
            return v

    class GroundTruthRow(_Loose):
        label: str
        window: tuple[int, int]
        expected_detection: bool = True
        detection_type: Literal["presence", "absence"] = "presence"
        component: str | None = None
        event_type: str | None = None
        cadence: int = Field(default=1, ge=1)
        timeout: float = Field(default=5, gt=0)

        @model_validator(mode="after")
        def _check(self) -> GroundTruthRow:
            if self.window[0] > self.window[1]:
                raise ValueError("window must be [start, end] with start<=end")
            if self.detection_type == "absence" and not self.event_type:
                raise ValueError("absence rows need the required event_type")
            return self

    class Window(_Loose):
        start: int = Field(ge=0)
        end: int = Field(gt=0)

    class Probes(_Loose):
        interval: int = Field(ge=1)
        targets: list[str]
        sla_ms: float = 50.0

    class Scenario(_Loose):
        id: str = Field(pattern=r"^SC-\d{2}$")
        seed: int
        description: str = ""
        initial_conditions: dict[str, Any]
        event_sequence: list[Action] = Field(min_length=1)
        ground_truth: list[GroundTruthRow] = Field(min_length=1)
        evaluation_window: Window
        reset_procedure: list[Literal["restore_modes", "restore_policy_baseline",
                                      "flush_state", "new_experiment_id"]]
        probes: Probes | None = None

        @model_validator(mode="after")
        def _windows_inside_evaluation(self) -> Scenario:
            end = self.evaluation_window.end
            for row in self.ground_truth:
                if row.window[1] > end:
                    raise ValueError(f"ground truth {row.label!r} ends after evaluation window")
            return self

    def validate_scenario(doc: dict) -> None:
        missing = REQUIRED_TOP - set(doc)
        if missing:  # keep the original, readable message for the common case
            raise ValueError(f"scenario missing sections: {sorted(missing)}")
        Scenario.model_validate(doc)

    PYDANTIC = True
except ImportError:  # stdlib-only path
    validate_scenario = _validate_plain  # type: ignore[assignment]
    PYDANTIC = False
