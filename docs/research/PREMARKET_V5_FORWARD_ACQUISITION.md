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

## Schedule-delivery completeness

Artifact readiness alone cannot distinguish a naturally young cohort from a GitHub schedule slot that was never delivered. The cloud-shadow workflow therefore gives every run an auditable name containing the exact `github.event.schedule` cron value.

`scripts/audit_premarket_v5_schedule_delivery.py` consumes GitHub Actions workflow-run metadata and reconstructs the preregistered NYSE trading-session geometry from the existing snapshot resolver. A slot becomes mature 20 minutes after its target timestamp, matching the latest start time that could still qualify as decision-grade forward acquisition.

For each mature early/mid/late slot the audit reports whether:

- a matching active DST-safe scheduled run was delivered;
- at least one matching run completed successfully;
- delivery is missing entirely;
- a delivered run failed/cancelled or otherwise did not succeed;
- duplicate active deliveries occurred.

Inactive DST duplicate schedules and manual workflow dispatches never satisfy delivery completeness. Future or not-yet-mature slots are excluded rather than being reported as failures. This keeps the audit score-blind and prevents a young cohort from being mistaken for an operational outage.

The schedule audit is intentionally separate from forward-readiness: a successful workflow run proves delivery, while the acquisition/readiness audit proves that the resulting prediction artifact itself is operationally complete, timely, scheduled, and payload-integrity bound. Both are needed to understand why Issue #3 evidence is or is not accumulating.

## Issue #3 interpretation

`ready_for_issue_3_score_inspection=true` means that every preregistered snapshot family (06:45, 08:00, 09:15 ET) contains at least 55 distinct sessions that are both operationally complete and acquisition-provenance eligible.

Historical/manual reconstructions and scheduled runs that start outside the frozen acquisition window are explicitly excluded from that count. They must never be relabeled as untouched forward evidence.

A schedule-delivery report with missing mature slots does not change model scores or promotion thresholds; it identifies evidence-acquisition debt that must be resolved or explicitly documented before the 55-session geometry can be considered operationally trustworthy.

## Safety scope

This change does not modify model weights, calibration, thresholds, risk rules, symbols, Alpaca feed choice, broker behavior, or order paths. It only strengthens research-evidence provenance, delivery observability, and readiness semantics.
