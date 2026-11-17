"""Pure metric functions on hand-built examples with known TP/FP/FN."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from research.evaluation import metrics as M


def test_detection_rate():
    assert M.detection_rate(8, 10) == 0.8
    assert M.detection_rate(0, 0) == 1.0          # no positives -> perfect by convention


def test_precision_and_fp_rate():
    assert M.precision(9, 1) == 0.9
    assert M.precision(0, 0) == 1.0               # no alerts -> 1.0
    assert M.fp_rate(5, 100) == 0.05
    assert M.fp_rate(0, 0) == 0.0


def test_delay_penalty_counts_misses_as_full_window():
    # 2 matched at 0s, 2 missed, window 100 -> acc = 0 + 2*100 = 200; /4 /100 = 0.5
    assert M.delay_penalty([0.0, 0.0], missed=2, window_len=100) == 0.5
    assert M.delay_penalty([], missed=0, window_len=100) == 0.0


def test_containment_and_availability_defaults():
    assert M.containment(3, 4) == 0.75
    assert M.containment(0, 0) == 1.0             # nothing to contain -> 1.0
    assert M.availability(9, 12) == 0.75
    assert M.availability(0, 0) == 1.0            # no probes -> 1.0


def test_recovery():
    assert M.recovery(6, 60) == 0.9
    assert M.recovery(None, 60) == 1.0            # no fault -> 1.0
    assert M.recovery(1000, 60) == 0.0           # clamped


def test_reward_matches_formula():
    comp = {"D": 1.0, "C": 1.0, "A": 1.0, "Q": 1.0, "F": 0.0, "L": 0.0}
    # perfect run = sum of the positive weights
    assert abs(M.reward(comp) - (0.30 + 0.25 + 0.20 + 0.10)) < 1e-9
    comp2 = {"D": 1.0, "C": 0.0, "A": 1.0, "Q": 1.0, "F": 0.0, "L": 0.0}
    assert abs(M.reward(comp2) - (0.30 + 0.20 + 0.10)) < 1e-9
