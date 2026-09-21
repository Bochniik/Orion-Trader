# Adaptive challenger forward-evidence lifecycle

This research-only gate sits between immutable challenger registration and tournament scoring.

A challenger is `tournament_ready` only when all supplied observations are strictly after its preregistered forward cutoff, use preregistered horizons, have valid timestamps and explicit trading-session identity, contain no duplicate `(timestamp, symbol, horizon)` observations, and satisfy preregistered minimum observation and distinct-session requirements.

The minimums are intentionally not hard-coded globally. Each candidate must include `evaluation_protocol.min_forward_observations` and `evaluation_protocol.min_forward_distinct_sessions` before registration. Because the evaluation protocol is part of the candidate's immutable SHA-256 material, the readiness gate reads those values directly from the validated registration and exposes no caller override. Missing, malformed, or non-positive preregistered minimums fail closed. This prevents adapting sample-size requirements after seeing challenger outcomes.

The gate does not score, promote, recalibrate, or modify runtime models. Failure is closed: insufficient, contaminated, duplicated, malformed, wrong-horizon, or contract-incomplete evidence remains not ready for tournament evaluation.

Next logical step: wire the positive readiness report into the tournament entry point so scoring cannot bypass the evidence lifecycle gate, then validate that integration in the dedicated challenger CI before considering any model change.
