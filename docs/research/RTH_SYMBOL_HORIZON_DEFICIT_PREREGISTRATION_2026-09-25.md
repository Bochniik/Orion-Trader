# RTH symbol × horizon deficit replication preregistration

Status: research-only; no runtime or promotion effect.

## Development evidence boundary

This preregistration freezes two hypotheses discovered from settled regular-hours evidence available through 2026-09-24. Those observations are development evidence only and MUST NOT be used to approve a challenger influenced by these hypotheses.

Frozen hypotheses:

1. `NVDA × 1h`: the incumbent regular-hours model has worse leakage-safe proper scores than the chronological expanding prior.
2. `GOOGL × 30m`: the incumbent regular-hours model has worse leakage-safe proper scores than the chronological expanding prior.

The discovery snapshot contained 10 distinct settled sessions for each named symbol × horizon slice. The exact observed score deltas are diagnostic context, not acceptance thresholds.

## Replication cohort

Only genuinely new settled observations after the development boundary may count toward replication. A replication decision requires at least 10 distinct post-boundary sessions for each named slice. Do not stop collection early because intermediate scores look favorable or unfavorable.

Any malformed, non-point-in-time, stale, recovered-without-provenance, or otherwise ineligible observation remains excluded under the existing regular-hours evidence rules.

## Frozen replication question

For each hypothesis independently, compare the incumbent against the same leakage-safe chronological expanding prior used by the RTH proper-score diagnostic.

A deficit is considered replicated only if BOTH post-boundary proper-score deltas are worse than the prior:

- `model_brier - prior_brier > 0`
- `model_log_loss - prior_log_loss > 0`

after the minimum 10 distinct post-boundary sessions are available.

If either delta is <= 0 at that maturity point, the deficit is not replicated and no specialist candidate should be justified from this hypothesis.

No accuracy-only criterion may override the proper-score result.

## Anti-leakage / model-change rule

This document does not define or approve a model change. During the replication cohort:

- do not tune the incumbent to these two slices;
- do not alter calibration or decision thresholds because of intermediate replication outcomes;
- do not create symbol-specific runtime overrides;
- do not promote a challenger automatically.

If a deficit replicates, the next step is a NEW immutable challenger registration with its own exact change summary, code/model lineage and strictly later forward cutoff. The replication observations then become development evidence for that new candidate and cannot approve it.

If the deficit does not replicate, record the rejection and retain the incumbent.

## Relationship to the adaptive research loop

This preregistration is a replication screen before candidate design. The existing immutable challenger registry and registered tournament remain authoritative for any later evidence-informed candidate. Production inference, risk policy, broker behavior and order paths are unchanged.
