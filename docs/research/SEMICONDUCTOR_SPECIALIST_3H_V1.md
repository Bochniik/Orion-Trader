# Semiconductor Specialist 3h V1

Status: preregistered historical screening experiment. Research only; no runtime, risk, broker, order or production calibration behavior changes.

## Why this experiment exists

The earlier broad sector specialist screen did not demonstrate stable sector-wide or ticker-specific edge. A leave-one-out audit left only a weak, distributed Information Technology signal at 3h; 5h was composition-sensitive and is not carried forward. Because that observation inspired this experiment, the previously inspected sector dataset is explicitly non-decisive for this candidate.

## Frozen hypothesis

A semiconductor-specific calibration residual may improve 3h regular-hours probability quality over the global calibrated parent for liquid US semiconductor equities.

The target is **3h only**. The 5h horizon is excluded before this expanded semiconductor cohort is inspected.

## Frozen cohorts

Semiconductor cohort: `NVDA`, `AMD`, `AVGO`, `QCOM`, `MU`, `INTC`, `AMAT`.

Control cohort used to fit the broader global parent: `AAPL`, `MSFT`, `AMZN`, `TSLA`, `META`, `GOOGL`.

`SPY` remains the benchmark market series used by the existing V3 walk-forward path.

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

The specialist is scored only when its child layer is active. Fallback rows cannot manufacture specialist evidence.

## Interpretation rule

This run is historical screening, not an untouched decisive holdout. It can reject or deprioritize the hypothesis. A positive screen only justifies collecting a fresh untouched forward cohort under the same frozen identity; it cannot authorize production promotion.

Any failed required symbol download invalidates historical support rather than silently changing the cohort. Exact downloaded frames and source files are content-addressed in the evidence artifact.

## Anti-snooping rule

Do not change the 3h target, cohort membership, ridge, gates, calibration fraction or decision rule in response to this screen and then score the modified design on the same data as though it were untouched evidence. A redesign requires a new candidate identity and later decisive evidence must pass the research-lineage contamination guard.
