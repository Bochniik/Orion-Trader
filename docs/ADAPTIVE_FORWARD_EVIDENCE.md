# Adaptive challenger forward-evidence lifecycle

This research-only gate sits between immutable challenger registration and tournament scoring.

A challenger is `tournament_ready` only when all supplied observations are strictly after its preregistered forward cutoff, use preregistered horizons, have valid timestamps and explicit trading-session identity, contain no duplicate `(timestamp, symbol, horizon)` observations, and satisfy caller-supplied minimum observation and distinct-session requirements.

The minimums are intentionally not hard-coded here: the evaluation protocol for a candidate must preregister them before evidence is inspected. This prevents adapting sample-size requirements after seeing challenger outcomes.

The gate does not score, promote, recalibrate, or modify runtime models. Failure is closed: insufficient, contaminated, duplicated, malformed, or wrong-horizon evidence remains not ready for tournament evaluation.

Next logical step: wire the preregistered evidence contract into the tournament entry point so scoring requires a positive readiness report, then validate that integration in the dedicated challenger CI before considering any model change.
