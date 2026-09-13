# Long-horizon V5 score-blind collection health summary

## Purpose

The long-horizon forward-evidence pipeline now has several acquisition-integrity guards: source freshness, completed-bar age, stock-timeline integrity, benchmark alignment, OHLCV validity, and strict artifact provenance. The next useful step is to measure which guard actually limits genuine weekday coverage instead of adding more speculative checks.

This utility summarizes collection health without inspecting model probabilities, directions, calibration, outcomes, or performance metrics.

## Output

`scripts/summarize_long_horizon_v5_collection_health.py` accepts one or more paired prediction JSON artifacts and emits only operational fields:

- run/status counts;
- forward-eligible run count;
- complete-run count;
- aggregate expected and observed pair counts plus observed-pair rate;
- normalized failure reason counts;
- affected symbols by normalized failure reason.

Dynamic text after the first `:` in a failure value is discarded. This keeps values such as timestamp mismatches, ages, provider exception details, and other diagnostic payload text out of the aggregate report.

The summarizer never traverses `paired_predictions`, so incumbent/challenger probabilities cannot affect or leak into the health result.

## Contract

The output contract is `orion-long-horizon-v5-collection-health-v1` and is explicitly marked `score_blind: true`.

Input files must use the paired-shadow contract `orion-long-horizon-v5-paired-shadow-v1`; unexpected contracts fail closed.

## Verification

Focused tests cover aggregation, normalization of dynamic failure detail, exclusion of model probabilities from the result, malformed failure structures, and rejection of unexpected input contracts.

## Next evidence step

After this PR is green and merged, run the summarizer against the first genuine weekday forward-eligible prediction artifacts produced under paired runner v5. Use the resulting reason counts and observed-pair rate to choose the next engineering task. A recurring source-freshness or completed-bar problem should lead to provider/workflow timing investigation; timeline, OHLCV, or benchmark-alignment failures should lead to ingestion-quality investigation. Do not relax a guard solely to improve coverage.
