# Long-horizon V5 source freshness guard

Date: 2026-09-13

## Problem

The paired long-horizon collector already required the incumbent and challenger to expose the exact same source `as_of` timestamp. That protected pair identity, but it did not prove that the shared timestamp was fresh relative to the scheduled collection slot. If both engines consumed the same stale market snapshot, the artifact could still become forward evidence and later settle normally.

That failure mode is score-blind but decision-relevant: it can make collection coverage look complete while the observations are not genuine current-point-in-time forecasts.

## Guard

`run_long_horizon_v5_paired_cloud_shadow.py` now applies a second timestamp invariant after atomic pairing and before a row is admitted to the prediction artifact.

For every symbol in an eligible collection slot:

- every emitted horizon must carry one valid timezone-aware `prediction_time_utc`;
- all horizons emitted for that symbol must share that timestamp;
- the timestamp must belong to the same America/New_York market-session date as the collection reference time;
- it must not be more than 15 minutes old;
- it must not be more than one minute in the future, allowing only minimal clock skew.

A violation removes all rows for that symbol from forward evidence, records a score-blind failure reason, and makes expected coverage degraded rather than silently accepting stale evidence.

The payload records the freshness policy in `source_freshness` so later audits can see the exact operational contract without exposing probabilities or outcomes.

## Why 15 minutes

The paired workflow is hourly and the underlying regular-hours inputs are minute-scale market data. Fifteen minutes is deliberately wider than an ordinary bar-publication delay while still rejecting snapshots stale enough to invalidate the meaning of a point-in-time 3h/5h forecast. The guard is an evidence-quality rule only; it does not alter model probabilities, calibration, thresholds, risk policy, broker behavior, or runtime recommendations.

## Regression coverage

Focused tests cover:

- exact-boundary acceptance at 15 minutes;
- rejection immediately beyond the boundary;
- future timestamps beyond the one-minute skew allowance;
- prior-session timestamps;
- inconsistent timestamps across horizons for one symbol;
- integration behavior proving stale rows are removed and collection coverage becomes degraded.

## Next logical step

Observe the first scheduled weekday collection with this guard enabled. Measure only score-blind operational effects: stale-source rejection count, affected symbols, and whether the critical 5h slot still reaches expected coverage. If stale rejections occur, trace the market-data/inference source that produced the delayed `as_of` value rather than widening the threshold automatically. If no stale rejections occur across representative sessions, keep the guard as a permanent invariant and move the next engineering step to the measured collection-health bottleneck.
