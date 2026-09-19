# Adaptive Research Loop

Orion's adaptive research loop is deliberately separated from runtime trading behavior.

## Purpose

Settled point-in-time evidence should shorten the path to better hypotheses without allowing the current model to tune itself on the same observations used to judge it. The first stage therefore mines failure patterns from the immutable cloud-shadow evidence ledger and produces research hypotheses only.

The diagnostic contract is `orion-adaptive-research-diagnostics-v1`.

## Stage 1 — settled-error diagnostics

`backend/evals/adaptive_research_error_diagnostics.py` reads the append-only cloud-shadow evidence ledger and, for a selected engine, reports:

- horizon-level error baselines;
- direction, confidence-band, symbol and reliability-profile slices;
- observation and distinct-session coverage for every slice;
- Wilson 95% uncertainty intervals for observed error rates;
- candidate failure patterns only when a slice has minimum coverage, materially higher error than its horizon baseline, and its lower uncertainty bound remains above that baseline.

The defaults are intentionally conservative: at least 12 observations, at least 3 distinct sessions and at least 10 percentage points of excess error.

These are diagnostics, not model-selection results. A reported pattern can be caused by noise, correlation between slices, market regime concentration or a weak incumbent. It is a hypothesis worth testing, not a rule to deploy.

## Anti-leakage boundary

Any challenger whose design is influenced by this diagnostic evidence must receive:

1. a new immutable candidate identity;
2. a preregistration timestamp later than the latest development observation used;
3. a new untouched forward cohort after that cutoff;
4. paired comparison against the incumbent on identical symbol/timestamp observations;
5. the existing proper-score and session-block-bootstrap gate before it can become research-eligible.

The observations used to discover a failure pattern cannot also approve the challenger created from that pattern.

## Non-goals

This stage does not retrain V3.1 or V5, change thresholds, alter calibration, change risk policy, submit orders or promote a model automatically. It does not inspect or modify broker state.

## Next stage

Once the diagnostic contract is stable, add a candidate registry that records the development-evidence cutoff, hypothesis, feature/model change, code SHA and frozen evaluation protocol before a challenger starts producing new forward predictions. The registry should fail closed if a candidate tries to reuse pre-cutoff observations as promotion evidence.
