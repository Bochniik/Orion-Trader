# Long-horizon V5 stock timeline integrity guard

## Problem

The frozen long-horizon V5 design expresses both rolling features and outcome horizons in fixed counts of five-minute bars. Examples include 18 rows for 90-minute memory, 36 rows for the 3-hour target and 60 rows for the 5-hour target. This is only equivalent to elapsed clock time when the stock history itself is a contiguous five-minute regular-session timeline.

A missing stock bar can silently stretch a 3-hour or 5-hour target beyond its preregistered elapsed-time meaning. The same gap can distort row-count rolling returns, volatility, persistence and range features. A duplicate or off-grid timestamp can create the opposite problem. The benchmark-alignment guard introduced in adapter v2 protects SPY alignment, but it cannot detect corruption in the stock timeline itself.

## Forward-evidence policy

The frozen V5 model, target builder and feature definitions remain unchanged. The forward adapter now validates the normalized stock timeline before benchmark alignment or feature construction.

For every stock timestamp at or before the point-in-time cutoff:

- duplicate timestamps are forbidden,
- timestamps must lie exactly on the five-minute grid,
- consecutive rows inside the same New York regular-session date must be exactly five minutes apart.

Overnight gaps between trading sessions are expected and are ignored. A partial current session is allowed because the guard does not require a fixed first or last bar. An explicit historical `as_of` cutoff makes later unused gaps irrelevant.

Any violation fails closed before V5 feature construction. The result is marked `stock_timeline_verified=false`, and no forward forecast from that frame is eligible for evidence collection.

## Why this matters for leakage-safe validation

`attach_targets()` creates horizon labels by shifting a fixed number of rows within the same session. The V5 feature builder likewise uses row-count windows such as 6, 12 and 18 bars. If source cadence is broken, those operations still run but no longer represent the intended elapsed horizons. Rejecting the frame is therefore safer than imputing a missing stock bar or pretending row count still equals wall-clock time.

This guard is deliberately stricter than a coverage optimization. A trading halt, provider omission or other genuine missing bar may be operationally explainable, but the resulting frame still cannot be treated as clean decision-grade forward evidence for this preregistered row-count model.

## Scope and safety

This is a research data-quality change only. It does not alter model coefficients, feature formulas, target definitions, probability calculations, calibration, confidence thresholds, risk policy, runtime recommendations, market-data providers, broker connectivity or order submission.

The forward adapter identifier is bumped from `long-horizon-v5-forward-adapter-v2` to `long-horizon-v5-forward-adapter-v3` so future artifacts can distinguish the stricter stock-timeline contract.

## Verification

Focused tests cover:

- a valid contiguous partial regular session,
- overnight boundaries between sessions,
- a missing five-minute stock bar,
- duplicate timestamps,
- off-grid timestamps,
- historical point-in-time cutoffs that ignore later unused gaps,
- fail-closed behavior before feature construction,
- ordering of stock-timeline validation before benchmark alignment.

The existing long-horizon forward-shadow regression workflow continues to run because the forward adapter changes, and a dedicated stock-timeline CI workflow runs the new tests directly.

## Next step

Observe the first genuine weekday collection under adapter v3 and record only score-blind operational diagnostics: stock-timeline rejection count, affected symbols and failure reason category. If rejections occur, distinguish provider omissions from stock-specific halts or other data-quality events. Do not impute missing stock bars or weaken the guard merely to increase evidence coverage; first quantify whether the current data source can support the preregistered five-minute horizon semantics reliably.
