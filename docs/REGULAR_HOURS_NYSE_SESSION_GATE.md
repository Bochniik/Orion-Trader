# Regular-hours NYSE session gate

## Why this guard exists

The Regular-hours V3.1 cloud-shadow runner previously gated collection by New York weekday plus the 09:30-15:30 ET research window. That is not sufficient for forward evidence: Good Friday, Labor Day, Juneteenth and other recurring NYSE full-day closures can fall on weekdays. Running the model during such a closure risks reading the prior session's last intraday bar and creating an artifact that looks like a current-session observation.

## Contract

`scripts/run_regular_hours_v3_1_cloud_shadow.py` now reuses the deterministic `scripts/nyse_session_calendar.py` implementation already used by Premarket V5.

Before any model/provider execution, `regular_hours_gate()` requires all of the following:

1. the timestamp resolves to Monday-Friday in `America/New_York`;
2. the local calendar date is a recurring NYSE trading day;
3. the local clock is between 09:30 and 15:30 ET inclusive.

A weekday NYSE full-day closure returns `allowed=false`, `nyse_trading_day=false`, and `reason=market_holiday`. The payload is written as `status=skipped` with empty results, so it cannot masquerade as a live forward observation.

Weekends and ordinary out-of-window timestamps retain `reason=outside_regular_hours_shadow_window` so operational diagnostics can distinguish exchange holidays from normal scheduling misses.

The shared calendar is also included in the artifact lineage hash set. Any future modification to recurring exchange-calendar logic is therefore visible in immutable evidence provenance.

## Failure policy

The gate is deliberately fail-closed. A manual outside-session override does not bypass a recognized full-day NYSE holiday. No stale prior-session bar is promoted into regular-hours forward evidence simply because a cron event fired on a weekday.

The deterministic calendar models recurring published NYSE full-day holiday rules. It does not guess one-off emergency closures; those must remain observable collection failures rather than being silently classified as valid sessions.

## Regression coverage

Focused CI verifies Good Friday, Juneteenth, observed Independence Day, Labor Day, a normal weekday, weekends, and the New Year's Saturday edge where Friday 2021-12-31 remained an NYSE trading day. The existing shared calendar regression suite also runs whenever the regular-hours gate or calendar changes.

## Next step

Keep collecting real regular-hours artifacts and inspect `provenance_valid_coverage_pct`, alignment retries, scheduler-delivery drift, and valid-session coverage. If V1/V2 timestamp mismatches remain material after bounded retries, the next architectural improvement should be a shared immutable point-in-time market snapshot rather than loosening provenance tolerances.
