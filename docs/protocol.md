# Pre-registration protocol (tag `protocol-v1` before any optimization run)

## Hypotheses
- H1: LLM-guided ProPS > fixed baseline (final mean reward).
- H2: ProPS > random search for the same budget.
- H3: ProPS competitive with / better than TPE in sample efficiency.
- H4: Domain hints improve ProPS over a no-hint ablation.
- H5: Hard safety constraints are never violated by an accepted candidate.

## Fixed in advance
- Primary metric: final best-so-far reward on held-out seeds.
- Budget B, repetitions, seeds, statistical tests: (fill in).

## Known threats to validity
Synthetic-data realism, LLM non-determinism, reward-weight dependence,
overfitting to deterministic scenarios, Wazuh latency noise.
