# Long-horizon V5 OHLCV integrity guard

## Problem

The long-horizon V5 forward adapter already rejects broken stock-bar cadence and missing benchmark timestamps. Those protections do not guarantee that the numeric OHLCV values inside an otherwise well-aligned bar are valid.

Malformed values such as `inf`, non-positive prices, negative volume, or an impossible OHLC envelope can propagate into returns, range, volatility, VWAP and relative-strength features. In the worst case they can contaminate both the current prediction row and historical rows used by the daily retraining step while preserving a superficially valid timestamp.

## Forward-evidence policy

Adapter v4 validates normalized stock and SPY rows before stock-timeline or benchmark-alignment checks and before feature construction.

For every row at or before the point-in-time cutoff:

- Open, High, Low, Close and Volume must all be finite;
- Open, High, Low and Close must be strictly positive;
- Volume must be non-negative; zero volume remains allowed because a legitimate bar can contain no reported trades;
- High must be at least Open, Close and Low;
- Low must be at most Open, Close and High.

The same rules apply independently to the stock and to SPY. A malformed stock row fails with `stock_*` diagnostics; a malformed benchmark row fails with `benchmark_*` diagnostics.

An explicit historical `as_of` remains point-in-time safe: malformed rows strictly after that cutoff do not invalidate an earlier forecast.

## Interaction with normalization

The shared OHLCV normalizer converts non-numeric values to missing values and drops rows containing those missing fields. Such removal is subsequently exposed by the stock-timeline guard when it creates an intra-session cadence gap. Values that survive numeric conversion but are still invalid for market data, such as positive/negative infinity, non-positive prices or negative volume, are rejected directly by the v4 OHLCV guard.

## Safety

This is a research-evidence data-quality change only. The frozen V5 feature definitions, model training logic, probability calculation, calibration, confidence thresholds, target definitions and promotion policy are unchanged. No runtime recommendation, risk rule, broker integration, paid data source or order path is modified.

## Verification

Focused regressions cover:

- well-formed rows including zero volume;
- non-finite OHLCV values;
- non-positive prices;
- negative volume;
- impossible High/Low envelopes;
- point-in-time cutoff behavior;
- fail-closed ordering before timeline checks and feature construction.

## Next evidence step

On the first genuine weekday collection under adapter v4, measure only score-blind OHLCV rejection counts and reason categories for stock and benchmark inputs. If rejections occur, trace the provider/raw-frame source and distinguish real market-data corrections from ingestion corruption before changing any guard.
