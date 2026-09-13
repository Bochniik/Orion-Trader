# Long-horizon V5 completed-bar evidence guard

## Finding

The paired long-horizon collector previously required V3.1 and V5 to agree on the exact source timestamp and rejected stale or future timestamps. That still allowed a scheduled run started shortly after a five-minute boundary to accept the bar whose timestamp marks the beginning of the currently forming interval.

For forward research evidence this is not reproducible: historical model rows are finalized bars, while an in-progress bar can change after the prediction is recorded. The issue is independent of model score and therefore should be handled as acquisition integrity rather than by changing calibration or thresholds.

## Guard

Scheduled evidence whose acquisition provenance is `forward_eligible` now requires the shared prediction timestamp to be at least five minutes older than the collection reference time. A younger source timestamp fails closed with `prediction_bar_not_closed:<age>s` and contributes no prediction rows.

The existing maximum source age remains 15 minutes, so eligible scheduled evidence is constrained to a closed-bar window of 5–15 minutes behind the collection reference.

Local and manually triggered diagnostic runs do not receive the minimum-age restriction. They remain useful for debugging current data without becoming forward evidence.

## Scope

This change does not alter:

- V5 coefficients, features, target definitions, probabilities, or calibration;
- V3.1 runtime recommendations or suppression logic;
- symbol universe, market-data provider, risk policy, broker integration, or order paths;
- score-bearing evaluation or promotion criteria.

The paired runner version is advanced to `long-horizon-v5-paired-shadow-v5` so the acquisition behavior is explicit in artifact lineage.

## Verification

Focused regressions cover the exact five-minute boundary, rejection at 299 seconds, scheduled-only enforcement, and successful collection from a fully elapsed five-minute bar. The existing long-horizon forward-shadow suite remains the broader regression gate because the runner script is already in that workflow's path filter.

## Next evidence step

On the first genuine weekday scheduled collection, record only score-blind `prediction_bar_not_closed` rejection counts together with freshness, OHLCV, timeline, benchmark-alignment, and coverage diagnostics. If the guard rejects many symbols, trace provider publication latency and workflow start timing before changing the five-minute requirement.
