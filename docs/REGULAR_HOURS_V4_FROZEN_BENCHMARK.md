# Regular-hours V4 frozen benchmark execution

## Purpose

This milestone turns the existing provenance-aware V4 vs V3/V3.1 benchmark into a reproducible GitHub Actions experiment. It does not modify any Orion runtime model, probability, threshold, risk policy, broker path, or trading behavior.

## Frozen experiment

The workflow `.github/workflows/frozen-intraday-v4-benchmark.yml` executes the already-reviewed evidence runner with the predeclared universe:

`AAPL MSFT NVDA AMZN META GOOGL TSLA AMD SPY QQQ`

and fixed research parameters:

- 60d history
- 5m bars
- 0.60 V3.1 calibration fraction
- minimum 3 symbols per horizon
- minimum 80 paired observations
- minimum 8 sessions
- 2000 paired session-block bootstrap samples

The workflow runs automatically when this experiment path first lands on `main`, and can subsequently be rerun manually. It is intentionally not scheduled: repeatedly evaluating a rolling historical window should not become an implicit tuning loop.

## Evidence and safety

The benchmark runner fingerprints the exact yfinance dataframes consumed, source code, Git revision, Python runtime, and benchmark result. The workflow preserves the JSON evidence artifact for 30 days. Repository permissions are read-only and the workflow contains no secrets or broker/order integration.

Historical success is not deployment authority. `promotion_allowed` remains false in the evidence contract; a V4 historical pass is only a prerequisite for forward shadow comparison.

## Regression policy

`backend/tests/test_frozen_intraday_v4_benchmark_workflow.py` asserts the trigger/permission boundary, frozen symbol universe and benchmark parameters, evidence upload, and absence of broker/secrets/order paths. The focused intraday challenger CI runs these checks on changes to the experiment workflow.

## Decision rule

After the first main-branch evidence run completes:

- If V4 fails the existing proper-score or session-stability gate against either V3 or V3.1 on any required horizon, retain the evidence as a negative result and reject V4 unchanged.
- If V4 passes every required gate, do not replace the incumbent. Add V4 only as a forward cloud-shadow challenger and require genuine timestamped OOS evidence before any runtime promotion discussion.
- Do not alter the frozen universe, thresholds, calibration fraction, sample gates, or bootstrap policy after seeing the result merely to obtain a passing conclusion.

## Next logical step

Inspect the first immutable benchmark artifact produced from `main`. Record per-horizon Brier/log-loss deltas, bootstrap confidence bounds, directional accuracy, ECE, symbol coverage, and failure diagnostics. Use that evidence to either reject V4 or qualify it for forward shadow testing.
