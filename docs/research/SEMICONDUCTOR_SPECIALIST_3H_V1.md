# Semiconductor Specialist 3h V1

Status: historical screen completed and rejected. Research only; no runtime, risk, broker, order or production calibration behavior changes.

## Why this experiment exists

The earlier broad sector specialist screen did not demonstrate stable sector-wide or ticker-specific edge. A leave-one-out audit left only a weak, distributed Information Technology signal at 3h; 5h was composition-sensitive and was not carried forward. Because that observation inspired this experiment, the previously inspected sector dataset was explicitly non-decisive for this candidate.

## Frozen hypothesis

A semiconductor-specific calibration residual may improve 3h regular-hours probability quality over the global calibrated parent for liquid US semiconductor equities.

The target was **3h only**. The 5h horizon was excluded before this expanded semiconductor cohort was inspected.

## Frozen cohorts

Semiconductor cohort: `NVDA`, `AMD`, `AVGO`, `QCOM`, `MU`, `INTC`, `AMAT`.

Control cohort used to fit the broader global parent: `AAPL`, `MSFT`, `AMZN`, `TSLA`, `META`, `GOOGL`.

`SPY` remained the benchmark market series used by the existing V3 walk-forward path.

## Frozen protocol

- data screen: 60d / 5m historical regular-hours data;
- base probabilities: existing V3 chronological walk-forward;
- calibration source: existing leakage-safe V3.1 held-out conversion, calibration fraction 0.60;
- global history gate: 80 observations / 8 sessions;
- semiconductor residual gate: 40 observations / 6 sessions;
- final evaluation gate: 80 active semiconductor observations / 8 sessions;
- ridge: 8.0;
- bootstrap: 2,000 deterministic paired session-block samples;
- primary metrics: paired Brier improvement and paired log-loss improvement;
- supporting metrics: directional accuracy and ECE.

The specialist was scored only when its child layer was active. Fallback rows could not manufacture specialist evidence.

## Historical screen result

The PR #67 evidence run completed successfully and captured every preregistered symbol with no download failures. The screen produced 490 active paired observations across 10 sessions, so the preregistered coverage gate passed.

The specialist nevertheless underperformed its global calibrated parent:

- Brier score: incumbent `0.253673`, specialist `0.254108`, improvement `-0.000435`;
- log loss: incumbent `0.700503`, specialist `0.701402`, improvement `-0.000899`;
- directional accuracy: incumbent `45.9184%`, specialist `45.1020%`, delta `-0.8164 pp`;
- 10-bin ECE: incumbent `0.063162`, specialist `0.070354`, improvement `-0.007192`.

Paired session-block bootstrap was also unsupportive: the 95% interval for Brier improvement was `[-0.004610, 0.003499]`, the log-loss interval was `[-0.009260, 0.006978]`, and only about 41% of bootstrap samples showed positive proper-score improvement. The preregistered verdict is therefore `not_demonstrated`.

The immutable GitHub Actions evidence artifact has digest `sha256:5cdd6e2c9da5991fb33c6e3c88f0abefdf571c378e7ece64aaee3efe6ca89067`; the benchmark result hash recorded inside the artifact is `4b4691982da6b952ad5833620276b19aa66c97c8c1de688b5a1d2936f0c058e2`.

## Decision

Reject `semiconductor-specialist-3h-v1` unchanged. Do not promote it, assign it a decisive holdout, or tune its ridge, gates, cohort or calibration fraction on this inspected screen in an attempt to recover the hypothesis.

A future industry-specialist redesign must use a new candidate identity and must treat both the original broad-sector dataset and this semiconductor screening cohort as inspected evidence. Any later decisive evidence must be genuinely untouched and pass the research-lineage contamination guard.

## Interpretation rule

This run was historical screening, not an untouched decisive holdout. A negative screen is sufficient to deprioritize the frozen design. It does not imply that every possible industry-aware model is invalid; it means this specific residual-calibration hypothesis did not justify further promotion work.

## Anti-snooping rule

Do not change the 3h target, cohort membership, ridge, gates, calibration fraction or decision rule in response to this screen and then score the modified design on the same data as though it were untouched evidence. A redesign requires a new candidate identity and later decisive evidence must pass the research-lineage contamination guard.
