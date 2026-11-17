"""Small seeded-simulation helpers shared by component cores."""
from __future__ import annotations

import random


def rng_for(seed: int, offset: int = 0) -> random.Random:
    """Independent-but-reproducible RNG stream derived from the global seed."""
    return random.Random(seed + offset)


def gauss_nonneg(rng: random.Random, mean: float, sigma: float) -> float:
    """Gaussian clamped at 0 (for rates/metrics that cannot be negative)."""
    return max(0.0, rng.gauss(mean, sigma))
