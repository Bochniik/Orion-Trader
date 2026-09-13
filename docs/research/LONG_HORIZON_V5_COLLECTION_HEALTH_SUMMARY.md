# Long-horizon V5 score-blind collection health summary

## Purpose

The long-horizon forward-evidence pipeline has several acquisition-integrity guards: source freshness, completed-bar age, stock-timeline integrity, benchmark alignment, OHLCV validity, and strict artifact provenance. The useful next step is to measure which guard actually limits genuine weekday coverage instead of adding speculative checks.

This utility summarizes collection health without inspecting model probabilities, directions, calibration, outcomes, or performance metrics.

## Population integrity

Operational health metrics are computed only from artifacts whose `acquisition_provenance.forward_eligible` value is the boolean `true`. Manual and diagnostic artifacts are counted in `ignored_non_forward_run_count` but do not contribute to status counts, coverage, failure reasons, affected symbols, or complete-run counts.

This distinction is required because mixing diagnostic runs into genuine forward evidence can distort the measured bottleneck. Missing, malformed, or non-boolean forward-eligibility provenance fails closed rather than being guessed.

## Coverage integrity

Forward-eligible artifacts are now validated before they can affect health telemetry. The summarizer reconstructs the expected symbol/horizon geometry from `symbols_requested` and `session_gate.eligible_horizons`, then requires all coverage metadata to agree with that geometry.

It fails closed when any of the following is inconsistent or malformed:

- unsupported or duplicate eligible horizons;
- duplicate or empty requested symbols;
- non-score-blind coverage metadata;
- negative/non-integer expected or observed counts;
- expected count that disagrees with the symbol/horizon cross-product;
- unexpected or duplicate entries in `missing_pairs`;
- observed count that disagrees with expected minus missing pairs;
- a `complete` flag that disagrees with `missing_pairs`;
- completed/degraded/skipped status semantics that disagree with coverage;
- a failure entry for a symbol outside `symbols_requested`.

This prevents a damaged or partially-written prediction artifact from creating a believable but incorrect operational bottleneck report.

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

The output contract is `orion-long-horizon-v5-collection-health-v3`, is explicitly marked `score_blind: true`, and declares `population: forward_eligible_only`.

Input files must use the paired-shadow contract `orion-long-horizon-v5-paired-shadow-v1`; unexpected contracts fail closed.

## Scheduled integration

The long-horizon evidence-cycle workflow recovers only authenticated scheduled paired-shadow prediction artifacts and now builds the aggregate collection-health summary from that exact recovered population before settlement. When at least one prediction artifact is recovered, the workflow uploads a dedicated `long-horizon-v5-collection-health-<run_id>` artifact. A malformed forward artifact therefore fails the health projection before its operational telemetry can be reported as trustworthy.

The health artifact remains score-blind and separate from the cumulative evidence ledger and model-performance decision. It is intended to answer only whether the collection pipeline is healthy enough to support later outcome analysis.

## Verification

Focused tests cover forward-only aggregation, exclusion of non-forward diagnostic data, normalization of dynamic failure detail, exclusion of model probabilities, ambiguous provenance, unexpected input contracts, and the coverage-integrity invariants above. Collection-health CI also verifies that the scheduled evidence-cycle invokes the summarizer over the recovered prediction set and uploads the resulting health artifact.

## Next evidence step

Use the first genuine weekday evidence-cycle artifact to inspect validated forward-eligible reason counts and observed-pair rate. A recurring source-freshness or completed-bar problem should lead to provider/workflow timing investigation; timeline, OHLCV, or benchmark-alignment failures should lead to ingestion-quality investigation. If coverage is healthy, return to leakage-safe model validation and calibration rather than adding more acquisition guards. Do not relax a guard solely to improve coverage.
