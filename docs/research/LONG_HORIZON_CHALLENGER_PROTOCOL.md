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

The first candidate after pre-registration is deliberately different from V4. It does not add regime-classification thresholds. Instead it extends the incumbent statistical feature set with causal longer-memory signals that can plausibly matter at 3h/5h horizons:

- 90-minute and 120-minute session-bounded returns;
- 90-minute realized volatility;
- 90-minute stock-vs-SPY relative strength;
- 60-minute directional persistence;
- 60-minute range expansion;
- an interaction between session progress and 90-minute relative strength.

All rolling and return features are session-bounded. The model is refit once per test day and its training cutoff is shifted backward by the full target horizon so unresolved outcomes cannot enter training. Fixed L2 and probability-shrinkage constants are part of the candidate identity and must not be retuned after forward labels are observed.

Historical results for this candidate remain screening-only. They may reject the design before shadow collection, but they cannot make it research-eligible.

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

Run leakage-safe historical paired screening of the frozen v5 candidate against V3/V3.1 to reject it if it is obviously weak. If it survives screening, add a research-only cloud shadow runner that records v5 predictions alongside the incumbent without changing runtime behavior. After enough post-cutoff sessions accumulate, evaluate the untouched paired forward holdout with this gate. Do not tune the same candidate on that holdout.
