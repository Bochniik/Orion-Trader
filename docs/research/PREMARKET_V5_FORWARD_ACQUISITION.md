# Premarket V5 forward acquisition provenance

## Purpose

Issue #3 requires genuinely point-in-time evidence, not merely a historical reconstruction that was clipped to a past `as_of` timestamp. A causal data cutoff is necessary, but by itself it does not prove when the data were acquired.

The scheduled Premarket V5 path therefore records and validates acquisition provenance before an artifact may count toward decision-grade readiness.

## Frozen policy

The policy is score-blind and was fixed before the next eligible three-snapshot trading session after this change.

A prediction artifact counts as decision-grade forward evidence only when all of the following are true:

- the artifact remains `shadow_research_only`;
- order submission is disabled;
- the causal cutoff is enforced;
- the GitHub event is `schedule` rather than manual dispatch;
- collection starts no more than 2 minutes before the preregistered prediction timestamp;
- collection starts no more than 20 minutes after that timestamp;
- GitHub run ID and positive run attempt are present;
- the prediction payload still matches the SHA-256 identity captured before acquisition provenance was attached;
- the ordinary collection-health checks also consider the forecast artifact complete.

A late or manually generated artifact may remain useful for diagnostics, but it does **not** count toward the 55 complete-session requirement for early, mid, or late snapshots.

## Evidence flow

The scheduled workflow now follows this order:

1. resolve the preregistered early/mid/late target;
2. capture `collection_started_at_utc` before the market-data request;
3. run the existing causal Premarket V5 shadow prediction;
4. capture `collection_completed_at_utc`;
5. attach `orion-premarket-v5-forward-acquisition-v1` provenance;
6. upload the immutable prediction artifact.

`scripts/audit_premarket_v5_forward_readiness.py` then recomputes the timing classification, verifies the pre-attestation payload hash, checks the frozen timing policy, and combines it with the existing operational collection-health projection.

The resulting readiness report exposes no Brier score, log loss, realized outcome, probability, directional confidence, or other predictive-performance metric. Readiness remains independent of model quality so collection cannot stop early because observed scores look favorable or unfavorable.

## Issue #3 interpretation

`ready_for_issue_3_score_inspection=true` now means that every preregistered snapshot family (06:45, 08:00, 09:15 ET) contains at least 55 distinct sessions that are both operationally complete and acquisition-provenance eligible.

Historical/manual reconstructions and scheduled runs that start outside the frozen acquisition window are explicitly excluded from that count. They must never be relabeled as untouched forward evidence.

## Safety scope

This change does not modify model weights, calibration, thresholds, risk rules, symbols, Alpaca feed choice, broker behavior, or order paths. It only strengthens research-evidence provenance and readiness semantics.
