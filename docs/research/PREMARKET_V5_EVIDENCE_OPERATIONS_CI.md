# Premarket V5 evidence operations CI

## Why this exists

Monday 2026-09-14 is the first eligible Premarket V5 forward-collection session. The preregistered 06:45 ET snapshot had no corresponding scheduled GitHub Actions run after its acquisition-maturity window. The incident is classified as a delivery miss rather than backfilled: a later `workflow_dispatch` must not be relabelled as untouched forward evidence.

The repository already contains score-blind tooling that separates schedule delivery, workflow execution, artifact persistence, forecast completeness, and acquisition eligibility. During the incident audit, however, the focused Premarket pull-request workflow was found not to compile or execute the evidence-operations scripts and their dedicated regressions. Changes to this critical layer could therefore avoid the intended focused CI path.

## Change

The focused Premarket validation workflow now explicitly covers:

- GitHub Actions evidence collection,
- schedule-delivery auditing,
- collection-health auditing,
- unified evidence-health auditing,
- forward-readiness validation,
- Premarket V5 cloud-shadow and evidence-health workflow changes.

It also executes the existing regressions for Actions evidence provenance, schedule delivery, collection health, unified evidence health, forward acquisition, and snapshot scheduling.

## Research contract

This change does **not** alter the frozen 06:45 / 08:00 / 09:15 ET snapshot protocol, prediction features, model weights, calibration, thresholds, symbol universe, market-data provider, risk policy, broker integration, or order path. It does not make a missed snapshot forward-eligible retroactively.

The 2026-09-14 early-slot delivery miss remains an operational incident and is excluded from decision-grade forward evidence.

## Next step

Observe the remaining 08:00 ET and 09:15 ET Premarket V5 slots and the first Regular-hours scheduled collections. If delivery misses repeat after their maturity windows, treat the pattern as a scheduler-reliability problem and design delivery redundancy as a separately preregistered infrastructure change rather than weakening evidence eligibility.
