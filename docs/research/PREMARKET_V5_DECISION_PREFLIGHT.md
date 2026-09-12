# Premarket V5 Decision Preflight

Status: research validation safety gate. This does not modify runtime prediction behavior, calibration profiles, thresholds, risk policy, broker integration, or order paths.

## Purpose

Premarket V5 decision-grade validation must not run merely because a CSV exists or because one audit passes. The exact dataset must satisfy both independent requirements:

1. **Provenance:** the dataset is content-addressed back to the recorded Alpaca 1-minute raw source and collection manifest through the accepted dataset builder lineage.
2. **Readiness:** the dataset has valid prediction-time identity, premarket timestamps, feature coverage, target labels, no cross-open target leakage, and enough sessions for the preregistered 40-day train + 10-day calibration + 5-day test policy.

`scripts/run_premarket_v5_decision_preflight.py` composes those gates without weakening either one. `decision_grade_validation_allowed=true` only when both reports return `PASS`.

## Fail-closed behavior

A missing/tampered lineage artifact, unsupported collector/builder contract, unreadable CSV, malformed prediction-time fields, target leakage, or insufficient session coverage blocks event-nested model validation. A failure in one gate cannot be overridden by success in the other.

The preflight report embeds both underlying audit reports so the blocker remains diagnosable and reproducible. It also hard-codes `runtime_modified=false` and `promotion_authorized=false`: passing preflight authorizes only the next research step, not deployment.

## Next step after PASS

Only a passing dataset should proceed to the existing Premarket V5 event-nested validation path. That validation must still satisfy Issue #3's proper-score, calibration, fold-stability and baseline requirements before any later promotion proposal is considered.
