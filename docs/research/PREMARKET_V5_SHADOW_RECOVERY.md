# Premarket V5 delayed shadow recovery

## Problem

GitHub Actions scheduled jobs are not guaranteed to start exactly at their cron minute. The premarket V5 shadow workflow previously used wall-clock execution time as the prediction timestamp. A materially delayed 09:15 ET run could therefore skip after the regular session opened, losing that session's point-in-time evidence.

Naively backdating a delayed run is unsafe: the history download may already contain bars after the intended prediction timestamp. If those bars reach dataset construction, the same-day training set can contain information that was unavailable at prediction time.

## Contract

The scheduled workflow now freezes the daily prediction timestamp to **09:15 America/New_York** and passes it explicitly as `--as-of`.

The runner enforces two fail-closed rules:

1. A frozen target that is still in the future is skipped (`scheduled_target_not_reached`). This makes the duplicate EDT/EST cron harmless before the correct 09:15 local slot.
2. After downloading market history, the raw input is clipped to `timestamp <= as_of` **before** training-dataset construction and model fitting. A delayed job can therefore recover the intended 09:15 snapshot without allowing post-cutoff bars into training or inference.

The prediction artifact records `causal_cutoff_enforced: true`, and the runner version is advanced to `premarket-v5-cloud-shadow-v2`.

## Regression coverage

`backend/tests/test_premarket_v5_cloud_shadow.py` covers:

- EDT and EST 09:15 conversion,
- fail-closed behavior before the frozen target is reached,
- delayed recovery after the target time,
- physical removal of post-cutoff bars from the raw history,
- existing V5 model-schema protections.

## Scope

This change is shadow/research infrastructure only. It does not promote V5, change model coefficients, alter decision thresholds, modify risk policy, or enable order submission.

## Next step

After merge, inspect the first delayed or on-time premarket artifact and confirm that its `as_of_et` is exactly 09:15 ET and that the latest causal bar does not exceed the frozen timestamp. Then apply the same explicit-slot/recovery discipline to regular-hours V3.1, where hourly scheduled execution currently still uses wall-clock runtime rather than a frozen slot identity.
