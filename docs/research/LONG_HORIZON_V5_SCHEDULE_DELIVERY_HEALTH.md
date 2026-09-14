# Long-horizon V5 scheduled workflow delivery health

## Why this exists

The long-horizon forward pipeline already measures two downstream acquisition layers:

1. completed scheduled workflow run -> authenticated prediction artifact (`run-recovery health`), and
2. authenticated forward artifact -> expected symbol/horizon pairs (`collection health`).

Those metrics cannot detect a third failure mode: an expected GitHub Actions cron invocation that is never created. If the scheduler omits a run entirely, there is no workflow-run ID for the run-recovery metric to count, so artifact recovery can appear to be 100% even though a frozen collection slot never happened.

This matters especially for the scarce `5h` evidence path, where losing a collection opportunity has a larger effect on time-to-maturity than losing one of the denser `3h` opportunities.

## Contract

`scripts/audit_long_horizon_v5_schedule_delivery.py` emits `orion-long-horizon-v5-schedule-delivery-v1`.

The report is explicitly `score_blind: true` and does not read prediction artifacts, probabilities, directions, labels, outcomes, calibration, or performance. It compares only frozen expected GitHub schedule slots with authoritative `event=schedule` workflow-run metadata.

The frozen producer cron remains unchanged:

```text
5 14-19 * * 1-5
```

The audit does not fabricate pre-protocol misses. Expected slots begin no earlier than the deployment of the scheduled paired-shadow producer in #32 (`2026-09-11T05:10:00Z`).

A slot enters the denominator only after a 20-minute maturity grace period. An observed scheduled run may match its expected slot when GitHub creates it up to 55 minutes late. Delays beyond that bound are intentionally treated as a missing expected slot plus an unexpected run rather than ambiguously assigning a run across adjacent hourly cron slots.

## Output

The report exposes only operational fields:

- expected, delivered, and missing mature schedule-slot counts;
- schedule-delivery rate, or `null` before any mature slot exists;
- conclusion counts for delivered runs;
- per-UTC-slot delivery health for each frozen `14:05Z` through `19:05Z` slot;
- exact missing slot timestamps;
- unmatched scheduled runs that cannot be assigned safely to a mature expected slot.

Per-slot health prevents strong aggregate delivery from hiding a systematically missing hour that could disproportionately affect a particular horizon.

## Evidence-cycle integration

The scheduled evidence cycle already queries authoritative scheduled producer runs for the same 35-day recovery window. It now reuses that population to build schedule-delivery health before run-recovery health, settlement, or model evaluation.

The resulting artifact is uploaded as:

```text
long-horizon-v5-schedule-delivery-health-<evidence-cycle-run-id>
```

with 90-day retention and `if-no-files-found: error`.

The three operational layers should be interpreted in order:

1. **schedule delivery** — did GitHub create the expected frozen cron invocation?
2. **run recovery** — did the completed scheduled invocation leave an authenticated recoverable prediction artifact?
3. **pair coverage** — did that authenticated forward artifact contain the expected symbol/horizon geometry?

A failure at an earlier layer should be investigated before interpreting a later-layer rate.

## Verification

Focused regressions cover protocol activation, weekend exclusion, complete delivery, a single missing slot, per-hour visibility, bounded scheduler delay, beyond-tolerance runs, immature-slot exclusion, duplicate run IDs, non-scheduled input rejection, null-rate semantics before activation, and absence of model fields from the report.

Collection-health CI compiles the new auditor and runs its regressions together with the existing run-recovery and pair-coverage suites. Workflow-wiring assertions require schedule-delivery health to be built before run-recovery health and settlement.

## Next evidence step

Do not change the frozen collection schedule to improve this metric. On the next genuine weekday evidence cycle, inspect `schedule_delivery_rate` first, then `recovery_rate`, then horizon-specific pair coverage (`3h` and `critical_5h`). If schedule delivery is incomplete, diagnose GitHub scheduling/orchestration before touching ingestion or model code. If delivery and recovery are healthy but pair coverage is degraded, use the existing normalized data-quality failure reasons. If all three layers are healthy, return to leakage-safe forward validation and calibration when the pre-registered maturity gates are satisfied.
