# Regular-hours V4 challenger tournament

## Status

Research-only. Challenger V4 is not promoted or connected to Orion runtime.

## Why this exists

The generic paired tournament can compare two OOS reports for one symbol, but a single ticker can make a challenger look stronger than it is. This benchmark adds a cross-symbol gate and compares V4 against two incumbent views:

1. raw V3 daily-refit walk-forward probabilities;
2. V3.1 probabilities produced only on a later holdout after the V3.1 reliability score is fitted on the earlier OOS calibration segment.

V3, V3.1 and V4 are therefore compared only on exact common OOS timestamps. The same downloaded stock/SPY frames are supplied to V3 and V4 for a symbol so provider timing differences cannot create artificial wins.

## Cross-symbol gate

Per-symbol paired tournament rules remain unchanged: minimum paired observations and sessions plus positive lower 95% session-block bootstrap bounds for both Brier and log-loss improvement.

The cross-symbol benchmark then requires, for every 30m/1h/3h/5h horizon and for both V3 and V3.1 baselines:

- enough independently evaluable symbols;
- positive observation-weighted Brier improvement;
- positive observation-weighted log-loss improvement;
- a strict majority of symbols individually passing the session-stability tournament gate.

Any provider/data failure makes the batch fail closed (`v4_not_demonstrated`). Accuracy and ECE remain diagnostics; proper scoring rules and stability drive eligibility.

## Leakage controls

V3.1 calibration uses only the earlier chronological portion of already-OOS V3 records. The later evaluation labels cannot change the fitted reliability score or calibrated probabilities. Regression coverage explicitly mutates future evaluation labels and verifies that the V3.1 probabilities do not change.

## Reproducible command

From `backend/` after installing the normal research dependencies including `yfinance`:

```bash
python -m evals.benchmark_intraday_challenger_v4 AAPL MSFT NVDA AMZN META GOOGL TSLA AMD SPY QQQ --period 60d --interval 5m --output v4_tournament.json
```

The output is evidence only. `v4_research_eligible` is not a deployment decision.

## Next logical step

Run the benchmark on real historical data and retain the JSON result with dataset/provider timing metadata. If V4 fails any horizon or either baseline, reject it unchanged and inspect the failed regime/horizon before designing another challenger. If it passes, add V4 to cloud shadow collection alongside the incumbent and require genuine forward evidence before any runtime promotion.
