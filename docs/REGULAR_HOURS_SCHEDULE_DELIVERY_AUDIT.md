# Regular-hours schedule delivery audit

This diagnostic separates GitHub Actions schedule delivery reliability from Orion's analytical runtime quality.

## Why it exists

A cloud-shadow workflow can finish successfully even when GitHub starts the scheduled job well after its intended cron slot. A late start may cause the existing New York session gate to skip the model, but a green workflow alone does not explain whether the engine failed or the scheduler delivered the job late.

## Contract

`scripts/audit_regular_hours_schedule_delivery.py` emits `orion-regular-hours-schedule-delivery-v1` before every Regular-hours V3.1 cloud-shadow prediction.

For scheduled runs it records:

- the cron expression and inferred intended UTC slot;
- intended and observed timestamps in UTC and America/New_York;
- delivery delay in minutes;
- `on_time`, `delayed`, or `severely_delayed` classification;
- whether the intended slot was inside Orion's 09:30-15:30 ET research window;
- `missed_regular_window=true` only when an in-session intended observation was delivered after the valid prediction window.

Manual workflow dispatches are explicitly marked `manual_dispatch`; they do not receive fabricated scheduler-delay values.

The thresholds are operational diagnostics only: <=20 minutes is `on_time`, >20 and <=60 minutes is `delayed`, and >60 minutes is `severely_delayed`. They do not alter model outputs, calibration, risk rules, promotion state or trading behavior.

## Safety

The audit makes no market-data calls and does not change the existing hourly cron cadence. It adds no paid API usage and no order path. The prediction artifact and schedule-delivery JSON are uploaded together so a skipped prediction can be distinguished from a scheduler-delivery problem.

## Next step

Collect several trading sessions of delivery diagnostics before changing cadence. If valid in-session cron slots repeatedly show `missed_regular_window=true`, then change scheduling architecture or add a bounded redundant trigger policy in a separate reviewed PR. Do not increase polling frequency based on one delayed run.
