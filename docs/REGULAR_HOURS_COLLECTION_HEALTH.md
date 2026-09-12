# Regular-hours V3.1 collection health

## Purpose

This audit answers an operational question before Orion changes the regular-hours model architecture:

> Are real cloud-shadow observations arriving with enough point-in-time provenance quality to justify the current independent V1/V2 fetch design, or is a shared immutable snapshot needed?

It deliberately does **not** inspect predictive performance.

## Score-blind contract

`scripts/audit_regular_hours_collection_health.py` projects immutable Regular-hours V3.1 prediction artifacts down to operational fields only.

The report exposes:

- completed vs skipped artifact counts,
- standard 10-symbol universe vs custom-universe artifacts,
- distinct NYSE sessions represented,
- requested / available symbol counts,
- provenance-valid symbol count and fraction,
- provenance gaps,
- provider/runtime failures,
- alignment retry count and fraction,
- total and mean alignment attempts,
- per-session versions of the same operational coverage fields.

The report does **not** read or expose:

- `probability_up` / `probability_down`,
- bullish/bearish direction,
- directional accuracy,
- Brier score,
- log loss,
- realized returns or outcomes,
- calibration metrics.

A regression test mutates forecast probabilities and directions while holding the operational projection fixed and requires the collection-health report to remain byte-for-byte equivalent as a Python object.

## Fail-closed validation

Completed artifacts are accepted only when they remain research-only, order submission is disabled, the runtime was not modified, the regular-hours session gate was open, and the observation belongs to a deterministic NYSE trading day.

Operational counts are recomputed from symbol rows rather than trusted blindly. If the artifact-reported symbol, availability, provenance, retry, attempt, or failure counts disagree with the recomputed projection, the audit raises an error instead of publishing a misleading health report.

Skipped artifacts are counted separately and do not reduce market-time provenance coverage. Custom-universe completed runs are visible but excluded from the preregistered 10-symbol aggregate so manual experiments cannot contaminate standard collection health.

## Automation

`.github/workflows/regular-hours-collection-health.yml` runs once after the US close on weekdays. It recovers non-expired `regular-hours-v3-1-shadow-*` artifacts from the trailing 30 days, builds the score-blind report, and retains the report artifact for 90 days.

This workflow is intentionally separate from the market-time prediction workflow so operational auditing does not add latency or market-data requests to live shadow collection.

## Decision use

Do not change V3.1 probabilities, calibration, thresholds, or risk behavior based on this report.

Use several real sessions of `provenance_valid_fraction`, `alignment_retry_fraction`, failure frequency, and per-session stability to decide whether the next engineering step should be a shared immutable point-in-time market snapshot for V1 and V2. The evidence should precede that larger refactor rather than assuming retries are either sufficient or inadequate.
