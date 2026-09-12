# Regular-hours provenance recovery

## Purpose

Regular-hours V3.1 combines V1 and V2, but those model paths currently obtain their 5-minute public market data independently. Around a newly completed bar, the two reads can temporarily end on different timestamps. PR #51 made forward evidence fail closed when that happens, which protects validation integrity but can reduce usable forward-sample coverage.

This change adds a bounded recovery step to the cloud-shadow collector. It is deliberately a reliability measure, not a model change.

## Contract

For each requested symbol, the cloud-shadow collector may make at most three V3.1 attempts. It stops immediately when all of the following are true:

- `source_timestamp_aligned == true`
- `as_of` is present
- the existing V3/V3.1 provenance contract therefore proves that V1 and V2 refer to the same canonical source timestamp

There is a one-second delay between attempts in the scheduled runner. The retry does not alter probabilities, thresholds, calibration, risk logic, market-hours gating, or the downstream settlement policy.

If alignment is still absent after the bounded attempts, the observation remains provenance-invalid. No timestamp tolerance is introduced, no nearest-bar pairing is accepted, and `created_at_utc` is never substituted for the market-data cutoff.

## Measurable diagnostics

Cloud-shadow contract v2 records:

- `provenance_valid_symbol_count`
- `provenance_valid_coverage_pct`
- `alignment_retry_symbol_count`
- `alignment_attempt_count`
- per-symbol `alignment_attempts`

These fields let us distinguish transient provider timing from persistent pipeline misalignment and quantify how much forward evidence is actually usable.

## Safety boundary

This remains research-only shadow collection. Order submission stays disabled. The change does not promote a model, alter any trading recommendation threshold, add a paid provider, or change settlement scoring rules.

## Why this is not the final shared-snapshot architecture

A bounded retry is intentionally smaller and easier to validate than refactoring both model implementations at once. It can recover transient mismatches while keeping the strict fail-closed rule introduced by PR #51.

If forward runs continue to show material provenance loss or repeated retries, the next architectural step is a true shared immutable market snapshot: capture stock and benchmark frames once at a defined point-in-time cutoff, then pass those same frames into both V1 and V2. That refactor should be evaluated in its own PR with equivalence tests proving that model calculations remain unchanged apart from deterministic timestamp alignment.
