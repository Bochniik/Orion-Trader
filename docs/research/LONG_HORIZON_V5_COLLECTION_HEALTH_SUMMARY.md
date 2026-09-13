# Long-horizon V5 score-blind collection health summary

## Purpose

The long-horizon forward-evidence pipeline now has several acquisition-integrity guards: source freshness, completed-bar age, stock-timeline integrity, benchmark alignment, OHLCV validity, and strict artifact provenance. The next useful step is to measure which guard actually limits genuine weekday coverage instead of adding more speculative checks.

This utility summarizes collection health without inspecting model probabilities, directions, calibration, outcomes, or performance metrics.

## Population integrity

Operational health metrics are computed only from artifacts whose `acquisition_provenance.forward_eligible` value is the boolean `true`. Manual and diagnostic artifacts are counted in `ignored_non_forward_run_count` but do not contribute to status counts, coverage, failure reasons, affected symbols, or complete-run counts.

This distinction is required because mixing diagnostic runs into genuine forward evidence can distort the measured bottleneck. Missing, malformed, or non-boolean forward-eligibility provenance fails closed rather than being guessed.

## Output

`scripts/summarize_long_horizon_v5_collection_health.py` accepts one or more paired prediction JSON artifacts and emits only operational fields:

- total input count, forward-eligible count, and ignored non-forward count;
- forward-only run/status counts;
- forward-only complete-run count;
- forward-only aggregate expected and observed pair counts plus observed-pair rate;
- forward-only normalized failure reason counts;
- forward-only affected symbols by normalized failure reason.

Dynamic text after the first `:` in a failure value is discarded. This keeps values such as timestamp mismatches, ages, provider exception details, and other diagnostic payload text out of the aggregate report.

The summarizer never traverses `paired_predictions`, so incumbent/challenger probabilities cannot affect or leak into the health result.

## Contract

The output contract is `orion-long-horizon-v5-collection-health-v2`, is explicitly marked `score_blind: true`, and declares `population: forward_eligible_only`.

Input files must use the paired-shadow contract `orion-long-horizon-v5-paired-shadow-v1`; unexpected contracts fail closed.

## Verification

Focused tests cover forward-only aggregation, exclusion of non-forward diagnostic failures and coverage, normalization of dynamic failure detail, exclusion of model probabilities from the result, malformed failure structures, ambiguous provenance, missing provenance, and rejection of unexpected input contracts.

## Next evidence step

After this change is green and merged, run the summarizer against the first genuine weekday prediction artifacts produced under paired runner v5. Use only the forward-eligible reason counts and observed-pair rate to choose the next engineering task. A recurring source-freshness or completed-bar problem should lead to provider/workflow timing investigation; timeline, OHLCV, or benchmark-alignment failures should lead to ingestion-quality investigation. Do not relax a guard solely to improve coverage.
