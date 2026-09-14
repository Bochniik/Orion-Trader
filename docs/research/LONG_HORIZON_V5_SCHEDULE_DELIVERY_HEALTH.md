# Long-horizon V5 scheduled workflow delivery health

## Why this exists

The long-horizon forward pipeline measures three acquisition layers:

1. expected GitHub cron slot -> scheduled workflow run (`schedule-delivery health`),
2. completed scheduled workflow run -> authenticated prediction artifact (`run-recovery health`), and
3. authenticated forward artifact -> expected symbol/horizon pairs (`collection health`).

The first version of schedule-delivery health intentionally measured every frozen UTC cron slot. That is useful for GitHub scheduler transport health, but it is not sufficient to measure lost forward-evidence opportunities. The producer cron spans six UTC hours so the same workflow can cover the New York collection window across daylight-saving transitions. Only a subset of those cron invocations can actually create a settleable `3h` or `5h` prediction.

A raw missing support slot therefore must not be treated as equivalent to losing a genuine forward-evidence opportunity. Conversely, a delivered GitHub run can arrive too late to preserve the horizon that the nominal slot was intended to collect. V2 adds a market-relative, DST-safe evidence-opportunity layer without changing the frozen producer schedule.

## Contract

`scripts/audit_long_horizon_v5_schedule_delivery.py` emits `orion-long-horizon-v5-schedule-delivery-v2`.

The report is explicitly `score_blind: true` and does not read prediction artifacts, probabilities, directions, labels, outcomes, calibration, or performance. It compares only frozen expected GitHub schedule slots with authoritative `event=schedule` workflow-run metadata and deterministic market-time eligibility.

The frozen producer cron remains unchanged:

```text
5 14-19 * * 1-5
```

The audit does not fabricate pre-protocol misses. Expected slots begin no earlier than the deployment of the scheduled paired-shadow producer in #32 (`2026-09-11T05:10:00Z`).

A raw cron slot enters the denominator only after a 20-minute maturity grace period. An observed scheduled run may match its expected slot when GitHub creates it up to 55 minutes late. Delays beyond that bound are intentionally treated as a missing expected slot plus an unexpected run rather than ambiguously assigning a run across adjacent hourly cron slots.

## Market-relative evidence opportunities

`America/New_York` is authoritative for horizon eligibility. A nominal or delivered run is evidence-eligible only on a weekday inside the frozen `10:00-13:30 ET` collection window, and its target horizon must settle no later than the `16:00 ET` regular-session close.

For each expected cron slot, the report records:

- the nominal UTC and New York timestamps;
- `expected_eligible_horizons` at the nominal slot;
- the actual run creation time when delivered;
- `effective_eligible_horizons` at the actual creation time; and
- any `lost_eligible_horizons` caused by a missing or sufficiently delayed invocation.

The aggregate `evidence_opportunities` section exposes `expected_opportunity_count`, `effective_delivery_count`, `lost_opportunity_count`, `effective_delivery_rate`, and exact lost nominal slots independently for `3h` and `5h`. `critical_5h` is a direct alias of the `5h` summary because the 5-hour path has the scarcest collection geometry.

This layer is DST-safe. During U.S. daylight time the first useful slot is normally `14:05Z` (`10:05 ET`) and can preserve both `3h` and `5h`. During U.S. standard time the equivalent market-relative opportunity shifts to `15:05Z`. The broad UTC cron itself remains unchanged, so this interpretation does not alter pre-registered collection geometry.

## Raw scheduler output

The original transport metrics remain available because they answer a different operational question:

- expected, delivered, and missing mature cron-slot counts;
- raw `schedule_delivery_rate`, or `null` before any mature slot exists;
- conclusion counts for delivered runs;
- per-UTC-slot delivery health for each frozen `14:05Z` through `19:05Z` slot;
- exact missing slot timestamps; and
- unmatched scheduled runs that cannot be assigned safely to a mature expected slot.

A support-only UTC slot can therefore reduce raw `schedule_delivery_rate` without reducing `3h` or `critical_5h` evidence-opportunity delivery. This separation prevents scheduler transport noise from being misdiagnosed as lost model evidence.

## Evidence-cycle integration

The scheduled evidence cycle queries authoritative scheduled producer runs for the same recovery window and builds schedule-delivery health before run-recovery health, settlement, or model evaluation.

The resulting artifact is uploaded as:

```text
long-horizon-v5-schedule-delivery-health-<evidence-cycle-run-id>
```

with 90-day retention and `if-no-files-found: error`.

Operational health should now be interpreted in this order:

1. **raw schedule transport** — did GitHub create the expected frozen cron invocation?
2. **effective horizon opportunity delivery** — did the scheduled invocation exist soon enough, in New York market time, to preserve the intended `3h`/`5h` evidence opportunity?
3. **run recovery** — did the completed scheduled invocation leave an authenticated recoverable prediction artifact?
4. **pair coverage** — did that authenticated forward artifact contain the expected symbol/horizon geometry?

A failure at an earlier evidence-relevant layer should be investigated before interpreting a later-layer rate.

## Verification

Focused regressions cover protocol activation, weekend exclusion, complete raw delivery, support-only slot loss, critical 5h slot loss, horizon-specific opportunity rates, U.S. daylight/standard-time transitions, bounded scheduler delay, horizon preservation under delay, beyond-tolerance runs, immature-slot exclusion, duplicate run IDs, non-scheduled input rejection, null-rate semantics before activation, and absence of model fields from the report.

Collection-health CI compiles the auditor and runs its regressions together with the existing run-recovery and pair-coverage suites. Workflow-wiring assertions continue to require schedule-delivery health before run-recovery health and settlement.

## Next evidence step

Do not change the frozen collection schedule to improve these metrics. On the next genuine weekday evidence cycle, inspect raw `schedule_delivery_rate`, then `evidence_opportunities.3h.effective_delivery_rate` and `critical_5h.effective_delivery_rate`, then `recovery_rate`, and finally horizon-specific pair coverage. A raw support-slot miss with intact evidence-opportunity delivery is scheduler noise rather than a lost prediction opportunity. A lost 3h/5h opportunity should be diagnosed in GitHub scheduling/orchestration before touching ingestion or model code. If effective delivery, recovery, and pair coverage are healthy, return to leakage-safe forward validation and calibration when the pre-registered maturity gates are satisfied.
