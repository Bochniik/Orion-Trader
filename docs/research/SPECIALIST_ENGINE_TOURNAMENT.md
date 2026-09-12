# Sector & Ticker Specialist Engine Tournament

Status: research-only challenger protocol. This work does **not** change the Regular-hours V3.1 runtime, its frozen forward-validation lineage, risk policy, market-data provider, broker behavior, or order paths.

## Hypothesis

A single global intraday probability model may leave stable cross-sectional calibration error on the table because sectors and highly liquid individual tickers can have different response distributions. The research question is whether a hierarchical specialist layer adds out-of-sample probability quality without sacrificing causal integrity.

The hierarchy is:

1. `base`: supplied point-in-time out-of-sample probability.
2. `global`: one regularized calibration intercept learned from all completed prior sessions.
3. `sector`: global calibration plus a regularized sector residual when the sector has enough prior observations/sessions; otherwise exact fallback to global.
4. `ticker`: global + sector calibration plus a regularized ticker residual when the ticker has enough prior observations/sessions; otherwise exact fallback to sector.

This first experiment deliberately tests **specialist calibration**, not a new feature/model family. That keeps the hypothesis narrow and avoids changing the frozen Regular-hours V3.1 predictive cohort before specialization demonstrates value.

## Causality rules

- Every prediction for a session is frozen before any label from that session enters fitting history.
- Sector/ticker membership must be supplied as prediction-time metadata. The tournament does not infer future classifications.
- Duplicate `(symbol, timestamp)` identities, malformed probabilities, missing sector metadata, or invalid labels fail closed.
- Specialist candidates and incumbent are compared on identical symbol/timestamp rows only.
- Same-session outcomes and future observations may not affect earlier predictions; dedicated regressions enforce both invariants.

## Preregistered sample gates

Defaults are fixed before inspecting specialist performance:

- global calibration: at least 80 prior observations across 8 prior sessions;
- sector residual: at least 40 prior observations across 6 prior sessions;
- ticker residual: at least 24 prior observations across 5 prior sessions;
- ridge penalty: 8.0;
- final paired evaluation: at least 80 observations across at least 8 sessions.

Insufficient specialist history is not imputed. The row falls back to its parent layer and the fallback is counted explicitly.

## Evaluation

The existing Orion paired challenger tournament remains the scoring authority. Brier score and log loss are primary. Directional accuracy and 10-bin ECE are supporting diagnostics. Stability uses deterministic paired session-block bootstrap rather than independent-row resampling.

A specialist is only `research_eligible` when the existing paired tournament's proper-score coverage and stability conditions pass. Even that result is **not promotion authorization**. The output hard-codes `promotion_authorized=false`.

The decisive production question is staged:

- sector specialist must first demonstrate value against the global calibrated candidate;
- ticker specialization should then be examined for incremental value over the sector parent, not merely against an uncalibrated baseline;
- a later runtime/promotion proposal requires untouched evidence and a separate decision.

## Data requirement

GitHub source currently does not contain the real point-in-time model dataset needed to make a performance claim. Therefore this PR establishes the leakage-safe tournament and synthetic causality regressions only. No synthetic score is evidence that specialization works.

The next experiment should feed historical/forward OOS records containing `timestamp`, `symbol`, prediction-time `sector`, `p_up`, and `actual_up` for liquid equities. ETFs such as SPY/QQQ should be treated as a separate asset bucket or excluded from sector conclusions rather than being mislabeled as equities sectors.

## Decision rule

If sector/ticker specialization does not improve paired proper scores with session-level stability, reject it unchanged. Do not tune gates or ridge strength on the same decisive holdout after seeing the result. Any redesign receives a new research identity and a fresh untouched evaluation set.
