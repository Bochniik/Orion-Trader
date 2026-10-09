# Data Reliability: acquisition/evidence incident handoff (2026-10-09)

Status: **open; research/shadow only**. This document records observed failures and remediation criteria. It is not a forward-evidence artifact, model validation, or evidence of successful collection.

## Verified on 2026-10-09 (UTC)

- `main` at `38658c7ff8cdc9f95349392b83b8bef15473458e`.
- [PR #365](https://github.com/Bochniik/Orion-Trader/pull/365), continuous premarket cloud collection, remains open. Exact-head `85922e67c365c13c478278d3c331d5ed756d080d`: [Premarket validation run 37837873775](https://github.com/Bochniik/Orion-Trader/actions/runs/37837873775) fails (145 passed, 2 failed) because the focused-test install excludes the declared `yfinance` dependency; backend analytics regression passed. **Do not merge before new exact-head required CI passes.**
- [Regular-hours collection-health run 37873816797](https://github.com/Bochniik/Orion-Trader/actions/runs/37873816797) fails with `ValueError: Artifact originated from unexpected workflow path`. Investigate the `scheduler-delivery-canary.yml` provenance path while retaining run ID, attempt, commit SHA, event type, and artifact-digest validation; never broadly disable origin checks.
- [Long-horizon evidence run 37869610701](https://github.com/Bochniik/Orion-Trader/actions/runs/37869610701): earlier artifact audit reported 17/120 delivered schedule slots, 103 missing, 0/20 critical 5h opportunities, and no evaluable 3h/5h observations. Treat these as *observed coverage*, not forecasts or accuracy evidence.
- [Issue #316](https://github.com/Bochniik/Orion-Trader/issues/316) remains open: the preregistered 2026-09-30 08:00 ET snapshot had 0/10 evaluable predictions. The current error reason conflates missing previous close and fewer than three current-day causal premarket bars.

## Recovery order and acceptance criteria

1. Fix PR #365 focused-validation installation to include the backend requirements plus pytest; keep an exact-head CI record. Separately ensure a failed/provider-unavailable/stale scan cannot publish a successful acquisition artifact. Outside 04:00–09:30 America/New_York, emit an explicit **skipped** result without a success artifact; GitHub cron uses UTC and includes slots outside the live window.
2. Only after the required checks pass and the PR is mergeable, merge PR #365. Verify at least one *actual scheduled* in-window scan on the merged `main` (not merely a green workflow). Record run ID/attempt, source event, NY-local time, symbols, scan status, candidate count, artifact digest, and whether a provider call completed.
3. Restore regular-hours collection-health by adding narrowly authorized canary provenance with regression tests. Re-run against the authentic immutable prediction artifact and confirm its digest remains unchanged.
4. Diagnose missing scheduled slots separately from provider failures and from prediction ineligibility. Retry only missing, valid windows; dedupe by session, scheduled slot, run/attempt, and immutable artifact identity. A recovery job must not backdate a forecast or invent forward evidence.
5. For #316, expose distinct per-symbol missing-prior-close versus insufficient-current-session-bars reasons, observed causal bar count, last bar UTC, and prior-session lookup status. Add an 08:00 ET frozen fixture, and check collector date/end semantics and feed/session coverage. Preserve `forward_eligible=false` when no prediction is evaluable.
6. Do not close #316 or promote models until real, preregistered multi-session forward evidence meets the documented gates. Insufficient data must remain fail-closed; do not adjust model weights, thresholds, or timestamps to make checks pass.

## Guardrails

This is an operational handoff only. Never use retrospective recovery artifacts as if they were contemporaneous predictions. Never disable provenance checks or rewrite immutable evidence to manufacture successful runs. A GitHub Actions `success` conclusion alone does not establish successful acquisition.
