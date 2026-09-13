# Long-horizon V5 recovery population

Date fixed: 2026-09-13

## Problem

The paired prediction workflow supports both scheduled collection and manual `workflow_dispatch` diagnostics, and both execution modes upload artifacts under the `long-horizon-v5-paired-shadow-<run_id>` namespace.

The evidence-cycle recovery loop previously selected artifacts by namespace and age before authenticating the producing workflow run. `validate_long_horizon_v5_artifact_origin.py` correctly rejects any prediction whose GitHub run event is not `schedule`, but that meant a legitimate manual diagnostic artifact could abort the entire scheduled settlement cycle instead of simply being excluded from the genuine forward population.

## Recovery rule

Prediction recovery now fetches the authoritative GitHub Actions run metadata after binding artifact run ID and head SHA. If the producing run event is not `schedule`, that artifact is skipped before download, settlement, ledger accumulation, and readiness evaluation.

Scheduled artifacts are not weakened by this change. They continue through the existing strict origin validator, which requires the expected workflow path, successful completed run, exact run attempt, exact head SHA, scheduled acquisition provenance, `forward_eligible=true`, verified workflow commit lineage, and matching payload lineage.

The prior cumulative ledger already used the same population rule: non-scheduled ledger-producing runs are skipped before recovery. The prediction path now follows the same semantics.

## Safety and leakage properties

- Manual or diagnostic predictions cannot enter the append-only forward ledger.
- A manual diagnostic run cannot block later scheduled settlement merely because its artifact is still retained.
- A malformed or provenance-invalid artifact from an actual scheduled run still fails closed.
- No probabilities, realized outcomes, model scores, calibration values, thresholds, risk rules, providers, broker behavior, or order paths are changed.

## Verification

The focused forward-shadow CI statically verifies that the non-scheduled event filter exists and is executed before prediction artifact download. Existing origin-validator tests continue to require rejection of non-scheduled artifacts when validation is invoked, preserving defense in depth.

## Next evidence step

Allow the first genuine weekday collection and evidence-cycle runs to execute with this recovery population rule. Use the forward-only collection-health summary to measure coverage and failure categories. Do not change collection guards or model thresholds based on diagnostic/manual artifacts or interim model outcomes.
