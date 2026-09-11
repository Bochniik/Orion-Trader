# Long-Horizon Regular-Hours Challenger Protocol

## Purpose

The frozen V4 benchmark produced an unstable positive signal on 3h/5h while the 30m hypothesis regressed proper scores. That result is not evidence that a 3h/5h challenger is already superior; using the same benchmark again to tune and approve a new model would be data snooping.

This protocol fixes the next hypothesis and its decision rules before new forward evidence arrives.

## Pre-registered hypothesis

A separately designed regular-hours challenger may target only the 3h and 5h directional horizons. The short horizons are not part of this candidate's success criterion and may not be added or removed after forward results are observed.

Required horizons:

- 3h
- 5h

Pre-registration cutoff: `2026-09-11T00:00:00Z`.

## Evidence policy

Historical walk-forward/backtest data is allowed only for design screening. A strong historical result is explicitly insufficient for research eligibility.

The decisive comparison must use genuinely forward observations whose paired incumbent/challenger timestamps are all at or after the pre-registration cutoff. Any pre-cutoff paired observation in either required horizon makes the forward gate fail closed.

The existing paired challenger tournament remains the scoring authority. Incumbent and challenger are compared only on identical timestamps and identical outcomes. Each required horizon must independently satisfy:

- minimum paired-observation coverage;
- minimum distinct-session coverage;
- positive Brier-score improvement;
- positive log-loss improvement;
- positive lower 95% session-block-bootstrap confidence bounds for both proper-score improvements.

Directional accuracy and ECE remain supporting diagnostics and cannot substitute for proper-score improvement.

## Frozen candidate design: long-horizon v5

Candidate identity: `long-horizon-v5-20260911-a`.

The first candidate after pre-registration is deliberately different from V4. It does not add regime-classification thresholds. Instead it extends the incumbent statistical feature set with causal horizon-specific memory signals that can plausibly matter at 3h/5h horizons:

- 90-minute return and realized volatility for the 3h branch;
- 90-minute stock-vs-SPY relative strength for the 3h branch;
- 60-minute directional persistence and range expansion for the 3h branch;
- 60-minute realized volatility for the 5h branch;
- 30-minute directional persistence and range expansion for the 5h branch;
- session-progress interactions with horizon-appropriate relative strength.

The earlier 120-minute feature concept was removed before forward evaluation because it consumed too much of the usable 5h prediction window. All retained rolling and return features are session-bounded. The model is refit once per test day and its training cutoff is shifted backward by the full target horizon so unresolved outcomes cannot enter training. Fixed L2 and probability-shrinkage constants are part of the candidate identity and must not be retuned after forward labels are observed.

Historical results for this candidate remain screening-only. They may reject the design before shadow collection, but they cannot make it research-eligible.

## Historical screening contract

`backend/evals/benchmark_intraday_long_horizon_v5.py` performs the pre-forward screen of the frozen V5 identity against both raw V3 and leakage-safe held-out V3.1. It uses only the pre-registered 3h/5h horizons and the generic paired tournament, so incumbent and challenger are scored only on identical OOS timestamps.

The multi-symbol screen requires, for each required horizon and against both baselines:

- enough evaluable symbols;
- a majority of per-symbol paired tournaments to satisfy the session-block stability gate;
- positive observation-weighted Brier improvement;
- positive observation-weighted log-loss improvement.

Any symbol/data failure makes the batch fail closed. Candidate identity drift is rejected before scoring. Even a complete historical pass returns `forward_research_eligible=false`, `promotion_allowed=false`, and can only conclude `v5_survives_historical_screen`. A failed screen concludes `v5_reject_unchanged`; the frozen candidate must not then be retuned and rescored as if the same evidence were untouched.

## Anti-overfitting rules

1. The frozen V4 benchmark must not be reused as promotion evidence for the next challenger.
2. Historical evidence is screening-only even if every metric improves.
3. The required horizons are fixed at 3h and 5h before new forward evidence.
4. Missing forward coverage fails closed rather than being imputed.
5. A candidate that fails forward evidence is rejected unchanged. Any redesigned candidate receives a new identity and must face a later untouched holdout.
6. No runtime model, reliability table, threshold, leverage rule, broker path or order behavior changes as part of this protocol.

## Implementation

`backend/evals/long_horizon_challenger_gate.py` wraps the generic paired tournament with the pre-registered 3h/5h scope and explicit evidence modes:

- `historical_screen`: always returns screening-only and can never become forward research-eligible.
- `forward_holdout`: requires all paired timestamps in both required horizons to be at or after the cutoff before the paired tournament can confer research eligibility.

`backend/app/services/intraday_probability_long_horizon_challenger_v5.py` implements the frozen `long-horizon-v5-20260911-a` candidate as research-only walk-forward code. It emits only 3h/5h chronological OOS records and explicitly sets `runtime_modified=false` and `promotion_allowed=false`.

Even a successful forward research result sets `promotion_allowed=false`. Runtime promotion remains a separate product/risk decision.

## Next logical step

Run the frozen leakage-safe historical screen on the established multi-symbol universe. If V5 fails either required horizon or either baseline, record `v5_reject_unchanged` and do not retune it on the same evidence. If it survives, add a research-only cloud-shadow collector that records V5 predictions alongside the incumbent without changing runtime behavior, then wait for sufficient post-cutoff sessions before evaluating the untouched forward holdout.
