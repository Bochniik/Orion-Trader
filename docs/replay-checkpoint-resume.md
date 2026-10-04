# Replay checkpoint resume

Historical replay now resumes from a compatible checkpoint by default.

Compatibility is validated against runner id, evidence scope, period, interval, pre/post-market mode, and benchmark symbol. Completed symbols are skipped, cumulative prediction/settlement counts are preserved, and aggregate Brier/directional metric numerators and counts are carried forward.

Set `UniverseRunnerConfig(resume_from_checkpoint=False)` to force a fresh replay over the requested universe.

This path remains SIMULATED_FORWARD-only and does not write to LIVE_FORWARD.
