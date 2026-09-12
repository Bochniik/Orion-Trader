# Regular-hours timestamp provenance

## Purpose

Regular-hours V3.1 forward evidence must be evaluated against the exact market-data cutoff used by the ensemble. Artifact creation time is operational metadata and is not evidence of the source-data cutoff.

## Required provenance

A regular-hours symbol is eligible for outcome collection and scoring only when all of the following are true:

- the symbol-level `as_of` timestamp is present and timezone-aware;
- `source_timestamp_aligned` is exactly `true`;
- V1 and V2 source timestamps are preserved in `source_as_of` for auditability;
- the forecast itself is available and not suppressed by display/reliability policy.

If V1 and V2 consume different latest bars, the ensemble intentionally withholds `as_of`. Such probabilities may remain visible for research diagnostics, but they are not valid point-in-time forward evidence and must not enter Brier score, log loss, calibration, accuracy, or outcome-fetch windows.

## Fail-closed settlement rule

`scripts/evaluate_cloud_shadow_predictions.py` must never substitute top-level `created_at_utc` for a missing regular-hours symbol `as_of`. A workflow can spend seconds or minutes installing dependencies and running models after the source bars were observed; using artifact creation time as the prediction cutoff can therefore shift both the base-price and target-price windows and contaminate forward validation.

Rows with missing, malformed, unproven, or explicitly unaligned source timestamps are excluded before outcome collection and settlement.

Premarket V5 timestamp handling is unchanged by this policy.

## Regression protection

Focused tests verify that:

1. the Regular-hours V3.1 cloud-shadow artifact preserves `as_of`, `source_timestamp_aligned`, and `source_as_of`;
2. an aligned symbol-level cutoff is accepted;
3. a missing `as_of` cannot fall back to artifact creation time;
4. an explicitly unaligned timestamp is excluded even when an `as_of` value is present;
5. missing alignment proof fails closed.

Both Regular-hours V3.1 cloud-shadow CI and Cloud shadow settlement CI run the provenance regressions.

## Next logical step

Collect the next genuine regular-hours forward artifacts and measure provenance-valid coverage separately from raw workflow success. If timestamp alignment frequently fails, investigate why V1 and V2 obtain different latest bars and redesign data acquisition around one shared immutable input snapshot before changing model weights or calibration.
