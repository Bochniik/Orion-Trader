# Long-horizon V5 benchmark alignment guard

## Problem

The frozen long-horizon V5 feature builder aligns SPY to each stock timestamp with `reindex(...).ffill()`. That fallback is convenient for exploratory research, but it is unsafe for decision-grade forward evidence: a missing SPY bar can be silently replaced by an older benchmark value while the stock prediction timestamp itself remains current. Relative-strength features can therefore look fresh even when their benchmark component is stale.

## Forward-evidence policy

The frozen V5 model and feature definitions are not changed. Instead, the forward adapter now validates normalized regular-session inputs before feature construction.

For a forward forecast to be eligible, every normalized stock timestamp that is at or before the point-in-time cutoff must also exist in the normalized SPY frame. Extra SPY timestamps are allowed. Equivalent instants are compared in UTC so differing timezone representations do not create false mismatches. If any used stock timestamp is absent from SPY, the adapter fails closed with `benchmark_missing_stock_timestamps:<count>:<first>:<last>` and does not call the feature builder.

This makes the existing SPY forward-fill path unreachable for genuine forward evidence while preserving the preregistered model implementation itself. When an explicit historical `as_of` cutoff is supplied, later unused rows do not affect the alignment decision.

## Why validate the used frame rather than only the latest bar

The challenger retrains its daily model from the same downloaded 60-day frame on each run. Checking only the final prediction bar would protect the current feature vector but could still allow forward-filled SPY values into historical training rows. Requiring exact SPY coverage for all stock timestamps used at or before the cutoff prevents that hidden benchmark imputation from affecting either the current prediction features or the training sample.

## Scope and safety

This is a research data-quality guard only. It does not change model coefficients, probability calculations, calibration, confidence thresholds, target definitions, risk policy, runtime recommendations, broker connectivity, or order submission.

The forward adapter identifier is bumped to `long-horizon-v5-forward-adapter-v2` so collected evidence can distinguish the stricter data-quality contract from earlier artifacts.

## Verification

Focused tests cover:

- exact stock/SPY timestamp alignment,
- rejection of a single missing SPY timestamp,
- fail-closed behavior before feature construction,
- allowance for harmless extra SPY timestamps,
- historical point-in-time cutoffs that ignore later unused gaps,
- timezone-equivalent timestamp representations.

The existing long-horizon forward-shadow regression workflow still runs because the adapter itself changed, and a dedicated benchmark-alignment CI job runs the new tests directly.

## Next step

Observe the first genuine weekday collection under adapter v2. Measure only score-blind benchmark-alignment rejection counts and affected symbols. If rejections occur, trace whether they come from provider timing/race conditions or persistent historical gaps before changing the policy. Do not loosen the guard merely to improve coverage.
