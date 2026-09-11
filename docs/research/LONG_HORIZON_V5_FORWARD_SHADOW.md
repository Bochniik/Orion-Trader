# Long-horizon V5 forward shadow protocol

Date fixed: 2026-09-11

This milestone connects the frozen `long-horizon-v5-20260911-a` challenger to a research-only forward evidence path. It does not modify OrionTrader runtime decisions, risk policy, thresholds, broker behavior, or order submission.

## Why this exists

The historical V5 screen was not decision-grade because the frozen 60d/5m geometry could not satisfy the pre-registered 80-observation coverage gate against V3.1. The forward gate therefore requires untouched post-registration observations and explicitly distinguishes an immature sample from model failure.

A valid forward comparison also needs truly paired observations. Running incumbent and challenger in unrelated jobs can create different timestamps and different settlement targets. This protocol therefore records both predictions atomically under one symbol/horizon/prediction timestamp.

## Frozen models and horizons

- Incumbent: `regular_hours_v3_1`.
- Challenger: `long-horizon-v5-20260911-a`.
- Required horizons: `3h` and `5h` only.
- The challenger implementation is imported unchanged; the new forward adapter only produces a causal point-in-time prediction from observed bars.
- Training rows retain the V5 horizon-resolution cutoff, so unresolved future outcomes cannot enter the daily fit.

## Settlement-safe prediction windows

The scheduled runner is gated to 10:00-13:30 America/New_York. Each individual horizon is additionally suppressed when its target timestamp would extend beyond the 16:00 regular-session close. This prevents forecasts that could never be settled on the regular-hours evidence feed from depressing coverage.

The incumbent's underlying calibrated V3.1 probability is retained for research comparison even when the product UI would suppress display of that horizon. The evidence record marks that fact with `was_runtime_suppressed`; no suppressed probability is surfaced to runtime UI by this milestone.

## Evidence integrity

Prediction artifacts include Git/file lineage and are immutable GitHub Actions artifacts. Settlement uses bounded 1-minute outcome windows from the existing Alpaca IEX market-data path, after the full horizon has elapsed. Incumbent and challenger are settled against the same prediction timestamp and realized outcome.

Settled records are accumulated through the existing append-only evidence ledger implementation. A dedicated long-horizon ledger is used to avoid races with the existing premarket/regular-hours evidence cycle. Duplicate records are idempotent; conflicting material values for the same identity fail closed.

The decision builder validates frozen model identities, paired-role lineage, supported horizons, timezone-aware timestamps, the pre-registration cutoff, pair completeness and exact realized settlement equality. Pair identity is `(symbol, horizon, prediction_time, target_time)`. The shared challenger tournament is symbol-aware, so simultaneous observations for AAPL, MSFT, NVDA or other universe members remain separate observations rather than conflicting timestamp duplicates.

Workflows have read-only repository permissions. The prediction payload explicitly carries `research_only=true`, `order_submission_enabled=false`, `runtime_modified=false`, and `promotion_allowed=false`.

## Score-blind maturity and decision rule

Do not inspect interim proper scores to decide when to stop collection. The deterministic ledger decision builder first evaluates only sample geometry:

- at least 80 complete incumbent/challenger pairs for `3h`;
- at least 80 complete incumbent/challenger pairs for `5h`;
- at least 8 distinct sessions for each horizon;
- every included observation at or after the fixed `2026-09-11T00:00:00Z` cutoff.

While either horizon is immature, the artifact reports `forward_holdout_collecting_evidence`, `decision_grade=false` and `metrics_exposed=false`. It does not invoke the proper-score tournament and does not emit Brier, log-loss or bootstrap deltas.

Only after both horizons are mature does the builder transform the append-only ledger into frozen incumbent/challenger tournament reports and call `evaluate_long_horizon_candidate(..., evidence_mode="forward_holdout")` with the pre-registered 80-observation, 8-session and 2000 session-block-bootstrap policy.

A mature forward failure rejects this frozen V5 unchanged. A mature pass grants research eligibility only; it does not authorize runtime promotion or live trading.

## Reproducibility

Every readiness/decision artifact records the SHA-256 of the exact cumulative ledger it evaluated. Re-running the builder against the same ledger therefore ties the conclusion to a concrete immutable evidence state. Pairing and ordering are deterministic.

## Next logical step

Let the append-only forward ledger accumulate untouched observations until both pre-registered horizon gates are mature. Do not tune V5 or change the thresholds based on interim results. Once a mature decision artifact exists, review the paired session-block tournament; a failure should reject this frozen V5, while a pass should move only to an explicit research-review step before any runtime consideration.