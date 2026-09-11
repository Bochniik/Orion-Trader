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

The runner now applies the same settlement geometry before inference. A scheduled slot with no settleable horizon is a score-blind `skipped` run rather than a failed collection run. For an eligible slot, the runner records the exact expected `(symbol, horizon)` coverage and marks the run `degraded` if any expected pair is missing. This prevents harmless late cron slots from producing false failures while making real evidence loss visible immediately.

The incumbent's underlying calibrated V3.1 probability is retained for research comparison even when the product UI would suppress display of that horizon. The evidence record marks that fact with `was_runtime_suppressed`; no suppressed probability is surfaced to runtime UI by this milestone.

## Evidence integrity

Prediction artifacts include Git/file lineage and are immutable GitHub Actions artifacts. Settlement uses bounded 1-minute outcome windows from the existing Alpaca IEX market-data path, after the full horizon has elapsed. Incumbent and challenger are settled against the same prediction timestamp and realized outcome.

Settled records are accumulated through the existing append-only evidence ledger implementation. A dedicated long-horizon ledger is used to avoid races with the existing premarket/regular-hours evidence cycle. Duplicate records are idempotent; conflicting material values for the same identity fail closed.

Every newly written ledger is now integrity-sealed. Each record carries deterministic `record_id` and `material_sha256` values, while the ledger carries a SHA-256 fingerprint over the sorted `(record_id, material_sha256)` set plus the expected record count. Recovery validates stored record fingerprints, the cumulative record count, and the ledger-level digest before any prior ledger is accepted as the base for a new cycle. A modified or truncated sealed ledger therefore fails closed instead of silently becoming a shorter "append-only" history. Legacy unsealed ledgers remain readable only for migration; the next successful build seals them automatically.

The dedicated V5 evidence cycle invokes both the settlement layer and the accumulator with `--score-blind-summary`. Raw settled records retain the probabilities and outcomes required for the eventual frozen tournament, but pre-maturity settlement summaries, ledger summaries and CI stdout expose only collection/settlement coverage plus `score_blind=true` and `metrics_exposed=false`. Brier score, log loss, directional accuracy, ECE, probabilities and realized labels are deliberately omitted from operational summaries. The generic settlement/accumulator behavior remains backward-compatible when score-blind mode is not requested.

The raw settlement records and raw ledger are research evidence, not progress dashboards. They should not be inspected to make an outcome-driven stop/tune decision before both pre-registered maturity gates are satisfied. The score-blind operational summaries exist so collection health can be monitored without revealing model performance.

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

## Score-blind collection-capacity audit

`scripts/audit_long_horizon_v5_collection_capacity.py` audits the scheduled forward collection geometry without reading predictions, outcomes, Brier scores or log loss. For a representative session date it converts the UTC cron window to America/New_York, applies the 10:00-13:30 collection gate and the 16:00 settlement boundary, then reports the maximum paired-observation capacity implied by the frozen schedule and symbol count.

For the 10-symbol frozen universe on 2026-09-11, the current schedule has three settleable `3h` snapshots per session (30 possible pairs/session) but only one settleable `5h` snapshot per session (10 possible pairs/session). Therefore the `5h` horizon reaches exactly 80 possible pairs after the minimum 8 sessions only under complete symbol coverage. Any missed symbol/run means the 5h sample legitimately remains immature beyond session 8; this must be treated as collection readiness, not model failure. The audit also has a regression check across the EDT/EST transition so UTC scheduling drift cannot silently change the evidence geometry.

This audit does not change the pre-registered 80-observation or 8-session thresholds. It exists to diagnose collection reliability before any outcome-dependent interpretation.

## Score-blind collection-health audit

`scripts/audit_long_horizon_v5_collection_health.py` consumes paired prediction artifacts but deliberately projects only top-level operational metadata: run status, ET session timestamp, eligible horizons, requested symbols, expected/observed pair counts and explicit `missing_pairs`. It never reads `paired_predictions`, probabilities, directions, realized outcomes, Brier score, log loss, directional accuracy or ECE.

The report aggregates total and per-horizon coverage, missing-pair counts by symbol, distinct collection sessions, skip reasons and a dedicated `critical_5h` view. This makes the single settleable 5h slot measurable without exposing interim model performance. An operational SHA-256 fingerprint is computed from the canonical score-blind projections so repeating the audit over the same collection geometry is deterministic.

The production paired-shadow workflow runs this diagnostic even when the prediction runner exits degraded, then uploads the health JSON beside the immutable prediction artifact. The audit fails closed if the artifact contract is unexpected, `coverage.score_blind` is not true, pair counts disagree with the requested symbol/horizon geometry, or status/coverage semantics are inconsistent. Regression tests verify that changing probabilities, directions or injected outcome/score fields cannot change the health report.

Collection health is not a model-quality metric and does not change the 80-observation/8-session maturity gate. A degraded collection run means evidence is missing and may require more sessions; it is neither evidence for nor against V5.

## Reproducibility

Every readiness/decision artifact records the SHA-256 of the exact cumulative ledger it evaluated. Re-running the builder against the same ledger therefore ties the conclusion to a concrete immutable evidence state. Pairing and ordering are deterministic. The cumulative ledger itself also carries an independent deterministic records digest, so corruption or truncation is detected before the next accumulation cycle.

## Next logical step

Let the append-only forward ledger accumulate untouched observations until both pre-registered horizon gates are mature. Track the score-blind collection-health report, settled-observation counts and distinct-session counts alongside the capacity audit so operational data loss is separated from model performance. In particular, verify whether the critical 10:05 ET 5h collection consistently reaches 10/10 symbol coverage; if it does not, fix market-data/inference reliability rather than changing thresholds. Do not tune V5 or change thresholds based on interim outcomes. Once a mature decision artifact exists, review the paired session-block tournament; a failure should reject this frozen V5, while a pass should move only to an explicit research-review step before any runtime consideration.
