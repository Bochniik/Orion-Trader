# Long-horizon V5 score-blind collection health summary

## Purpose

The long-horizon forward-evidence pipeline has several acquisition-integrity guards: source freshness, completed-bar age, stock-timeline integrity, benchmark alignment, OHLCV validity, and strict artifact provenance. The useful next step is to measure which guard actually limits genuine weekday coverage instead of adding speculative checks.

This utility summarizes collection health without inspecting model probabilities, directions, calibration, outcomes, or performance metrics.

## Population integrity

Operational health metrics are computed only from artifacts whose `acquisition_provenance.forward_eligible` value is the boolean `true`. Manual and diagnostic artifacts are counted in `ignored_non_forward_run_count` but do not contribute to status counts, coverage, failure reasons, affected symbols, complete-run counts, or horizon-specific health.

This distinction is required because mixing diagnostic runs into genuine forward evidence can distort the measured bottleneck. Missing, malformed, or non-boolean forward-eligibility provenance fails closed rather than being guessed.

## Coverage integrity

Forward-eligible artifacts are validated before they can affect health telemetry. The summarizer reconstructs the expected symbol/horizon geometry from `symbols_requested` and `session_gate.eligible_horizons`, then requires all coverage metadata to agree with that geometry.

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

## Horizon-specific health

Overall pair coverage is not sufficient for this protocol. The frozen schedule can produce multiple settleable `3h` observations per session but only a narrow `5h` opportunity. A healthy aggregate rate can therefore hide systematic loss of the horizon that is slowest to mature.

Contract v4 derives a score-blind `coverage.by_horizon` projection directly from the already-validated symbol/horizon geometry and `missing_pairs`. For both `3h` and `5h` it reports:

- eligible run count;
- complete run count;
- expected pair count;
- observed pair count;
- missing pair count;
- observed pair rate, or `null` when that horizon has not yet been eligible.

The `5h` projection is also copied to the explicit top-level `critical_5h` field so the pre-registered bottleneck can be inspected without combining it with denser `3h` evidence. This is collection telemetry only; it does not inspect outcomes or change maturity thresholds.

This distinction matters operationally. A report can legitimately show a high overall observed-pair rate and 100% `3h` coverage while `critical_5h.observed_pair_rate` is poor or zero. Such a result means the forward dataset is not yet healthy enough for balanced long-horizon validation even though aggregate coverage looks reassuring.

## Whole-run recovery integrity

Pair coverage can only describe prediction artifacts that actually exist. A scheduled GitHub Actions collection run can fail, be cancelled, or otherwise complete without producing a recoverable prediction artifact. Before this milestone such a whole-run loss was invisible to the aggregate collection-health report, because the evidence cycle built health only from artifacts it successfully recovered.

`scripts/summarize_long_horizon_v5_run_recovery_health.py` closes that observability gap without inspecting predictions. The evidence cycle obtains the authoritative scheduled workflow-run population from GitHub Actions for the same 35-day recovery window and compares completed scheduled run IDs with the IDs of prediction artifacts that passed the existing provenance checks.

The score-blind recovery contract `orion-long-horizon-v5-run-recovery-health-v1` reports:

- completed scheduled run count;
- pending scheduled run count, excluded from the denominator;
- authenticated recovered prediction-artifact run count;
- missing prediction-artifact run count;
- recovery rate, or `null` when no completed scheduled runs exist;
- missing-run counts by workflow conclusion;
- run ID, creation timestamp, and conclusion for each missing completed scheduled run.

Manual `workflow_dispatch` runs are excluded from the forward population. Runs before the exact recovery cutoff are excluded, and recovered artifacts outside that population are counted separately rather than creating false missing-run conclusions at the time boundary. Duplicate run IDs, malformed IDs, timestamps, or completed runs without conclusions fail closed.

This telemetry is intentionally independent from model output. It never traverses prediction payloads, probabilities, directions, outcomes, calibration, or performance. Its only question is whether each completed scheduled collection attempt left an authenticated recoverable artifact.

## Output

`scripts/summarize_long_horizon_v5_collection_health.py` accepts one or more paired prediction JSON artifacts and emits only operational fields:

- total input count, forward-eligible count, and ignored non-forward count;
- forward-only run/status counts;
- forward-only complete-run count;
- forward-only aggregate expected and observed pair counts plus observed-pair rate;
- validated per-horizon coverage for `3h` and `5h`;
- explicit `critical_5h` coverage;
- forward-only normalized failure reason counts;
- forward-only affected symbols by normalized failure reason.

Dynamic text after the first `:` in a failure value is discarded. This keeps values such as timestamp mismatches, ages, provider exception details, and other diagnostic payload text out of the aggregate report.

The summarizer never traverses `paired_predictions`, so incumbent/challenger probabilities cannot affect or leak into the health result.

## Contract

The pair-level output contract is `orion-long-horizon-v5-collection-health-v4`, is explicitly marked `score_blind: true`, and declares `population: forward_eligible_only`.

The workflow-level recovery output contract is `orion-long-horizon-v5-run-recovery-health-v1`, is explicitly marked `score_blind: true`, and declares `population: completed_scheduled_shadow_runs`.

Input prediction files must use the paired-shadow contract `orion-long-horizon-v5-paired-shadow-v1`; unexpected contracts fail closed.

## Scheduled integration

The long-horizon evidence-cycle workflow recovers only authenticated scheduled paired-shadow prediction artifacts. It now records the exact recovered producer run IDs, queries the authoritative scheduled producer workflow-run population for the same cutoff, and builds the run-recovery health report even when zero prediction artifacts were recovered. This is important because zero recovered artifacts is itself a possible reliability signal and must not suppress telemetry.

When prediction artifacts exist, the workflow also builds the aggregate pair-level collection-health summary from that exact recovered population before settlement. Both health reports are uploaded as dedicated 90-day artifacts with `if-no-files-found: error` after successful recovery processing.

The health artifacts remain score-blind and separate from the cumulative evidence ledger and model-performance decision. They are intended to answer only whether the collection pipeline is healthy enough to support later outcome analysis.

## Verification

Focused tests cover forward-only pair aggregation, exclusion of non-forward diagnostic data, normalization of dynamic failure detail, exclusion of model probabilities, ambiguous provenance, unexpected input contracts, and the coverage-integrity invariants above. Additional regressions prove that horizon-specific accounting is reconstructed from validated `missing_pairs`, that a high aggregate rate cannot hide total `5h` loss, and that horizons with no eligible runs report `null` rather than a fabricated zero-rate conclusion.

Run-recovery regressions cover missing artifacts from successful/failed/cancelled completed scheduled runs, exclusion of manual and still-running jobs, exact cutoff handling, null-rate semantics before any completed run exists, duplicate-ID rejection, malformed completed-run rejection, and projection of only score-blind workflow metadata. Collection-health CI also verifies that scheduled run recovery is built and uploaded before settlement.

## Operational evidence noted during audit

A genuine scheduled paired-shadow artifact from 2026-09-11 at 13:43 ET was correctly classified as `outside_long_horizon_shadow_window` and contained no prediction pairs. This is not model evidence. More importantly, it illustrates why workflow-level success and aggregate pair counts cannot substitute for horizon-aware collection telemetry: scheduled invocations can exist without contributing to the scarce `5h` population.

The inverse failure mode is now measured as well: a completed scheduled workflow that never leaves a recoverable prediction artifact can no longer silently disappear from health accounting.

The frozen collection schedule is intentionally left unchanged by this milestone. Changing sampling times after registration would alter forward-evidence geometry. The correct first response is to measure whether the existing critical `5h` opportunity and its producer workflow are actually captured reliably.

## Next evidence step

Use the first genuine weekday evidence-cycle artifacts to inspect both workflow-level `recovery_rate` and pair-level `coverage.by_horizon`, especially `critical_5h`. If run recovery is below 100%, investigate the missing run conclusions and GitHub Actions/provider failure path before interpreting pair coverage. If run recovery is healthy but `3h` or `5h` pair coverage is degraded, use the existing normalized failure reasons to isolate provider/timing or ingestion-quality causes. If both recovery and horizon-specific coverage are healthy, return to leakage-safe model validation and calibration rather than adding more acquisition guards. Do not relax a guard solely to improve coverage.
