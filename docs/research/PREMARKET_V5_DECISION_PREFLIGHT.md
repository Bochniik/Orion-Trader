# Premarket V5 Decision Preflight

Status: research validation safety gate. This does not modify runtime prediction behavior, calibration profiles, thresholds, risk policy, broker integration, or order paths.

## Purpose

Premarket V5 decision-grade validation must not run merely because a CSV exists or because one audit passes. The exact dataset must satisfy both independent requirements:

1. **Provenance:** the dataset is content-addressed back to the recorded Alpaca 1-minute raw source and collection manifest through the accepted dataset builder lineage.
2. **Readiness:** the dataset has valid prediction-time identity, premarket timestamps, feature coverage, target labels, no cross-open target leakage, and enough sessions for the preregistered 40-day train + 10-day calibration + 5-day test policy.

`scripts/run_premarket_v5_decision_preflight.py` composes those gates without weakening either one. `decision_grade_validation_allowed=true` only when both reports return `PASS` and both the dataset CSV and its dataset manifest have immutable SHA-256 identities.

## Content-addressed handoff to validation

A passing audit is not sufficient if the validator can later be pointed at different bytes. The preflight contract therefore records:

- SHA-256 of the exact dataset CSV;
- SHA-256 of the exact dataset lineage manifest;
- the complete provenance and readiness reports that authorized the research step.

`scripts/run_premarket_v5_validation.py` requires an explicit `--preflight` artifact. Before invoking the event-nested validator it recomputes the dataset and manifest hashes and requires exact equality with the preflight identities. A missing, failed, unsupported or stale preflight fails closed before model evaluation begins.

The validation manifest then records the SHA-256 of the preflight artifact alongside the dataset, validation report and research-gate hashes. This creates one auditable chain:

`raw collection -> dataset manifest -> dataset -> PASS preflight -> event-nested validation -> research gate`

The evidence pipeline routes through this chain automatically; it no longer has a decision-grade path that can skip the preflight binding.

## Fail-closed behavior

A missing/tampered lineage artifact, unsupported collector/builder contract, unreadable CSV, malformed prediction-time fields, target leakage, insufficient session coverage, stale preflight, or any dataset/manifest change after preflight blocks event-nested model validation. A failure in one gate cannot be overridden by success in the other.

The preflight report embeds both underlying audit reports so the blocker remains diagnosable and reproducible. It also hard-codes `runtime_modified=false` and `promotion_authorized=false`: passing preflight authorizes only the next research step, not deployment.

## Next step after PASS

Only the exact content-addressed dataset referenced by a passing preflight may proceed to Premarket V5 event-nested validation. That validation must still satisfy Issue #3's proper-score, calibration, fold-stability and baseline requirements before any later promotion proposal is considered.
