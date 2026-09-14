# Early Premarket Observational Collection

## Purpose

Orion's frozen Premarket V5 forward protocol intentionally samples 06:45, 08:00 and 09:15 America/New_York. U.S. extended-hours trading begins at 04:00 ET, so the interval from 04:00 to 06:45 contains potentially useful information that the frozen validation cohort does not observe.

This collector records that earlier interval without changing the frozen V5 experiment. It is research-only raw evidence for future preregistered challengers.

## Frozen observational cadence

The initial cadence is six ET slots on weekdays:

- 04:05
- 04:35
- 05:05
- 05:35
- 06:05
- 06:35

A DST-safe broad GitHub cron envelope is resolved in `scripts/resolve_early_premarket_observation.py`. Inactive EDT/EST duplicate slots fail closed. Delivery more than 20 minutes after a target is rejected rather than silently reassigned.

## Data source and universe

The workflow reuses the existing Alpaca Stock Bars v2 collector with the repository's existing Alpaca credentials and IEX feed. The default observation universe matches Premarket V5:

`AAPL MSFT NVDA AMZN META GOOGL TSLA AMD SPY QQQ`

Each artifact contains raw one-minute OHLCV rows, the existing raw-collection manifest, and an observational provenance sidecar.

## Leakage boundary

These artifacts are explicitly marked:

- `observational_only = true`
- `premarket_v5_forward_eligible = false`
- `issue_3_forward_cohort_eligible = false`
- `order_submission_enabled = false`

They must never be counted toward the 55-session Premarket V5 forward cohort in Issue #3.

GitHub Actions can deliver cron jobs late. The underlying historical-bars request can therefore contain rows acquired after the nominal observation target. The sidecar records both the target and actual acquisition timestamps. Any downstream feature builder or challenger must enforce `timestamp <= target_as_of_utc` before computing features. The raw artifact is deliberately retained so that this cutoff can be audited rather than hidden.

## Research use

Once enough observations exist, a future challenger may test whether 04:00-06:45 information improves the frozen parent model. Candidate features include early gap evolution, cumulative premarket volume, range expansion/contraction, realized volatility and cross-sectional/benchmark-relative movement. Those features must be preregistered and evaluated on untouched data before any runtime promotion.

No model weights, probabilities, calibration, thresholds, risk policy, broker integration or order path are changed by this collector.
